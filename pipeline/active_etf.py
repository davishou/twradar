"""主動式 ETF 持股異動。

取得持股的三種方式（依序嘗試）：
1. ADAPTERS 註冊的自動抓取函式（各投信網頁格式不同，請依需要自行加入，範本見下方）
2. data/etf_inbox/{代號}_{YYYYMMDD}.csv 手動匯入（欄位：代號,名稱,股數,權重；可直接用投信下載的檔）
3. 模擬資料源（--mock）

每次把快照存到 data/etf/{代號}/{日期}.json，和上一份比較算出加減碼。"""
from __future__ import annotations

import csv
import io
import logging
import re
from collections import defaultdict
from datetime import date
from typing import Callable

from . import config, store
from .util import num, parse_date, read_json, write_json

log = logging.getLogger(__name__)
SNAP = config.DATA_DIR / "etf"

# 例：ADAPTERS["00981A"] = my_fetch_00981A
# def my_fetch_00981A() -> tuple[date, list[dict]]:
#     js = http.get_json("https://投信網址/api/holdings?fund=00981A")
#     return parse_date(js["date"]), [{"code": r["stockNo"], "name": r["stockName"],
#                                       "shares": num(r["shares"]), "weight": num(r["weight"])} for r in js["rows"]]
ADAPTERS: dict[str, Callable[[], tuple[date, list[dict]]]] = {}


def _read_csv(path) -> list[dict]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp950", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {str(k).strip(): v for k, v in r.items() if k}
        code = next((str(r[k]).strip() for k in r if re.search(r"代號|代碼|code", k, re.I)), "")
        code = re.sub(r"\D", "", code)[:4]
        if len(code) != 4:
            continue
        out.append({"code": code, "name": next((r[k].strip() for k in r if re.search(r"名稱|name", k, re.I)), ""),
                    "shares": num(next((r[k] for k in r if re.search(r"股數|shares", k, re.I)), 0), 0),
                    "weight": num(next((r[k] for k in r if re.search(r"權重|比例|weight", k, re.I)), None))})
    return out


def _inbox(etf: str) -> tuple[date, list[dict]] | None:
    if not config.ETF_INBOX.exists():
        return None
    files = sorted(config.ETF_INBOX.glob(f"{etf}_*.csv"))
    if not files:
        return None
    f = files[-1]
    d = parse_date(f.stem.split("_")[-1])
    return (d, _read_csv(f)) if d else None


def collect(d: date, src=None) -> None:
    """抓各基金持股並存快照"""
    for etf in config.ACTIVE_ETFS:
        got = None
        if src is not None and hasattr(src, "etf_holdings"):
            got = (d, src.etf_holdings(etf, d))
        elif etf in ADAPTERS:
            try:
                got = ADAPTERS[etf]()
            except Exception as e:  # noqa: BLE001
                log.warning("ETF %s 抓取失敗：%s", etf, e)
        if not got:
            got = _inbox(etf)
        if got and got[1]:
            write_json(SNAP / etf / f"{got[0].isoformat()}.json", got[1])


def _snaps(etf: str) -> list[date]:
    p = SNAP / etf
    return sorted(x for x in (parse_date(f.stem) for f in p.glob("*.json")) if x) if p.exists() else []


def _price(code: str, d: date) -> float | None:
    q = store.load_day(d).get(code)
    if not q:
        ds = store.days_before(d, 1)
        q = store.load_day(ds[0]).get(code) if ds else None
    return (q or {}).get("avg") or (q or {}).get("close")


def build(companies: dict, quotes: list[dict]) -> dict:
    qm = {q["code"]: q for q in quotes}
    funds, holdings = [], []
    agg = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "net_lots": 0.0, "funds": [], "name": ""})
    latest_dates = []
    for etf, name in config.ACTIVE_ETFS.items():
        ds = _snaps(etf)
        if not ds:
            continue
        cur_d = ds[-1]
        prev_d = ds[-2] if len(ds) > 1 else None
        cur = {r["code"]: r for r in read_json(SNAP / etf / f"{cur_d.isoformat()}.json", [])}
        prev = {r["code"]: r for r in read_json(SNAP / etf / f"{prev_d.isoformat()}.json", [])} if prev_d else {}
        fname = name or qm.get(etf, {}).get("name") or etf
        latest_dates.append(cur_d)
        fb = fs = 0.0
        for code in set(cur) | set(prev):
            c, p = cur.get(code), prev.get(code)
            sh = (c or {}).get("shares") or 0
            dsh = sh - ((p or {}).get("shares") or 0) if prev_d else 0
            px = _price(code, cur_d)
            amt = dsh * px if px else 0
            shares_out = companies.get(code, {}).get("shares") or 0
            nm = (c or p or {}).get("name") or companies.get(code, {}).get("name", code)
            q = qm.get(code, {})
            row = {"fund": etf, "fund_name": fname, "code": code, "name": nm, "weight": (c or {}).get("weight"),
                   "lots": round(sh / 1000, 1), "mv": round(sh * px) if px else None,
                   "delta_lots": round(dsh / 1000, 1), "delta_amt": round(amt), "status": "新增" if c and not p and prev_d else ("出清" if p and not c else ""),
                   "cap_ratio": round(dsh / shares_out * 100, 4) if shares_out else None,
                   "chg": round((q["close"] / q["prev_close"] - 1) * 100, 2) if q.get("prev_close") else None}
            holdings.append(row)
            a = agg[code]
            a["name"] = nm
            if c:
                a["funds"].append(etf)
            if amt > 0:
                a["buy"] += amt
                fb += amt
            elif amt < 0:
                a["sell"] += -amt
                fs += -amt
            a["net_lots"] += dsh / 1000
        funds.append({"code": etf, "name": fname, "date": cur_d.isoformat(), "prev": prev_d.isoformat() if prev_d else None,
                      "n": len(cur), "buy": round(fb), "sell": round(fs), "net": round(fb - fs)})
    stocks = []
    for code, a in agg.items():
        q = qm.get(code, {})
        stocks.append({"code": code, "name": a["name"], "n_funds": len(a["funds"]), "funds": a["funds"],
                       "buy": round(a["buy"]), "sell": round(a["sell"]), "net": round(a["buy"] - a["sell"]),
                       "net_lots": round(a["net_lots"], 1), "close": q.get("close"),
                       "chg": round((q["close"] / q["prev_close"] - 1) * 100, 2) if q.get("prev_close") else None})
    stocks.sort(key=lambda x: -abs(x["net"]))
    holdings.sort(key=lambda x: (x["fund"], -(x["weight"] or 0)))
    res = {"date": max(latest_dates).isoformat() if latest_dates else None,
           "range": [min(latest_dates).isoformat(), max(latest_dates).isoformat()] if latest_dates else None,
           "totals": {"buy": sum(f["buy"] for f in funds), "sell": sum(f["sell"] for f in funds),
                      "net": sum(f["net"] for f in funds)},
           "funds": funds, "stocks": stocks, "holdings": holdings}
    write_json(config.OUT_DIR / "etf.json", res)
    return res
