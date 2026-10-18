"""處置預測：累計注意股次數、估算明日觸發價、目前處置中與出關日。

依『公布或通知注意交易資訊暨處置作業要點』的次數條件：
  連續 3 個營業日達第一款、連續 5 個營業日達第一~八款、
  最近 10 個營業日內 6 次、最近 30 個營業日內 12 次。
第一款、第二款觸發價以本地歷史收盤估算；第三~八款需券商分點、融資券等資料，僅顯示條件文字。
本模組為程式估算，非交易所預告。"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import config, store
from .util import limit_down, limit_up, price_down_to_tick, price_up_to_tick, write_json

log = logging.getLogger(__name__)
R = config.DISPOSAL_RULES
COUNT_CLAUSES = set(range(1, 9))  # 第一~八款計入次數


class Calendar:
    def __init__(self, holidays: set[date]):
        self.h = holidays

    def is_open(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.h

    def next(self, d: date, n: int = 1) -> date:
        while n:
            d += timedelta(days=1)
            if self.is_open(d):
                n -= 1
        return d

    def back(self, d: date, n: int) -> list[date]:
        """d（含）往前 n 個交易日，舊→新"""
        out = []
        while len(out) < n:
            if self.is_open(d):
                out.append(d)
            d -= timedelta(days=1)
        return out[::-1]

    def count_between(self, a: date, b: date) -> int:
        n, d = 0, a
        while d <= b:
            n += self.is_open(d)
            d += timedelta(days=1)
        return n


def merge_notices(notices: list[dict]) -> dict:
    st = store.state("notices", {}) or {}
    for n in notices:
        e = st.setdefault(n["code"], {"name": n["name"], "market": n["market"], "dates": {}})
        e["name"] = n["name"] or e["name"]
        e["dates"][n["date"]] = sorted(set(e["dates"].get(n["date"], [])) | set(n["clauses"]))
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    for e in st.values():
        e["dates"] = {k: v for k, v in e["dates"].items() if k >= cutoff}
    st = {k: v for k, v in st.items() if v["dates"]}
    store.save_state("notices", st)
    return st


def merge_punish(punish: list[dict]) -> list[dict]:
    st = store.state("punish", []) or []
    seen = {(p["code"], p["start"]) for p in st}
    for p in punish:
        if (p["code"], p["start"]) not in seen:
            st.append(p)
            seen.add((p["code"], p["start"]))
    cutoff = (date.today() - timedelta(days=120)).isoformat()
    st = [p for p in st if p["end"] >= cutoff]
    store.save_state("punish", st)
    return st


def _status_up(p, lu, ld):
    if p is None:
        return "資料不足"
    if ld >= p:
        return "跌停仍符合"
    return "可能" if p <= lu else "明日不可達"


def _status_down(p, lu, ld):
    if p is None:
        return "資料不足"
    if lu <= p:
        return "漲停仍符合"
    return "可能" if p >= ld else "明日不可達"


def clause1(code: str, market: str, today: date, c0: float) -> dict | None:
    """第一款：最近六個營業日（含明日）累積漲跌幅門檻 → 明日觸發價"""
    ds = store.days_before(today, 6)
    if len(ds) < 6:
        return None
    base = store.load_day(ds[0]).get(code, {}).get("close")
    if not base:
        return None
    r = R[market]
    mkt = store.market_avg_change(ds[0], today) / 100
    small, big, bp, diff = r["c1_small"], r["c1_big"], r["c1_big_price"], R["c1_diff"]
    up = min(base * (1 + small), max(base * (1 + big), base + bp))
    up = max(up, base * (1 + mkt + diff))
    dn = max(base * (1 - small), min(base * (1 - big), base - bp))
    dn = min(dn, base * (1 + mkt - diff))
    up = price_up_to_tick(up + 1e-6)
    dn = price_down_to_tick(dn - 1e-6) if dn > 0 else None
    lu, ld = limit_up(c0), limit_down(c0)
    cum = round((c0 / base - 1) * 100, 2)
    return {
        "base": base, "base_date": ds[0].isoformat(), "cum": cum, "mkt": round(mkt * 100, 2),
        "up": {"price": up, "pct": round((up / c0 - 1) * 100, 2), "status": _status_up(up, lu, ld)},
        "down": {"price": dn, "pct": round((dn / c0 - 1) * 100, 2) if dn else None, "status": _status_down(dn, lu, ld)},
    }


def clause2(code: str, market: str, today: date, c0: float) -> list[dict]:
    out = []
    lu, ld = limit_up(c0), limit_down(c0)
    for n, th, dth in R[market]["c2"]:
        ds = store.days_before(today, n)
        if len(ds) < n:
            out.append({"days": n, "th": th * 100, "status": "歷史不足"})
            continue
        base = store.load_day(ds[0]).get(code, {}).get("close")
        if not base:
            continue
        mkt = store.market_avg_change(ds[0], today) / 100
        p = price_up_to_tick(base * (1 + max(th, mkt + dth)) + 1e-6)
        out.append({"days": n, "th": th * 100, "base": base, "base_date": ds[0].isoformat(),
                    "cum": round((c0 / base - 1) * 100, 2), "price": p, "pct": round((p / c0 - 1) * 100, 2),
                    "status": _status_up(p, lu, ld)})
    return out


def build(today: date, quotes: list[dict], notices: list[dict], punish: list[dict], holidays: set[date],
          valuation: dict | None = None) -> dict:
    cal = Calendar(holidays)
    T = cal.next(today)
    st = merge_notices(notices)
    pun = merge_punish(punish)
    qm = {q["code"]: q for q in quotes}
    valuation = valuation or {}

    # ---- 目前處置中 ----
    current = []
    for p in pun:
        end = date.fromisoformat(p["end"])
        exit_d = cal.next(end)
        if exit_d < T:
            continue
        times = p.get("times") or 1
        remain = cal.count_between(T, end)
        current.append({**p, "exit": exit_d.isoformat(), "remain": remain,
                        "close": qm.get(p["code"], {}).get("close")})
    current.sort(key=lambda x: (x["exit"], x["code"]))
    in_disposal = {p["code"] for p in current if date.fromisoformat(p["end"]) >= T}

    # ---- 預測 ----
    w29 = {d.isoformat() for d in cal.back(today, 29)}
    w9 = {d.isoformat() for d in cal.back(today, 9)}
    back5 = [d.isoformat() for d in cal.back(today, 5)][::-1]
    cands = []
    for code, e in st.items():
        if code in in_disposal or code not in qm:
            continue
        ds = {k: v for k, v in e["dates"].items() if any(c in COUNT_CLAUSES for c in v)}
        k1 = 0
        for d in back5:
            if 1 in e["dates"].get(d, []):
                k1 += 1
            else:
                break
        kany = 0
        for d in back5:
            if d in ds:
                kany += 1
            else:
                break
        n10 = sum(d in w9 for d in ds)
        n30 = sum(d in w29 for d in ds)
        needs = {"c1": R["consec_c1"] - k1, "any": R["consec_any"] - kany,
                 "w10": R["within10"] - n10, "w30": R["within30"] - n30}
        need = min(needs.values())
        if need > 2 or need < 1:
            continue
        main = min(needs, key=lambda k: (needs[k], ["c1", "any", "w10", "w30"].index(k)))
        q = qm[code]
        c0 = q["close"]
        times = 1 + sum(1 for p in pun if p["code"] == code and p["start"] >= cal.back(today, 30)[0].isoformat())
        rec = sorted(e["dates"].items())[-8:]
        cands.append({
            "code": code, "name": e["name"] or q["name"], "market": e["market"], "close": c0, "need": need,
            "main": main, "only_c1": main == "c1" and min(needs["any"], needs["w10"], needs["w30"]) > need,
            "progress": {"c1": [k1, R["consec_c1"]], "any": [kany, R["consec_any"]],
                         "w10": [n10, R["within10"]], "w30": [n30, R["within30"]]},
            "earliest": cal.next(T, need).isoformat(), "times": times,
            "c1": clause1(code, e["market"], today, c0), "c2": clause2(code, e["market"], today, c0),
            "record": [{"date": d, "clauses": c} for d, c in rec],
            "limits": {"flat": c0, "up": limit_up(c0), "down": limit_down(c0)},
            "pe": valuation.get(code, {}).get("pe"), "pb": valuation.get(code, {}).get("pb"),
            "turnover_lots": q["volume"] // 1000,
        })
    cands.sort(key=lambda x: (x["need"], x["code"]))
    releases: dict[str, list] = {}
    for p in current:
        if p["exit"] <= cal.next(T).isoformat():
            releases.setdefault(p["exit"], []).append(p)
    res = {"date": today.isoformat(), "target": T.isoformat(), "minus1": [c for c in cands if c["need"] == 1],
           "minus2": [c for c in cands if c["need"] == 2], "current": current, "releases": releases}
    res["line_text"] = line_text(res)
    write_json(config.OUT_DIR / "disposal.json", res)
    return res


COND_NAME = {"c1": "連續3日第1款", "any": "連續5日（第1~8款）", "w10": "10日內6次", "w30": "30日內12次"}


def describe(c: dict) -> str:
    """一行條件摘要（給表格與 LINE 文字共用）"""
    parts = []
    c1 = c.get("c1")
    if c1:
        u, d = c1["up"], c1["down"]
        if u["status"] in ("可能", "跌停仍符合"):
            parts.append(f"①{'跌停仍符合' if u['status'] == '跌停仍符合' else ''}"
                         f"{'' if u['status'] == '跌停仍符合' else str(u['price']) + '↑(' + format(u['pct'], '+.1f') + '%)'}")
        elif d["status"] in ("可能", "漲停仍符合"):
            parts.append(f"①{'漲停仍符合' if d['status'] == '漲停仍符合' else str(d['price']) + '↓(' + format(d['pct'], '+.1f') + '%)'}")
        else:
            parts.append("① 明日不符合")
    else:
        parts.append("① 歷史資料不足")
    c2 = [x for x in c.get("c2", []) if x.get("status") in ("可能", "跌停仍符合")]
    if c2:
        x = min(c2, key=lambda y: y["price"])
        if x["status"] == "跌停仍符合":
            parts.append(f"②跌停仍符合（{x['days']}日門檻）")
        else:
            parts.append(f"②{x['price']}↑({x['pct']:+.1f}%，{x['days']}日門檻)")
    if not c["only_c1"]:
        parts.append("③~⑧ 需量能、券商、融資券條件")
    return "／".join(parts)


def line_text(res: dict) -> str:
    T = res["target"][5:].replace("-", "/")
    lines = [f"{config.SITE_NAME}｜明日處置預測", config.SITE_URL + "#/disposal", "",
             f"適用交易日：{T}", "條件為程式估算，非交易所預告",
             f"差1次就處置：{len(res['minus1'])} 檔"]
    for i, c in enumerate(res["minus1"], 1):
        lines.append(f"{i}. {c['name']}({c['code']})｜{COND_NAME[c['main']]}｜第{c['times']}次")
        lines.append(f"   條件：{describe(c)}")
    if res["releases"]:
        lines.append("")
        lines.append("【處置出關】")
        for d, ps in sorted(res["releases"].items()):
            lines.append(f"{d[5:].replace('-', '/')}：" + "、".join(f"{p['name']}({p['code']})" for p in ps))
    lines += ["", "本資訊由程式自動整理，僅供參考，不構成投資建議。"]
    return "\n".join(lines)
