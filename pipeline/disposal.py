"""處置預測：累計注意股次數、估算明日觸發價、目前處置中與出關日。

依『公布或通知注意交易資訊暨處置作業要點』的次數條件：
  連續 3 個營業日達第一款、連續 5 個營業日達第一~八款、
  最近 10 個營業日內 6 次、最近 30 個營業日內 12 次。
第一、二款觸發價以本地歷史收盤估算；第三（量放大）、四（週轉率）、六（本益比淨值比）、
七（券資比）款依『異常標準之詳細數據』估算；第五款需全市場券商分點，無法取得。
第一、二、三、四、七款的價格條件同時和「全體平均」與「同類股（同產業別）平均」比較；
同類未達 5 家或本益比為負／≥60 倍（上櫃 65 倍）時依規定不比同類。
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


class Peers:
    """同類股（同市場、同產業別）平均漲跌，用於第一、二、三、四、七款的『與同類股平均差幅』。
    依規定：同類未達 5 家，或該股本益比為負／達 60 倍（上櫃 65 倍）以上，不適用同類股比較。"""

    def __init__(self, companies: dict | None = None, valuation: dict | None = None):
        self.comp = companies or {}
        self.val = valuation
        self.groups: dict[tuple, list[str]] = {}
        for c, v in self.comp.items():
            if v.get("industry") and v.get("market"):
                self.groups.setdefault((v["market"], v["industry"]), []).append(c)
        self._memo: dict[tuple, float | None] = {}

    def info(self, code: str, market: str) -> tuple[str, str | None]:
        """回傳 (產業別, 不適用原因)；原因為 None 表示要和同類比"""
        ind = (self.comp.get(code) or {}).get("industry") or ""
        if not ind:
            return "", "無產業別資料"
        if len(self.groups.get((market, ind), [])) < 5:
            return ind, "同類未達 5 家"
        if self.val:   # 估值資料有抓到才判斷；本益比空白＝虧損（負值）
            v = self.val.get(code)
            if v is not None:
                pe = v.get("pe")
                lim = 65 if market == "TPEX" else 60
                if not pe or pe <= 0:
                    return ind, "本益比為負"
                if pe >= lim:
                    return ind, f"本益比≥{lim}倍"
        return ind, None

    def avg(self, code: str, market: str, d_from: date, d_to: date) -> dict:
        """{'ind', 'avg'(小數或 None), 'n', 'skip'(不適用原因)}"""
        ind, skip = self.info(code, market)
        if skip:
            return {"ind": ind, "avg": None, "n": len(self.groups.get((market, ind), [])), "skip": skip}
        k = (market, ind, d_from, d_to)
        if k not in self._memo:
            a, b = store.load_day(d_from), store.load_day(d_to)
            xs = [b[c]["close"] / a[c]["close"] - 1 for c in self.groups[(market, ind)]
                  if c in a and c in b and a[c].get("close") and b[c].get("close")]
            self._memo[k] = (sum(xs) / len(xs), len(xs)) if len(xs) >= 5 else (None, len(xs))
        v, n = self._memo[k]
        return {"ind": ind, "avg": v, "n": n, "skip": None if v is not None else "同類有行情未達 5 家"}


NO_PEERS = Peers()


def _peer_out(pa: dict) -> dict:
    return {"ind": pa["ind"], "ind_avg": round(pa["avg"] * 100, 2) if pa["avg"] is not None else None,
            "ind_n": pa["n"], "ind_skip": pa["skip"]}


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


def clause1(code: str, market: str, today: date, c0: float, peers: Peers = NO_PEERS) -> dict | None:
    """第一款：最近六個營業日（含明日）累積漲跌幅門檻 → 明日觸發價。
    漲跌幅須超過門檻，且與全體平均、同類股平均的差幅都在 20 個百分點以上"""
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
    pa = peers.avg(code, market, ds[0], today)
    up = max(up, base * (1 + mkt + diff))
    dn = max(base * (1 - small), min(base * (1 - big), base - bp))
    dn = min(dn, base * (1 + mkt - diff))
    if pa["avg"] is not None:
        up = max(up, base * (1 + pa["avg"] + diff))
        dn = min(dn, base * (1 + pa["avg"] - diff))
    up = price_up_to_tick(up + 1e-6)
    dn = price_down_to_tick(dn - 1e-6) if dn > 0 else None
    lu, ld = limit_up(c0), limit_down(c0)
    cum = round((c0 / base - 1) * 100, 2)
    return {
        "base": base, "base_date": ds[0].isoformat(), "cum": cum, "mkt": round(mkt * 100, 2), **_peer_out(pa),
        "up": {"price": up, "pct": round((up / c0 - 1) * 100, 2), "status": _status_up(up, lu, ld)},
        "down": {"price": dn, "pct": round((dn / c0 - 1) * 100, 2) if dn else None, "status": _status_down(dn, lu, ld)},
    }


def clause2(code: str, market: str, today: date, c0: float, peers: Peers = NO_PEERS) -> list[dict]:
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
        pa = peers.avg(code, market, ds[0], today)
        need = max(th, mkt + dth, (pa["avg"] + dth) if pa["avg"] is not None else -1)
        p = price_up_to_tick(base * (1 + need) + 1e-6)
        out.append({"days": n, "th": th * 100, "base": base, "base_date": ds[0].isoformat(),
                    "mkt": round(mkt * 100, 2), "gap": round(dth * 100), **_peer_out(pa),
                    "cum": round((c0 / base - 1) * 100, 2), "price": p, "pct": round((p / c0 - 1) * 100, 2),
                    "status": _status_up(p, lu, ld)})
    return out


# ------------------------------------------------------------ 第三、四、六、七款

def _x(market: str) -> dict:
    return R["TPEX_X" if market == "TPEX" else "TWSE_X"]


def price_cond(code: str, market: str, today: date, c0: float, peers: Peers = NO_PEERS) -> dict | None:
    """第三、四、七款共同的價格條件：6 日累積漲跌超過門檻，且與全體平均、同類股平均差幅都 ≥20 個百分點"""
    ds = store.days_before(today, 6)
    if len(ds) < 6:
        return None
    base = store.load_day(ds[0]).get(code, {}).get("close")
    if not base:
        return None
    th = _x(market)["cum"]
    mkt = store.market_avg_change(ds[0], today) / 100
    pa = peers.avg(code, market, ds[0], today)
    up_raw = max(base * (1 + th), base * (1 + mkt + R["c1_diff"]))
    dn_raw = min(base * (1 - th), base * (1 + mkt - R["c1_diff"]))
    if pa["avg"] is not None:
        up_raw = max(up_raw, base * (1 + pa["avg"] + R["c1_diff"]))
        dn_raw = min(dn_raw, base * (1 + pa["avg"] - R["c1_diff"]))
    up = price_up_to_tick(up_raw + 1e-6)
    dn = price_down_to_tick(dn_raw - 1e-6) if dn_raw > 0 else None
    lu, ld = limit_up(c0), limit_down(c0)
    su, sd = _status_up(up, lu, ld), _status_down(dn, lu, ld)
    if su in ("可能", "跌停仍符合"):
        d = {"dir": "up", "price": up, "pct": round((up / c0 - 1) * 100, 2), "status": su}
    elif sd in ("可能", "漲停仍符合"):
        d = {"dir": "down", "price": dn, "pct": round((dn / c0 - 1) * 100, 2), "status": sd}
    else:
        d = {"dir": "up", "price": up, "pct": round((up / c0 - 1) * 100, 2), "status": "明日不可達"}
    d.update(th=th * 100, cum=round((c0 / base - 1) * 100, 2), base=base, base_date=ds[0].isoformat(),
             mkt=round(mkt * 100, 2), **_peer_out(pa))
    return d


class Market:
    """全市場基準：量放大倍數、平均週轉率、加權平均本益比／淨值比、產業平均淨值比"""

    def __init__(self, today: date, quotes: list[dict], companies: dict, valuation: dict):
        self.comp = companies
        prev = store.days_before(today, 60, include=False)
        self.n60 = len(prev)
        sums: dict[str, float] = {}
        cnts: dict[str, int] = {}
        for d in prev:
            for c, q in store.load_day(d).items():
                if q.get("volume"):
                    sums[c] = sums.get(c, 0) + q["volume"]
                    cnts[c] = cnts.get(c, 0) + 1
        self.avg60 = {c: sums[c] / cnts[c] for c in sums if cnts[c] >= 20}
        self.mult, self.to, self.pe, self.pb, self.ind_pb = {}, {}, {}, {}, {}
        for m in ("TWSE", "TPEX"):
            qs = [q for q in quotes if q["market"] == m and q.get("volume")]
            v = sum(q["volume"] for q in qs if q["code"] in self.avg60)
            a = sum(self.avg60[q["code"]] for q in qs if q["code"] in self.avg60)
            self.mult[m] = round(v / a, 2) if a else 1.0
            sh = [(q["volume"], (companies.get(q["code"]) or {}).get("shares")) for q in qs]
            sv = sum(x for x, s in sh if s)
            ss = sum(s for x, s in sh if s)
            self.to[m] = sv / ss if ss else 0.01
            pes, pbs, ind = [], [], {}
            for q in qs:
                c = q["code"]
                s = (companies.get(c) or {}).get("shares")
                val = valuation.get(c) or {}
                if not s:
                    continue
                if val.get("pe") and val["pe"] > 0:
                    pes.append((val["pe"], s))
                if val.get("pb") and val["pb"] > 0:
                    pbs.append((val["pb"], s))
                    k = (companies.get(c) or {}).get("industry") or ""
                    ind.setdefault(k, []).append((val["pb"], s))
            wavg = lambda xs: sum(a * b for a, b in xs) / sum(b for _, b in xs) if xs else None  # noqa: E731
            self.pe[m], self.pb[m] = wavg(pes), wavg(pbs)
            self.ind_pb[m] = {k: wavg(v) for k, v in ind.items() if len(v) >= 5}

    def summary(self) -> dict:
        r = lambda x, n=2: round(x, n) if x is not None else None  # noqa: E731
        return {m: {"vol_mult": self.mult[m], "turnover": r(self.to[m] * 100), "pe": r(self.pe[m]), "pb": r(self.pb[m])}
                for m in ("TWSE", "TPEX")} | {"days60": self.n60}


def clause3(code: str, market: str, q: dict, M: Market, pc: dict | None) -> dict:
    x = _x(market)
    avg = M.avg60.get(code)
    shares = (M.comp.get(code) or {}).get("shares")
    if not avg or not pc:
        return {"status": "資料不足"}
    mult = max(x["c3_mult"], M.mult[market] + x["c3_mkt"])
    need = max(avg * mult, x["c3_min_lots"] * 1000, (shares or 0) * x["c3_min_to"])
    return {"status": pc["status"], "price": pc, "lots": int(-(-need // 1000)), "avg60": round(avg / 1000),
            "mult": round(mult, 2), "mkt_mult": M.mult[market], "today_mult": round(q["volume"] / avg, 2)}


def clause4(code: str, market: str, q: dict, M: Market, pc: dict | None) -> dict:
    x = _x(market)
    shares = (M.comp.get(code) or {}).get("shares")
    if not shares or not pc:
        return {"status": "資料不足"}
    to = max(x["c4_to"], M.to[market] + x["c4_mkt"])
    return {"status": pc["status"], "price": pc, "lots": int(-(-shares * to // 1000)), "to": round(to * 100, 2),
            "mkt_to": round(M.to[market] * 100, 2), "today_to": round(q["volume"] / shares * 100, 2)}


def clause6(code: str, market: str, q: dict, M: Market, val: dict) -> dict:
    """本益比、淨值比、週轉率（價格條件改看 PE/PB 門檻價）"""
    x = _x(market)
    c0 = q["close"]
    shares = (M.comp.get(code) or {}).get("shares")
    pe, pb = val.get("pe"), val.get("pb")
    if not shares or not pb or not M.pb[market]:
        return {"status": "資料不足"}
    bvps = c0 / pb
    loss = not pe or pe <= 0
    pe_th = None if loss else max(x["c6_pe"], 2 * M.pe[market] if M.pe[market] else 0)
    pb_th = max(x["c6_pb"], 2 * M.pb[market])
    p = bvps * pb_th
    if not loss:
        p = max(p, c0 / pe * pe_th)
    ind = (M.comp.get(code) or {}).get("industry") or ""
    ipb = M.ind_pb[market].get(ind)
    ind_p = bvps * ipb * x["c6_ind"] if ipb else None
    lu, ld = limit_up(c0), limit_down(c0)
    p_all = max(p, ind_p) if ind_p else None
    st_base = _status_up(price_up_to_tick(p + 1e-6), lu, ld)
    st_ind = _status_up(price_up_to_tick(p_all + 1e-6), lu, ld) if p_all else "資料不足"
    lots = int(-(-max(shares * x["c6_to"], x["c6_lots"] * 1000) // 1000))
    pr = price_up_to_tick(p_all + 1e-6) if st_ind in ("可能", "跌停仍符合") else price_up_to_tick(p + 1e-6)
    return {"status": st_ind if st_ind in ("可能", "跌停仍符合") else ("需集中度" if st_base in ("可能", "跌停仍符合") else st_base),
            "price": pr, "pct": round((pr / c0 - 1) * 100, 2), "lots": lots, "pe": pe, "pb": pb, "loss": loss,
            "pe_th": round(pe_th, 1) if pe_th else None, "pb_th": round(pb_th, 2),
            "ind": ind, "ind_pb": round(ipb, 2) if ipb else None, "ind_mult": x["c6_ind"]}


def clause7(code: str, market: str, M: Market, margin: dict, pc: dict | None) -> dict:
    """券資比：用『明日的前一交易日』＝今天的融資融券資料，今天收盤後即可判斷"""
    x = _x(market)
    days = margin.get("days") or []
    today = margin.get("today")
    if not today or not days or days[-1] != today:
        return {"status": "融資券未公布"}
    rows = [(margin["data"].get(d) or {}).get(code) for d in days[-6:]]
    cur = rows[-1]
    if not cur or not cur[0] or not cur[1] or not cur[3] or pc is None:
        return {"status": "資料不足"}
    ratio = lambda r: (r[2] or 0) / r[0] if r and r[0] else None  # noqa: E731
    rs = [ratio(r) for r in rows]
    r0 = rs[-1]
    known = [r for r in rs if r is not None]
    lo = min(known) if known else None
    fin, short = cur[0] / cur[1], (cur[2] or 0) / cur[3]
    prev = rs[-2] if len(rs) >= 2 else None
    fails = []
    if r0 < x["c7_ratio"]:
        fails.append(f"券資比{r0 * 100:.1f}%<{x['c7_ratio'] * 100:.0f}%")
    if fin < x["c7_fin"]:
        fails.append(f"融資使用率{fin * 100:.1f}%<{x['c7_fin'] * 100:.0f}%")
    if short < x["c7_short"]:
        fails.append(f"融券使用率{short * 100:.1f}%<{x['c7_short'] * 100:.0f}%")
    if lo is None or len(known) < 6:
        fails.append("券資比歷史不足6日")
    elif lo > 0 and r0 < lo * x["c7_mult"] or lo == 0 and r0 == 0:
        fails.append(f"未達6日最低{lo * 100:.1f}%的{x['c7_mult']}倍")
    if prev is not None and r0 < prev:
        fails.append("券資比低於前一日")
    ok = not fails
    return {"status": pc["status"] if ok else "不符合", "price": pc, "ratio": round(r0 * 100, 2),
            "min6": round(lo * 100, 2) if lo is not None else None, "fin_use": round(fin * 100, 1),
            "short_use": round(short * 100, 1), "fails": fails}


def build(today: date, quotes: list[dict], notices: list[dict], punish: list[dict], holidays: set[date],
          valuation: dict | None = None, companies: dict | None = None, margin: dict | None = None) -> dict:
    cal = Calendar(holidays)
    T = cal.next(today)
    st = merge_notices(notices)
    pun = merge_punish(punish)
    qm = {q["code"]: q for q in quotes}
    valuation = valuation or {}
    M = Market(today, quotes, companies or {}, valuation)
    peers = Peers(companies, valuation)
    margin = margin or {}

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
        pc = price_cond(code, e["market"], today, c0, peers)
        cands.append({
            "code": code, "name": e["name"] or q["name"], "market": e["market"], "close": c0, "need": need,
            "main": main, "only_c1": main == "c1" and min(needs["any"], needs["w10"], needs["w30"]) > need,
            "progress": {"c1": [k1, R["consec_c1"]], "any": [kany, R["consec_any"]],
                         "w10": [n10, R["within10"]], "w30": [n30, R["within30"]]},
            "earliest": cal.next(T, need).isoformat(), "times": times,
            "c1": clause1(code, e["market"], today, c0, peers), "c2": clause2(code, e["market"], today, c0, peers),
            "record": [{"date": d, "clauses": c} for d, c in rec],
            "limits": {"flat": c0, "up": limit_up(c0), "down": limit_down(c0)},
            "pe": valuation.get(code, {}).get("pe"), "pb": valuation.get(code, {}).get("pb"),
            "turnover_lots": q["volume"] // 1000,
            "c3": clause3(code, e["market"], q, M, pc), "c4": clause4(code, e["market"], q, M, pc),
            "c6": clause6(code, e["market"], q, M, valuation.get(code) or {}),
            "c7": clause7(code, e["market"], M, margin, pc),
        })
    cands.sort(key=lambda x: (x["need"], x["code"]))
    releases: dict[str, list] = {}
    for p in current:
        if p["exit"] <= cal.next(T).isoformat():
            releases.setdefault(p["exit"], []).append(p)
    res = {"date": today.isoformat(), "target": T.isoformat(), "minus1": [c for c in cands if c["need"] == 1],
           "minus2": [c for c in cands if c["need"] == 2], "current": current, "releases": releases,
           "market": M.summary(), "margin_date": margin.get("today")}
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
    return "／".join(parts)


OK = ("可能", "跌停仍符合", "漲停仍符合")


def _pc_txt(pc: dict) -> str:
    if pc["status"] in ("跌停仍符合", "漲停仍符合"):
        return pc["status"]
    return f"收盤{'≥' if pc['dir'] == 'up' else '≤'}{pc['price']}（{pc['pct']:+.1f}%）"


def describe_ext(c: dict) -> list[str]:
    """第三、四、六、七款中明日可能成立的條件，一款一行"""
    out = []
    c3, c4, c6, c7 = c.get("c3") or {}, c.get("c4") or {}, c.get("c6") or {}, c.get("c7") or {}
    if c3.get("status") in OK:
        out.append(f"③ {_pc_txt(c3['price'])}；量≥{c3['lots']:,}張（60日均量{c3['mult']:g}倍）")
    if c4.get("status") in OK:
        out.append(f"④ {_pc_txt(c4['price'])}；量≥{c4['lots']:,}張（週轉率≥{c4['to']:g}%）")
    if c6.get("status") == "跌停仍符合":
        out.append(f"⑥ 本益比、淨值比已達標；量≥{c6['lots']:,}張")
    elif c6.get("status") in OK:
        out.append(f"⑥ 收盤≥{c6['price']}（{c6['pct']:+.1f}%）；量≥{c6['lots']:,}張")
    elif c6.get("status") == "需集中度":
        out.append(f"⑥ 收盤≥{c6['price']}（{c6['pct']:+.1f}%）；量≥{c6['lots']:,}張，且需單一券商或投資人占比過高")
    if c7.get("status") in OK:
        out.append(f"⑦ {_pc_txt(c7['price'])}（券資比{c7['ratio']}%已達標）")
    return out


def line_text(res: dict) -> str:
    T = res["target"][5:].replace("-", "/")
    lines = [f"{config.SITE_NAME}｜明日處置預測", config.SITE_URL + "#/disposal", "",
             f"適用交易日：{T}", "條件為程式估算，非交易所預告",
             f"差1次就處置：{len(res['minus1'])} 檔"]
    for i, c in enumerate(res["minus1"], 1):
        lines.append(f"{i}. {c['name']}({c['code']})｜{COND_NAME[c['main']]}｜第{c['times']}次")
        lines.append(f"   條件：{describe(c)}")
        for t in describe_ext(c):
            lines.append(f"   {t}")
    if res["releases"]:
        lines.append("")
        lines.append("【處置出關】")
        for d, ps in sorted(res["releases"].items()):
            lines.append(f"{d[5:].replace('-', '/')}：" + "、".join(f"{p['name']}({p['code']})" for p in ps))
    lines += ["", "本資訊由程式自動整理，僅供參考，不構成投資建議。"]
    return "\n".join(lines)
