"""選股清單：營收年增加速＋挑股價最接近一年高點（research/robust_check.py 回測的最佳組合）

規則（和回測一樣）：
  訊號   單月營收年增 ≥ 30%，且連續 3 個月年增一個比一個高（本月 > 上月 > 上上月）
  進場   營收法定公布期限（次月 10 日）之後的第一個交易日收盤買
  過濾   20 日均成交金額 ≥ 1 億、排除營建（建材營造）與金融（金融保險）、只看普通股（4 碼）
  排序   股價 ÷ 近一年（250 日）最高價，越接近 1 越前面（用進場前一天收盤）
  資金   20 份；每月進場日用「空出來的份數」從名單第一名往下買（已持有的跳過），持有 60 個交易日賣
另外模擬「從一年前開始照規則買」，得到目前應有的持股（回測 2013~2026 年化約 +33%，已扣成本與滑價 0.3%）。

只讀 data/history（約 260 個交易日）、data/archive/revenue、data/state/companies.json；不抓網路、不呼叫 AI。
python -m pipeline.picks      產生 site/data/picks.json（部署時產生，不進 git）
"""
from __future__ import annotations

import csv
import gzip
import logging
import sys
from datetime import date

from . import config, store
from .util import read_json, write_json

log = logging.getLogger(__name__)
OUT = config.OUT_DIR / "picks.json"
SLOTS, HOLD, MIN_LIQ, MIN_YOY = 20, 60, 1e8, 30.0
EXCL_IND = {"建材營造", "金融保險"}
NEAR_N, NEAR_MIN = 250, 120          # 一年高點；資料不足 120 日不排序（排最後）


def _ym_add(y: int, m: int, k: int) -> tuple[int, int]:
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def load_revenue(y: int, m: int) -> dict[str, dict]:
    p = config.DATA_DIR / "archive" / "revenue" / f"{y}" / f"{y}-{m:02d}.csv.gz"
    if not p.exists():
        return {}
    out = {}
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            c = r.get("code", "")
            if len(c) != 4 or not c.isdigit():
                continue
            try:
                out[c] = {"yoy": float(r["yoy"]) if r.get("yoy") not in ("", None) else None,
                          "rev": float(r["rev"]) if r.get("rev") not in ("", None) else None, "name": r.get("name", "")}
            except ValueError:
                continue
    return out


def signals(y: int, m: int, rev: dict) -> dict[str, dict]:
    """(y, m) 月營收符合「年增加速」的公司 → {代號: {yoy, yoy1, yoy2, rev}}"""
    cur, p1, p2 = (rev.get(_ym_add(y, m, -k)) or {} for k in (0, 1, 2))
    out = {}
    for c, r in cur.items():
        a, b, d = r["yoy"], (p1.get(c) or {}).get("yoy"), (p2.get(c) or {}).get("yoy")
        if a is not None and b is not None and d is not None and a >= MIN_YOY and a > b > d:
            out[c] = {"yoy": a, "yoy1": b, "yoy2": d, "rev": r["rev"], "name": r["name"]}
    return out


def price_panel():
    """（交易日列表, {代號: [還原收盤或 None]}, {代號: [成交金額]}, {代號: 名稱/市場}），還原方式同 spark"""
    days = list(store.trading_days())
    closes: dict[str, list] = {}
    refs: dict[str, list] = {}
    vals: dict[str, list] = {}
    meta: dict[str, dict] = {}
    n = len(days)
    for i, d in enumerate(days):
        for c, q in store.load_day(d).items():
            if len(c) != 4 or not c.isdigit():
                continue
            if c not in closes:
                closes[c], refs[c], vals[c] = [None] * n, [None] * n, [None] * n
            cl = q.get("close")
            closes[c][i] = cl if cl else None
            refs[c][i] = q.get("prev_close")
            vals[c][i] = q.get("value")
            meta[c] = {"name": q.get("name"), "market": q.get("market")}
    adj = {}
    for c, cl in closes.items():
        a = [None] * n
        f, last = 1.0, None          # last＝較新的一個有成交日（往回走）
        for i in range(n - 1, -1, -1):
            if cl[i] is None:
                continue
            if last is not None:
                ref, prev = refs[c][last], cl[i]
                if ref and prev and abs(ref / prev - 1) > 0.0005 and 0.1 < ref / prev < 10:
                    f *= ref / prev
            a[i] = cl[i] * f
            last = i
        adj[c] = a
    return days, adj, vals, meta


def near_high(a: list, i: int) -> float | None:
    """第 i 天收盤 ÷ 含當天往前 250 日最高"""
    if i < 0 or a[i] is None:
        return None
    w = [x for x in a[max(0, i - NEAR_N + 1):i + 1] if x is not None]
    return a[i] / max(w) if len(w) >= NEAR_MIN else None


def avg_value(v: list, i: int) -> float | None:
    w = [x for x in v[max(0, i - 19):i + 1] if x]
    return sum(w) / len(w) if len(w) >= 15 else None


def entry_index(days: list[date], y: int, m: int) -> tuple[date, int | None]:
    """(公布期限, 進場日索引)：期限＝次月 10 日，進場＝期限之後第一個交易日；還沒到就 None"""
    ny, nm = _ym_add(y, m, 1)
    dl = date(ny, nm, 10)
    for i, d in enumerate(days):
        if d > dl:
            return dl, i
    return dl, None


def build(today: date | None = None) -> dict:
    comp = (read_json(config.STATE_DIR / "companies.json", {}) or {}).get("data", {})
    days, adj, vals, meta = price_panel()
    if not days:
        return {}
    last = len(days) - 1
    # 最新有營收的月份（檔案存在），往回 14 個月
    t = today or days[-1]
    y, m = _ym_add(t.year, t.month, -1)
    rev, months = {}, []
    for k in range(16):
        yy, mm = _ym_add(y, m, -k)
        r = load_revenue(yy, mm)
        if r:
            rev[(yy, mm)] = r
            if k < 14:
                months.append((yy, mm))
    months = sorted(months)
    latest = months[-1] if months else None
    out_months, holds, trades = [], [], []
    for (yy, mm) in months:
        if (yy, mm) not in rev or _ym_add(yy, mm, -2) not in rev:
            continue
        sig = signals(yy, mm, rev)
        dl, ei = entry_index(days, yy, mm)
        ref_i = (ei - 1) if ei is not None else last           # 排序用進場前一天（還沒進場就用最新一天）
        if ei is not None and ref_i - NEAR_MIN < 0:
            continue
        rows = []
        for c, s in sig.items():
            ind = (comp.get(c) or {}).get("industry", "")
            if ind in EXCL_IND or (not ind and c[:2] in ("25", "28")):
                continue
            if c not in adj:
                continue
            lq = avg_value(vals[c], ref_i)
            if not lq or lq < MIN_LIQ:
                continue
            nh = near_high(adj[c], ref_i)
            rows.append({"code": c, "name": (meta.get(c) or {}).get("name") or s["name"], "market": (meta.get(c) or {}).get("market"),
                         "ind": ind, "yoy": round(s["yoy"], 1), "yoy1": round(s["yoy1"], 1), "yoy2": round(s["yoy2"], 1),
                         "rev": s["rev"], "liq": round(lq), "near": None if nh is None else round(nh, 4)})
        rows.sort(key=lambda r: -(r["near"] if r["near"] is not None else -1))
        for k, r in enumerate(rows):
            r["rank"] = k + 1
            if ei is not None and adj[r["code"]][ei] is not None:
                r["entry_px"] = round(adj[r["code"]][ei], 2)
                cur = next((adj[r["code"]][j] for j in range(last, ei - 1, -1) if adj[r["code"]][j] is not None), None)
                r["ret"] = None if cur is None else round(cur / adj[r["code"]][ei] - 1, 4)
        # 模擬資金 20 份：先把到期的賣掉，再用空出的份數由上往下買
        bought = []
        if ei is not None:
            holds = [h for h in holds if h["exit_i"] > ei]
            held = {h["code"] for h in holds}
            free = SLOTS - len(holds)
            for r in rows:
                if free <= 0:
                    break
                if r["code"] in held or r.get("entry_px") is None:
                    continue
                h = {"code": r["code"], "name": r["name"], "ym": f"{yy}-{mm:02d}", "entry_i": ei, "exit_i": ei + HOLD}
                holds.append(h)
                trades.append(h)
                held.add(r["code"])
                bought.append(r["code"])
                r["bought"] = True
                free -= 1
        prev_n = len(rev.get(_ym_add(yy, mm, -1), {}))
        out_months.append({
            "ym": f"{yy}-{mm:02d}", "deadline": dl.isoformat(),
            "entry": days[ei].isoformat() if ei is not None else None,
            "status": "已進場" if ei is not None else ("公布中" if t <= dl else "待進場"),
            "reported": len(rev[(yy, mm)]), "reported_prev": prev_n,
            "n_signal": len(sig), "bought": bought, "rows": rows,
        })
    # 目前持股（模擬）
    cur = []
    for h in holds:
        if h["exit_i"] <= last:
            continue
        a = adj.get(h["code"]) or []
        p0 = a[h["entry_i"]] if a else None
        p1 = next((a[j] for j in range(last, h["entry_i"] - 1, -1) if a[j] is not None), None)
        cur.append({"code": h["code"], "name": h["name"], "ym": h["ym"], "entry": days[h["entry_i"]].isoformat(),
                    "held_days": last - h["entry_i"], "left_days": h["exit_i"] - last,
                    "ret": None if not p0 or not p1 else round(p1 / p0 - 1, 4)})
    cur.sort(key=lambda r: (r["entry"], r["code"]))
    # 已賣出（模擬，最近一年）
    done = []
    for h in trades:
        if h["exit_i"] > last:
            continue
        a = adj.get(h["code"]) or []
        p0, p1 = a[h["entry_i"]], a[h["exit_i"]] if h["exit_i"] < len(a) else None
        if p1 is None:
            p1 = next((a[j] for j in range(h["exit_i"], h["entry_i"], -1) if a[j] is not None), None)
        done.append({"code": h["code"], "name": h["name"], "ym": h["ym"], "entry": days[h["entry_i"]].isoformat(),
                     "exit": days[h["exit_i"]].isoformat(), "ret": None if not p0 or not p1 else round(p1 / p0 - 1, 4)})
    return {"date": days[-1].isoformat(), "latest_rev": f"{latest[0]}-{latest[1]:02d}" if latest else None,
            "rule": {"slots": SLOTS, "hold": HOLD, "min_liq": MIN_LIQ, "min_yoy": MIN_YOY, "excl": sorted(EXCL_IND)},
            "months": out_months[::-1], "holdings": cur, "free": SLOTS - len(cur), "closed": done[::-1],
            "sim_start": out_months[0]["entry"] if out_months else None}


def run() -> None:
    res = build()
    write_json(OUT, res)
    log.info("選股清單：%s 個月、目前持股 %s 檔", len(res.get("months", [])), len(res.get("holdings", [])))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()
    sys.exit(0)
