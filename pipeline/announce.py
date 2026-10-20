"""公告偵測：自結、季報、營收、庫藏股、事件行事曆。

資料來源：公開資訊觀測站「指定日期全部重大訊息」（含內文，上市＋上櫃），每次執行抓今天，
第一次執行補抓近 14 天。所有公告存在 data/state/material_db.json，保留 45 天。

每筆公告都會標示 traded：公告後是否已經歷過一次 13:30 收盤（沒有＝市場還沒反映）。
"""
from __future__ import annotations

import hashlib
import logging
import re
import time as _time
from datetime import date, datetime, time, timedelta

from . import ai, config, findb, store
from .util import now_tw, read_json, write_json

log = logging.getLogger(__name__)
OUT = config.OUT_DIR / "announce"
KEEP_DAYS = 45      # 公告資料庫保留天數
SHOW_DAYS = 21      # 頁面顯示最近幾天的公告
NUM = r"\(?-?[\d,]+(?:\.\d+)?\)?"

EVENT_KINDS = [
    ("併購", ["合併", "收購", "併購", "公開收購", "股份轉換"]),
    ("增資/可轉債", ["現金增資", "轉換公司債", "私募", "增資"]),
    ("資產交易", ["取得", "處分", "使用權資產", "機器設備", "不動產"]),
    ("澄清", ["澄清", "媒體報導"]),
    ("人事", ["人事異動", "董事長", "總經理", "財務主管", "辭任", "解任"]),
    ("訂單/合約", ["訂單", "合約", "簽訂", "得標"]),
    ("減資", ["減資"]),
]

RUBRIC = {
    "att": "自結損益驚喜度。① 驚喜度：單月 EPS 對比上季月均（上季 EPS÷3），大幅超越＝驚喜；② 延續性：獲利趨勢能否持續；③ 獲利品質：本業驅動優於業外。",
    "fin": "季報驚喜度。① 驚喜度：單季 EPS 對比上季，大幅成長＝驚喜；② 延續性；③ 獲利品質：毛利率、營益率改善且業外占比低較佳。",
    "rev": "月營收。① 驚喜度：同樣成長率，營收規模越大越驚人；低基期造成的高年增要扣分；② 延續性：月增連續加速優於單月跳升，結構性成長優於一次性認列；③ 資訊品質：備註有具體產品/客戶/訂單加分，制式文字不加分。",
}
SCALE = "評分 -9 到 +9 的整數：+8~9 高度超預期｜+6~7 值得關注｜+4~5 有亮點待觀察｜+1~3 符合預期｜0 無特別資訊｜負分＝衰退警示。"


# ------------------------------------------------------------------ 小工具

def _key(*xs) -> str:
    return hashlib.md5("|".join(map(str, xs)).encode()).hexdigest()[:12]


def pnum(s: str | None) -> float | None:
    """'(0.04)' → -0.04、'1,675' → 1675、'-' → None"""
    if s is None:
        return None
    s = s.strip().replace(",", "").rstrip("%")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def roc_date(s: str) -> date | None:
    m = re.search(r"(\d{2,3})\s*[/年.]\s*(\d{1,2})\s*[/月.]\s*(\d{1,2})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _traded(ann_date: str, ann_time: str, last_close_day: date | None) -> bool:
    """公告後是否已經過至少一次 13:30 收盤"""
    if not last_close_day or not ann_date:
        return False
    try:
        hh, mm = (int(x) for x in (ann_time or "00:00").split(":")[:2])
        dt = datetime.combine(date.fromisoformat(ann_date), time(hh, mm))
    except ValueError:
        return False
    return dt < datetime.combine(last_close_day, time(13, 30))


def _cutoff_label(last_close_day: date | None) -> str:
    return f"{last_close_day.month}/{last_close_day.day} 13:30" if last_close_day else ""


# ------------------------------------------------------------------ 公告資料庫

def update_material(fetch_day, today: date) -> dict:
    """抓今天（第一次跑時補近 14 天，之後每天補抓昨天一次）的全部重大訊息，存入資料庫"""
    db = store.state("material_db", {}) or {}
    fetched = db.setdefault("_fetched", {})
    days = [today]
    if not fetched:
        days += [today - timedelta(days=i) for i in range(1, 15)]
    else:
        y = today - timedelta(days=1)
        if fetched.get(y.isoformat(), "") < f"{today.isoformat()} 00:00":
            days.append(y)
    for d in days:
        if d.weekday() >= 5 and d != today:
            continue
        rows = fetch_day(d)
        if rows is None:
            continue
        for m in rows:
            k = _key(m["date"], m["time"], m["code"], m["subject"][:60])
            if k not in db:
                db[k] = m
        fetched[d.isoformat()] = now_tw().strftime("%Y-%m-%d %H:%M")
        if len(days) > 1:
            _time.sleep(3)
    cut = (today - timedelta(days=KEEP_DAYS)).isoformat()
    for k in [k for k, v in db.items() if not k.startswith("_") and v.get("date", "") < cut]:
        db.pop(k)
    store.save_state("material_db", db)
    return db


# ------------------------------------------------------------------ 解析

def _lines_with(body: str, word: str) -> list[list[float]]:
    out = []
    for ln in body.splitlines():
        if word in ln:
            nums = [pnum(x) for x in re.findall(NUM + "%?", ln.split(word, 1)[1])]
            nums = [x for x in nums if x is not None]
            if nums:
                out.append(nums)
    return out


def _period_of(text: str) -> tuple[str, int]:
    """回傳 (顯示用期間, 涵蓋月數)"""
    t = text.replace(" ", "")
    if re.search(r"前三季|第[一1]季[至~～-]第[三3]季|Q1.?Q3", t):
        return "Q1~Q3", 9
    if re.search(r"前二季|上半年|第[一1]季[至~～-]第[二2]季|Q1.?Q2", t):
        return "H1", 6
    m = re.search(r"第([一二三四1-4])季", t)
    if m:
        return "Q" + str("一二三四".index(m.group(1)) + 1 if m.group(1) in "一二三四" else m.group(1)), 3
    m = re.search(r"(\d{1,2})月", t)
    if m:
        return f"{int(m.group(1))}月", 1
    return "", 1


def parse_att(subject: str, body: str) -> dict:
    """自結：注意股的財務業務資訊表格，或公司自願公告的自結數"""
    out = {"eps": None, "rev": None, "period": "", "months": 1, "q_eps": None, "q_label": ""}
    eps_lines = _lines_with(body, "每股")
    rev_lines = _lines_with(body, "營業收入")
    if eps_lines and len(eps_lines[0]) >= 4:          # 證交所格式：月、增減%、季、增減%、四季累計
        out["eps"], out["q_eps"] = eps_lines[0][0], eps_lines[0][2]
        out["rev"] = rev_lines[0][0] if rev_lines else None
    elif eps_lines:                                    # 櫃買格式：單月、單季、四季分段
        out["eps"] = eps_lines[0][0]
        out["q_eps"] = eps_lines[1][0] if len(eps_lines) > 1 else None
        out["rev"] = rev_lines[0][0] if rev_lines else None
    if "注意交易資訊" in subject or "財務業務資訊" in body:
        m = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月", body)
        out["period"], out["months"] = (f"{int(m.group(2))}月", 1) if m else ("", 1)
        mq = re.search(r"(\d{2,3})\s*年?\s*第\s*(\d)\s*季", body)
        out["q_label"] = f"Q{mq.group(2)}" if mq else ""
    else:
        out["period"], out["months"] = _period_of(subject + " " + body[:300])
        if out["eps"] is None:
            m = re.search(r"每股[^\d\-(]{0,20}?(?:NTD|新台幣|NT\$)?\s*(" + NUM + ")", body)
            out["eps"] = pnum(m.group(1)) if m else None
    return out


def is_att(subject: str, body: str) -> bool:
    if re.search(r"流動比率|速動比率|負債比率", subject):
        return False
    return "自結" in subject or ("注意交易資訊" in subject and "財務業務" in subject) or \
        ("財務業務資訊" in body and "每股" in body)


FIN_FIELDS = [("rev", r"營業收入"), ("gross", r"營業毛利"), ("op", r"營業利益"), ("pretax", r"稅前淨利"),
              ("net", r"歸屬於母公司業主淨利"), ("eps", r"基本每股盈餘")]


def parse_fin(body: str) -> dict | None:
    """『財務報告業經董事會通過』格式：1 月 1 日累計至本期止的各項數字"""
    if "累計至本期止" not in body:
        return None
    rng = re.search(r"(\d{2,3})/(\d{2})/(\d{2})\s*[~～-]\s*(\d{2,3})/(\d{2})/(\d{2})", body)
    if not rng:
        return None
    y, end_m = int(rng.group(4)), int(rng.group(5))
    q = (end_m - 1) // 3 + 1
    out = {"year": y, "q": q}
    for k, word in FIN_FIELDS:
        m = re.search(r"累計至本期止" + word + r"[^:：]*[:：]\s*(" + NUM + ")", body)
        out[k] = pnum(m.group(1)) if m else None
    return out


def is_fin(subject: str, body: str) -> bool:
    return ("財務報告" in subject or "財務報表" in subject) and "累計至本期止" in body


PURPOSE = [("員工", "員工"), ("維護公司信用", "護盤"), ("股東權益", "護盤"), ("註銷", "銷除"), ("銷除", "銷除")]


def parse_treasury(body: str) -> dict | None:
    n = re.search(r"預定買回之數量[^:：]*[:：]\s*([\d,]+)", body)
    if not n:
        return None
    pm = re.search(r"買回股份目的[:：]\s*([^\n\r]+)", body)
    purpose = next((v for k, v in PURPOSE if pm and k in pm.group(1)), (pm.group(1).strip()[:6] if pm else ""))
    rng = re.search(r"買回區間價格[^:：]*[:：]\s*([\d.]+)\s*[~～至-]\s*([\d.]+)", body)
    per = re.search(r"預定買回之期間[:：]\s*(\d{2,3}/\d{1,2}/\d{1,2})\s*[~～至-]\s*(\d{2,3}/\d{1,2}/\d{1,2})", body)
    dd = re.search(r"董事會決議日期[:：]\s*(\d{2,3}/\d{1,2}/\d{1,2})", body)
    return {"shares": int(n.group(1).replace(",", "")), "purpose": purpose,
            "low": float(rng.group(1)) if rng else None, "high": float(rng.group(2)) if rng else None,
            "start": str(roc_date(per.group(1))) if per else None, "end": str(roc_date(per.group(2))) if per else None,
            "board": str(roc_date(dd.group(1))) if dd else None}


def parse_treasury_done(body: str) -> dict | None:
    done = re.search(r"實際已買回股數[^:：\d]*[:：]?\s*([\d,]+)", body)
    plan = re.search(r"預定買回[^\d]{0,12}股數[^:：\d]*[:：]?\s*([\d,]+)", body)
    if not done:
        return None
    d = int(done.group(1).replace(",", ""))
    p = int(plan.group(1).replace(",", "")) if plan else None
    return {"done": d, "plan": p, "pct": round(d / p * 100) if p else None}


def parse_event(subject: str, body: str) -> dict | None:
    """行事曆事件：法說會、財報董事會、除權息"""
    if re.search(r"法人說明會|法說會", subject):
        ds = re.findall(r"\d{2,3}/\d{1,2}/\d{1,2}", (re.search(r"召開法人說明會之日期[:：]([^\n\r]+)", body) or [None, ""])[1])
        if ds:
            return {"kind": "法", "from": str(roc_date(ds[0])), "to": str(roc_date(ds[-1]))}
    if re.search(r"董事會預計召開日期", subject + body):
        m = re.search(r"董事會預計召開日期[:：]\s*(\d{2,3}/\d{1,2}/\d{1,2})", body)
        if m:
            return {"kind": "財", "from": str(roc_date(m.group(1))), "to": str(roc_date(m.group(1)))}
    if re.search(r"除權|除息", subject) and re.search(r"除權（息）交易日|除權\(息\)交易日|除息交易日|除權交易日", body):
        m = re.search(r"除權[（(]息[)）]交易日[:：]\s*(\d{2,3}/\d{1,2}/\d{1,2})", body) or \
            re.search(r"除[權息]交易日[:：]\s*(\d{2,3}/\d{1,2}/\d{1,2})", body)
        t = re.search(r"除權、息類別[^:：]*[:：]\s*(除權息|除權|除息)", body)
        kind = {"除權息": "權息", "除權": "權", "除息": "息"}.get(t.group(1) if t else "", "息")
        if m:
            return {"kind": kind, "from": str(roc_date(m.group(1))), "to": str(roc_date(m.group(1)))}
    return None


# ------------------------------------------------------------------ AI

def _ai_score(kind: str, items: list[dict]) -> None:
    """為還沒評過分的項目打分（-9~+9），結果直接寫回 item；沒有 AI 時用規則分數"""
    todo = [i for i in items if i.get("score_src") != "ai"]
    if ai.enabled():
        for chunk in [todo[i:i + 40] for i in range(0, min(len(todo), 400), 40)]:
            lines = "\n".join(f"{i['code']} {i['name']}：{i['facts']}" for i in chunk)
            res = ai.ask_json(
                f"你是台股研究助理。以下是剛公布的資料，請依『{RUBRIC[kind]}』逐筆獨立判斷。\n{SCALE}\n"
                "理由 20 字內，只能根據提供的數字與文字，不可編造。\n"
                f"{lines}\n\n格式：{{\"代號\": {{\"score\": 整數, \"why\": \"理由\"}}}}", tag=f"score-{kind}", max_tokens=6000)
            if not isinstance(res, dict):
                continue
            for i in chunk:
                r = res.get(i["code"])
                if isinstance(r, dict) and str(r.get("score", "")).lstrip("+-").isdigit():
                    i["score"], i["why"], i["score_src"] = max(-9, min(9, int(r["score"]))), str(r.get("why", ""))[:40], "ai"
    for i in items:
        if i.get("score_src") != "ai":
            i["score"], i["score_src"] = i.get("rule_score"), "rule"


def _rule_score(new: float | None, base: float | None) -> int | None:
    """沒有 AI 時的規則分：相對基準的變化，±100% 約 ±6 分"""
    if new is None or base is None:
        return None
    ratio = (new - base) / max(abs(base), 0.05)
    return max(-9, min(9, round(ratio * 6)))


def _ai_extract_att(items: list[dict]) -> None:
    """規則抽不到 EPS 的自結公告，請 AI 從原文抽取"""
    todo = [i for i in items if i.get("eps") is None and not i.get("extract_tried")][:20]
    if not todo or not ai.enabled():
        return
    lines = "\n\n".join(f"[{i['code']}] {i['subject']}\n{i['body'][:1200]}" for i in todo)
    res = ai.ask_json(
        "以下是台股公司的自結損益公告原文。請抽出：期間（例如 9月、Q3、Q1~Q3）、該期間 EPS（元）、"
        "營業收入（百萬元）、毛利率%、營益率%。原文沒有的填 null，不可推算或編造。\n"
        f"{lines}\n\n格式：{{\"代號\": {{\"period\": \"\", \"eps\": 數字或null, \"rev\": 數字或null, \"gm\": 數字或null, \"om\": 數字或null}}}}",
        tag="extract-att", max_tokens=3000)
    for i in todo:
        i["extract_tried"] = True
        r = (res or {}).get(i["code"]) if isinstance(res, dict) else None
        if isinstance(r, dict):
            for k in ("eps", "rev", "gm", "om"):
                if isinstance(r.get(k), (int, float)):
                    i[k] = float(r[k])
            if r.get("period"):
                i["period"], i["months"] = r["period"], _period_of(r["period"])[1]
            i["extracted_by"] = "ai"


# ------------------------------------------------------------------ 主流程

def build(material: list[dict], revenue: list[dict], quotes: list[dict], last_close_day: date | None,
          exrights: list[dict] | None = None) -> dict:
    now = now_tw().strftime("%Y-%m-%d %H:%M")
    today = now_tw().date()
    qm = {q["code"]: q for q in quotes}
    fdb = store.state("fin_db", {}) or {}
    show_cut = (today - timedelta(days=SHOW_DAYS)).isoformat()

    def px(code):
        q = qm.get(code)
        if not q:
            return {}
        return {"close": q["close"], "chg": round((q["close"] / q["prev_close"] - 1) * 100, 2) if q["prev_close"] else None}

    def close_on(code: str, d: str) -> tuple[float | None, str | None]:
        """d 當天（或之前最近一個交易日）的收盤"""
        try:
            dd = date.fromisoformat(d)
        except ValueError:
            return None, None
        for x in store.days_before(dd, 1) or []:
            c = store.load_day(x).get(code, {}).get("close")
            return c, x.isoformat()
        return None, None

    old = {n: {x["key"]: x for x in (read_json(OUT / f"{n}.json", {}) or {}).get("items", [])}
           for n in ("att", "fin", "rev", "treasury", "events", "others")}

    def keep(name, it):
        """沿用舊資料的首次偵測時間、評分與 AI 抽取結果"""
        o = old[name].get(it["key"])
        it["first_seen"] = o["first_seen"] if o else now
        it["new"] = not o
        if o:
            if o.get("score_src") == "ai":
                for k in ("score", "why", "score_src"):
                    it[k] = o.get(k)
            it["extract_tried"] = o.get("extract_tried", False)
            if o.get("extracted_by") == "ai":
                for k in ("eps", "rev", "gm", "om", "period", "months", "extracted_by"):
                    if k in o:
                        it[k] = o[k]
        return it

    att, fin, treasury_new, treasury_done, events, others = [], [], [], [], [], []
    for m in sorted(material, key=lambda x: (x["date"], x["time"])):
        s, b = m["subject"], m["body"]
        base = {"key": _key(m["date"], m["time"], m["code"], s[:60]), "date": m["date"], "time": m["time"],
                "code": m["code"], "name": m["name"], "market": m["market"], "subject": s, "body": b[:6000],
                "traded": _traded(m["date"], m["time"], last_close_day), **px(m["code"])}
        if is_att(s, b):
            if m["date"] < show_cut:
                continue
            p = parse_att(s, b)
            last = findb.latest_single(fdb, m["code"])
            q_eps = p["q_eps"] if p["q_eps"] is not None else (last or {}).get("eps")
            att.append(keep("att", {**base, **p, "base_label": p["q_label"] or (last or {}).get("label", ""),
                                    "base_eps": q_eps, "base_eps_m": round(q_eps / 3, 2) if q_eps is not None else None,
                                    "base_gm": (last or {}).get("gm"), "base_om": (last or {}).get("om")}))
        elif is_fin(s, b):
            if m["date"] < show_cut:
                continue
            f = parse_fin(b) or {}
            y, q = f.get("year"), f.get("q")
            single = dict(f)
            prev_cum = (fdb.get(m["code"]) or {}).get(f"{y}Q{q - 1}") if q and q > 1 else None
            if q and q > 1:
                for k in ("rev", "gross", "op", "pretax", "eps"):
                    single[k] = round(f[k] - prev_cum[k], 2) if prev_cum and f.get(k) is not None and prev_cum.get(k) is not None else None
            rev = single.get("rev")
            prev = findb.single(fdb, m["code"], y, q - 1) if q and q > 1 else findb.single(fdb, m["code"], y - 1, 4) if y else None
            fin.append(keep("fin", {**base, "period": f"{y + 1911}Q{q}" if y else "", "cum_eps": f.get("eps"),
                                    "eps": single.get("eps"), "rev": rev,
                                    "gm": round(single["gross"] / rev * 100, 2) if rev and single.get("gross") is not None else None,
                                    "om": round(single["op"] / rev * 100, 2) if rev and single.get("op") is not None else None,
                                    "nonop_pct": round((single["pretax"] - single["op"]) / single["pretax"] * 100, 2)
                                    if single.get("pretax") and single.get("op") is not None else None,
                                    "single_ok": bool(q == 1 or prev_cum),
                                    "prev_label": (prev or {}).get("label", ""), "prev_eps": (prev or {}).get("eps"),
                                    "prev_gm": (prev or {}).get("gm"), "prev_om": (prev or {}).get("om"),
                                    "prev_nonop_pct": (prev or {}).get("nonop_pct")}))
        elif re.search(r"買回", s) and parse_treasury(b):
            treasury_new.append({**base, **parse_treasury(b)})
        elif re.search(r"買回", s) and re.search(r"屆滿|執行完畢|執行情形", s + b[:200]) and parse_treasury_done(b):
            treasury_done.append({**base, **parse_treasury_done(b)})
        else:
            ev = parse_event(s, b)
            if ev:
                events.append({**base, **ev})
            elif m["date"] >= show_cut:
                kind = next((k for k, kws in EVENT_KINDS if any(w in s for w in kws)), "其他")
                others.append(keep("others", {**base, "kind": kind}))

    # ---------- 自結：AI 抽取補缺、比較基準、評分
    _ai_extract_att(att)
    for a in att:
        a["eps_m"] = round(a["eps"] / max(a.get("months") or 1, 1), 2) if a.get("eps") is not None else None
        a["rule_score"] = _rule_score(a["eps_m"], a.get("base_eps_m"))
        a["facts"] = f"{a.get('period') or '期間不明'} EPS {a.get('eps')}（月均 {a['eps_m']}），上季 {a.get('base_label')} EPS {a.get('base_eps')}" \
                     f"（月均 {a.get('base_eps_m')}），營收 {a.get('rev')} 百萬，上季毛利率 {a.get('base_gm')}%、營益率 {a.get('base_om')}%"
    _ai_score("att", [a for a in att if a.get("eps") is not None])

    for f in fin:
        f["rule_score"] = _rule_score(f.get("eps"), f.get("prev_eps"))
        f["facts"] = f"{f['period']} 單季 EPS {f.get('eps')}（累計 {f.get('cum_eps')}），毛利率 {f.get('gm')}%、營益率 {f.get('om')}%、業外占稅前 {f.get('nonop_pct')}%；" \
                     f"上季 EPS {f.get('prev_eps')}、毛利率 {f.get('prev_gm')}%、營益率 {f.get('prev_om')}%"
    _ai_score("fin", [f for f in fin if f.get("eps") is not None or f.get("cum_eps") is not None])

    # ---------- 營收
    hist = store.state("rev_hist", {}) or {}
    rev = []
    for r in revenue:
        h = hist.setdefault(r["code"], {})
        if r.get("rev") is not None:
            h[r["ym"]] = r["rev"]
        months = sorted(h)[-7:]
        it = keep("rev", {"key": _key("rev", r["ym"], r["code"]), "date": "", "time": "",
                          **{k: r[k] for k in ("ym", "code", "name", "market", "industry", "rev", "mom", "yoy", "cum", "cum_yoy", "note")},
                          "hist": [[ym, h[ym]] for ym in months], **px(r["code"])})
        fs = it["first_seen"]
        it["date"], it["time"] = fs[:10], fs[11:16]
        it["traded"] = _traded(it["date"], it["time"], last_close_day)
        trend = [round((h[months[i]] / h[months[i - 1]] - 1) * 100, 1) for i in range(1, len(months)) if h[months[i - 1]]]
        it["facts"] = f"營收 {round((r['rev'] or 0) / 1000, 1)} 百萬，月增 {_f(r['mom'])}%、年增 {_f(r['yoy'])}%、累計年增 {_f(r['cum_yoy'])}%；" \
                      f"近月月增 {trend[-5:]}；備註：{(r['note'] or '無')[:80]}"
        it["rule_score"] = None if r["yoy"] is None else max(-9, min(9, round((r["yoy"] or 0) / 15)))
        rev.append(it)
    store.save_state("rev_hist", hist)
    _ai_score("rev", rev)

    # ---------- 庫藏股：決議與執行結果合併成「買回計畫」
    programs = store.state("treasury_db", {}) or {}
    for t in treasury_new:
        programs.setdefault(t["key"], {k: t[k] for k in ("key", "code", "name", "market", "date", "time", "subject", "body",
                                                         "shares", "purpose", "low", "high", "start", "end", "board")})
    for d in treasury_done:  # 對到同公司最近一個計畫
        cands = sorted((p for p in programs.values() if p["code"] == d["code"] and p["date"] <= d["date"]), key=lambda p: p["date"])
        if cands:
            cands[-1].update({"done_shares": d["done"], "progress": d["pct"], "done_date": d["date"], "done_body": d["body"][:3000]})
    cut = (today - timedelta(days=180)).isoformat()
    programs = {k: v for k, v in programs.items() if v["date"] >= cut}
    store.save_state("treasury_db", programs)
    treasury = []
    for p in programs.values():
        st = "完成" if p.get("progress") is not None or (p.get("end") and p["end"] < today.isoformat()) else \
             "執行中" if p.get("start") and p["start"] <= today.isoformat() else "待執行"
        treasury.append(keep("treasury", {**p, "status": st, "traded": _traded(p["date"], p["time"], last_close_day),
                                          "lots": round(p["shares"] / 10000, 1), **px(p["code"])}))

    # ---------- 事件行事曆（法說、財報、除權息），加上交易所除權息預告表補漏
    cal = {}
    for e in events:
        k = _key("ev", e["code"], e["kind"], e["from"])
        cal[k] = {**e, "key": k}
    for x in exrights or []:
        k = _key("ev", x["code"], x["kind"], x["from"])
        if not any(v["code"] == x["code"] and v["from"] == x["from"] for v in cal.values()):
            cal[k] = {"key": k, "date": "", "time": "", "subject": f"除權息預告（{x['kind']}）", "body": x.get("detail", ""),
                      "traded": True, **x, **px(x["code"])}
    ev_out = []
    for e in cal.values():
        e = keep("events", e)
        if not e.get("date"):
            e["date"] = e["first_seen"][:10]
        ann_close, ann_day = close_on(e["code"], e["date"])
        cur = qm.get(e["code"], {}).get("close")
        e["ann_close"], e["ann_day"] = ann_close, ann_day
        e["chg_since"] = round((cur / ann_close - 1) * 100, 2) if cur and ann_close else None
        e["days_since"] = len([d for d in store.trading_days() if ann_day and d.isoformat() > ann_day]) if ann_day else None
        e["upcoming"] = (e.get("to") or e.get("from") or "") >= today.isoformat()
        if e["upcoming"] or (e.get("to") or "") >= (today - timedelta(days=10)).isoformat():
            ev_out.append(e)

    res = {"att": att, "fin": fin, "rev": rev, "treasury": treasury, "events": ev_out, "others": others}
    sorters = {
        "att": lambda x: (x["date"], x["time"]), "fin": lambda x: (x["date"], x["time"]),
        "rev": lambda x: (x["first_seen"], x.get("score") or 0), "treasury": lambda x: (x.get("board") or x["date"]),
        "events": lambda x: x.get("from") or "", "others": lambda x: (x["date"], x["time"]),
    }
    for name, items in res.items():
        items.sort(key=sorters[name], reverse=name != "events")
        for i in items:
            i.pop("facts", None)
            i.pop("rule_score", None)
        write_json(OUT / f"{name}.json", {"updated": now, "last_close": last_close_day.isoformat() if last_close_day else None,
                                          "cutoff": _cutoff_label(last_close_day), "items": items})
    return res


def _f(x):
    return None if x is None else round(x, 1)
