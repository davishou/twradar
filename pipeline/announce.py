"""公告偵測：自結、季報、營收、庫藏股、重大事件。
每次執行都和已見清單比對，新出現的標記 new 並記下首次偵測時間；
同時標示公告是否已經歷過一次收盤（『這筆公告被交易過了嗎？』）。"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta

from . import ai, config, store
from .util import now_tw, read_json, write_json

log = logging.getLogger(__name__)
OUT = config.OUT_DIR / "announce"
KEEP_DAYS = 10

EVENT_KINDS = [
    ("併購", ["合併", "收購", "併購", "公開收購", "股份轉換"]),
    ("增資/可轉債", ["現金增資", "轉換公司債", "私募", "增資"]),
    ("資產交易", ["取得", "處分", "使用權資產", "機器設備", "不動產"]),
    ("股利", ["股利", "配息", "除息", "除權"]),
    ("澄清", ["澄清", "媒體報導"]),
    ("法說會", ["法人說明會", "法說會"]),
    ("人事", ["人事異動", "董事長", "總經理", "財務主管", "辭任", "解任"]),
    ("訂單/合約", ["訂單", "合約", "簽訂", "得標"]),
    ("減資", ["減資"]),
]

RE_EPS = re.compile(r"(?:每股盈餘|每股稅後盈餘|EPS)[^0-9\-－]{0,12}([\-－]?\d+(?:\.\d+)?)", re.I)


def _key(*xs) -> str:
    return hashlib.md5("|".join(map(str, xs)).encode()).hexdigest()[:12]


def _traded(ann_date: str, ann_time: str, last_close_day: date | None) -> bool:
    """公告後是否已經過至少一次 13:30 收盤"""
    if not last_close_day or not ann_date:
        return False
    try:
        hh, mm = (int(x) for x in (ann_time or "00:00").split(":")[:2])
        dt = datetime.combine(date.fromisoformat(ann_date), time(hh, mm))
    except ValueError:
        return False
    close_dt = datetime.combine(last_close_day, time(13, 30))
    return dt < close_dt


def _period(text: str) -> str:
    m = re.search(r"(前三季|前二季|上半年|第[一二三四]季|Q[1-4]\s*[~～-]\s*Q[1-4]|Q[1-4]|\d{1,2}\s*月)", text)
    return m.group(1).replace(" ", "") if m else ""


def _months(period: str) -> int:
    if "前三季" in period or re.search(r"Q1.?Q3", period):
        return 9
    if "前二季" in period or "上半年" in period or re.search(r"Q1.?Q2", period):
        return 6
    if "季" in period or re.fullmatch(r"Q[1-4]", period):
        return 3
    return 1


def _last_quarter_eps(eps_rows: list[dict]) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for r in eps_rows:
        if r["eps"] is None:
            continue
        cur = best.get(r["code"])
        if not cur or (r["year"], r["quarter"]) > (cur["year"], cur["quarter"]):
            best[r["code"]] = r
    return best


def _rule_score(monthly: float | None, base: float | None) -> int:
    if monthly is None or base is None:
        return 0
    ratio = (monthly - base) / max(abs(base), 0.1)
    return max(-5, min(5, round(ratio * 2)))


def _ai_scores(items: list[dict], kind: str) -> dict:
    if not items or not ai.enabled():
        return {}
    lines = "\n".join(f"{i['code']} {i['name']}：{i['summary']}" for i in items)
    res = ai.ask_json(
        f"以下是台股公司剛公布的{kind}。請為每筆給一個 -5 到 +5 的整數分數，代表相對公司近期水準"
        "的驚喜程度（+5 大幅優於、0 持平、-5 大幅轉差），並給 20 字內理由。\n"
        f"{lines}\n格式：{{\"代號\": {{\"score\": 整數, \"why\": \"理由\"}}}}")
    return res if isinstance(res, dict) else {}


def _merge(name: str, items: list[dict], now: str) -> list[dict]:
    """與既有清單合併，新項目標記 new"""
    old = read_json(OUT / f"{name}.json", {}) or {}
    prev = {x["key"]: x for x in old.get("items", [])}
    out = []
    for it in items:
        p = prev.pop(it["key"], None)
        it["first_seen"] = p["first_seen"] if p else now
        it["new"] = not p
        out.append(it)
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    for p in prev.values():  # 來源只保留當日，舊的我們自己留著
        if p.get("date", "") >= cutoff:
            p["new"] = False
            out.append(p)
    return out


def build(material: list[dict], revenue: list[dict], eps_rows: list[dict], quotes: list[dict],
          last_close_day: date | None) -> dict:
    now = now_tw().strftime("%Y-%m-%d %H:%M")
    qm = {q["code"]: q for q in quotes}
    lq = _last_quarter_eps(eps_rows)

    def px(code):
        q = qm.get(code)
        if not q:
            return {}
        return {"close": q["close"], "chg": round((q["close"] / q["prev_close"] - 1) * 100, 2) if q["prev_close"] else None}

    att, treasury, events = [], [], []
    for m in material:
        s, b = m["subject"], m["body"]
        base = {"key": _key(m["date"], m["time"], m["code"], s), "date": m["date"], "time": m["time"],
                "code": m["code"], "name": m["name"], "market": m["market"], "subject": s,
                "traded": _traded(m["date"], m["time"], last_close_day), **px(m["code"])}
        if "自結" in s or ("自結" in b and ("損益" in s or "財務" in s)):
            em = RE_EPS.search(b) or RE_EPS.search(s)
            eps = float(em.group(1).replace("－", "-")) if em else None
            per = _period(s + " " + b)
            months = _months(per)
            q = lq.get(m["code"])
            qm_eps = round(q["eps"] / 3, 2) if q else None
            att.append({**base, "period": per, "eps": eps, "eps_monthly": round(eps / months, 2) if eps is not None else None,
                        "last_q": f"{q['year']}Q{q['quarter']}" if q else None, "last_q_monthly": qm_eps,
                        "summary": f"{per} EPS {eps}，上季月均 {qm_eps}"})
        elif re.search(r"買回本公司股份|庫藏股", s):
            lots = re.search(r"預定買回股數[：:\s]*([\d,]+)\s*(張|股)", b)
            rng = re.search(r"買回價格區間[：:\s]*([\d.]+)\s*元?\s*(?:至|~|～|-)\s*([\d.]+)", b)
            n = None
            if lots:
                n = int(lots.group(1).replace(",", ""))
                n = n if lots.group(2) == "張" else n // 1000
            treasury.append({**base, "lots": n, "low": float(rng.group(1)) if rng else None,
                             "high": float(rng.group(2)) if rng else None, "body": b[:300]})
        else:
            kind = next((k for k, kws in EVENT_KINDS if any(w in s for w in kws)), "其他")
            events.append({**base, "kind": kind, "body": b[:300]})

    # 自結評分
    seen = {x["key"]: x for x in (read_json(OUT / "att.json", {}) or {}).get("items", [])}
    sc = _ai_scores([a for a in att if a["eps"] is not None and a["key"] not in seen][:60], "自結損益")
    for a in att:  # 已評過分的沿用
        if a["key"] in seen and a["code"] not in sc and seen[a["key"]].get("score_src") == "ai":
            sc[a["code"]] = {"score": seen[a["key"]]["score"], "why": seen[a["key"]].get("why", "")}
    for a in att:
        r = sc.get(a["code"]) if isinstance(sc.get(a["code"]), dict) else None
        a["score"] = int(r["score"]) if r and str(r.get("score", "")).lstrip("-").isdigit() else _rule_score(a["eps_monthly"], a["last_q_monthly"])
        a["score_src"] = "ai" if r else "rule"
        a["why"] = (r or {}).get("why", "")

    # 季報：只看最新一季，與上一季比較
    by = {}
    for r in eps_rows:
        by.setdefault(r["code"], {})[(r["year"], r["quarter"])] = r
    latest = max(((r["year"], r["quarter"]) for r in eps_rows), default=None)
    fin = []
    if latest:
        for code, qs in by.items():
            r = qs.get(latest)
            if not r or r["eps"] is None:
                continue
            y, qn = latest
            pq = qs.get((y, qn - 1)) if qn > 1 else qs.get((y - 1, 4))
            ly = qs.get((y - 1, qn))
            fin.append({"key": _key("fin", y, qn, code), "date": date.today().isoformat(), "time": "", "code": code,
                        "name": r["name"], "market": r["market"], "period": f"{y}Q{qn}", "eps": r["eps"],
                        "eps_prev_q": pq["eps"] if pq else None, "eps_ly": ly["eps"] if ly else None,
                        "summary": f"{y}Q{qn} EPS {r['eps']}，上季 {pq['eps'] if pq else '—'}", **px(code)})
        seen = {x["key"]: x for x in (read_json(OUT / "fin.json", {}) or {}).get("items", [])}
        sc = _ai_scores([f for f in fin if f["key"] not in seen][:60], "季報")  # 只評新公布的
        for f in fin:
            old = seen.get(f["key"])
            if old and old.get("score_src") == "ai":
                f["score"], f["score_src"] = old["score"], "ai"
                continue
            r = sc.get(f["code"]) if isinstance(sc.get(f["code"]), dict) else None
            f["score"] = int(r["score"]) if r and str(r.get("score", "")).lstrip("-").isdigit() else _rule_score(f["eps"], f["eps_prev_q"])
            f["score_src"] = "ai" if r else "rule"

    rev = []
    for r in revenue:
        rev.append({"key": _key("rev", r["ym"], r["code"]), "date": date.today().isoformat(), "time": "",
                    **{k: r[k] for k in ("ym", "code", "name", "market", "industry", "rev", "mom", "yoy", "cum", "cum_yoy", "note")},
                    "has_note": bool(r["note"]), **px(r["code"])})

    res = {}
    for name, items in (("att", att), ("fin", fin), ("rev", rev), ("treasury", treasury), ("events", events)):
        merged = _merge(name, items, now)
        key = {"att": lambda x: (-int(x["new"]), -(x.get("score") or 0)),
               "fin": lambda x: (-int(x["new"]), -(x.get("score") or 0)),
               "rev": lambda x: (-int(x["new"]), -(x.get("yoy") or -999)),
               }.get(name, lambda x: (x.get("date", ""), x.get("time", "")))
        merged.sort(key=key, reverse=name in ("treasury", "events"))
        write_json(OUT / f"{name}.json", {"updated": now, "items": merged})
        res[name] = merged
    return res
