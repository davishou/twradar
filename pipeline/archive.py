"""長期資料庫（回測用）：每類資料一個資料夾、每天一個 gzip CSV，欄位固定、永久保存。

data/archive/
  quotes/2026/2026-10-20.csv.gz    每日行情（上市＋上櫃普通股）
  inst/…                           三大法人買賣超（張）
  margin/…                         融資融券餘額與限額（張）
  limitup/…                        當日漲停股與族群分類
  notices/…                        注意股公告（依公告日）
  punish/…                         處置股（依公布日）
  adjust.csv.gz                    除權息／減資還原因子（由行情自動推算）
  progress.json                    歷史回補進度

gzip 用固定時間戳寫入，內容相同時檔案也相同，不會在 git 產生多餘變更。
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

from . import config

log = logging.getLogger(__name__)
ROOT = config.DATA_DIR / "archive"

COLS = {
    "quotes": ["code", "name", "market", "open", "high", "low", "close", "change", "ref", "volume", "value", "trades"],
    "inst": ["code", "foreign", "trust", "dealer"],
    "margin": ["code", "fin_bal", "fin_lim", "short_bal", "short_lim"],
    "limitup": ["code", "name", "market", "industry", "theme", "theme_source", "streak", "close", "chg", "lots",
                "vol_ratio", "turnover", "locked", "one_price", "reason"],
    "notices": ["date", "code", "name", "market", "clauses", "text"],
    "punish": ["announce", "code", "name", "market", "start", "end", "minutes", "times", "reason"],
    "val": ["code", "pe", "pb", "dy"],                                     # 每日本益比、股價淨值比、殖利率
    "revenue": ["code", "name", "market", "rev", "rev_prev", "rev_ly", "mom", "yoy", "cum", "cum_ly", "cum_yoy", "note"],  # 每月（千元）
    "fin": ["code", "market", "rev", "gross", "op", "nonop", "pretax", "eps"],  # 每季累計數（千元、元）
    "cbq": ["code", "name", "close", "chg", "open", "high", "low", "trades", "lots", "value", "avg", "ref_next",
            "nego_lots", "nego_close"],                                     # 可轉債每日行情（2007 起）
    "cbb": ["code", "name", "conv_start", "conv_end", "conv_price", "conv_next_date", "stop_conv_start", "stop_conv_end",
            "put_start", "put_end", "put_price", "call_start", "call_end", "call_price", "delist", "issue_amt", "out_amt",
            "ref_price", "stock_price", "halt_start", "halt_end", "coupon"],  # 可轉債資訊看板（2017 起）
}
INST_START = date(2012, 5, 2)    # 證交所三大法人日報最早日期；櫃買更早的也查無資料


def path(kind: str, d: date | str) -> Path:
    s = d if isinstance(d, str) else d.isoformat()
    return ROOT / kind / s[:4] / f"{s}.csv.gz"


def has(kind: str, d: date | str) -> bool:
    return path(kind, d).exists()


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    if isinstance(v, (list, tuple)):
        return ";".join(map(str, v))
    return str(v)


def write(kind: str, d: date | str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = COLS[kind]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in sorted(rows, key=lambda x: tuple(str(x.get(c, "")) for c in cols[:2])):
        w.writerow([_fmt(r.get(c)) for c in cols])
    p = path(kind, d)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(buf.getvalue().encode("utf-8"), compresslevel=9, mtime=0)
    if p.exists() and p.read_bytes() == data:
        return
    p.write_bytes(data)


def read(kind: str, d: date | str) -> list[dict]:
    p = path(kind, d)
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def days(kind: str) -> list[str]:
    return sorted(p.name[:-len(".csv.gz")] for p in (ROOT / kind).glob("*/*.csv.gz"))

# ------------------------------------------------------------------ 每日寫入

def save_quotes(d: date, quotes: list[dict]) -> None:
    write("quotes", d, [{**q, "ref": q.get("prev_close")} for q in quotes])


def save_inst(d: date, inst: dict) -> None:
    write("inst", d, [{"code": c, "foreign": v.get("f"), "trust": v.get("t"), "dealer": v.get("d")} for c, v in inst.items()])


def save_margin(d: date, margin: dict) -> None:
    write("margin", d, [{"code": c, "fin_bal": v[0], "fin_lim": v[1], "short_bal": v[2], "short_lim": v[3]}
                        for c, v in margin.items() if not c.startswith("_")])


def save_val(d: date, val: dict) -> None:
    write("val", d, [{"code": c, **v} for c, v in val.items()])


def save_limitup(d: date, daily: dict) -> None:
    write("limitup", d, [{k: s.get(k) for k in COLS["limitup"]} for s in (daily or {}).get("stocks", [])])


def sync_limitup() -> int:
    """網站的每日漲停檔（族群可能被重新分類過）同步到資料庫"""
    n = 0
    for p in sorted((config.OUT_DIR / "daily").glob("????-??-??.json")):
        save_limitup(date.fromisoformat(p.stem), json.loads(p.read_text("utf-8")))
        n += 1
    return n


def save_notices(notices: list[dict]) -> None:
    by: dict[str, list] = {}
    for n in notices:
        by.setdefault(n["date"], []).append(n)
    for d, ns in by.items():
        old = {(r["code"], r["market"]): r for r in read("notices", d)}
        for n in ns:
            old[(n["code"], n["market"])] = n
        write("notices", d, list(old.values()))


def save_punish(punish: list[dict]) -> None:
    by: dict[str, list] = {}
    for p in punish:
        k = p.get("announce") or p.get("start")
        if k:
            by.setdefault(k, []).append(p)
    for d, ps in by.items():
        old = {(r["code"], r["start"]): r for r in read("punish", d)}
        for p in ps:
            old[(p["code"], p["start"])] = p
        write("punish", d, list(old.values()))

# ------------------------------------------------------------------ 基本面（月營收、季報）

FUND_START = (2013, 1)    # 觀測站 IFRS 月營收、綜合損益表彙總從 102 年起


def _q_deadline(y: int, q: int) -> date:
    """季報法定公布期限（Q1 5/15、Q2 8/14、Q3 11/14、Q4 隔年 3/31）"""
    return {1: date(y, 5, 15), 2: date(y, 8, 14), 3: date(y, 11, 14), 4: date(y + 1, 3, 31)}[q]


def backfill_fundamentals(src, minutes: float = 20, delay: float = 4.0) -> dict:
    """回補月營收（每月一檔）與季報累計數（每季一檔），2013 起。
    已過公布期限 7 天後抓到的才算完成；期限內的會每次重抓（陸續有公司公布）。觀測站拒絕就停，下次續。"""
    from . import findb
    t0 = time.time()
    st = _progress()
    fd = st.setdefault("fund", {"revenue": {}, "fin": {}})
    today = date.today()
    stopped, n_rev, n_fin = "", 0, 0
    # 月營收：由新到舊
    y, m = today.year, today.month - 1 or 12
    if today.month == 1:
        y -= 1
    while (y, m) >= FUND_START:
        if time.time() - t0 > minutes * 60:
            stopped = "時間到"
            break
        key = f"{y}-{m:02d}"
        final = fd["revenue"].get(key, "") >= (date(y + (m == 12), m % 12 + 1, 1) + timedelta(days=20)).isoformat()
        if not (final and has("revenue", key)):
            rows = src.fetch_revenue_month(y, m)
            if rows is None:
                stopped = "月營收被拒或失敗"
                break
            write("revenue", key, rows)
            fd["revenue"][key] = today.isoformat()
            n_rev += 1
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    # 季報：由新到舊
    if not stopped:
        y, q = today.year, (today.month - 1) // 3
        if q == 0:
            y, q = y - 1, 4
        while (y, q) >= (FUND_START[0], 1):
            if time.time() - t0 > minutes * 60:
                stopped = "時間到"
                break
            key = f"{y}Q{q}"
            final = fd["fin"].get(key, "") >= (_q_deadline(y, q) + timedelta(days=7)).isoformat()
            if not (final and has("fin", key)):
                rows = []
                for typek, market in (("sii", "TWSE"), ("otc", "TPEX")):
                    got = findb.fetch_quarter(typek, y - 1911, q)
                    time.sleep(delay)
                    if got is None:
                        stopped = "季報被拒或失敗"
                        break
                    rows += [{"code": c, "market": market, **v} for c, v in got.items()]
                if stopped:
                    break
                if rows:
                    write("fin", key, rows)
                    fd["fin"][key] = today.isoformat()
                    n_fin += 1
            y, q = (y, q - 1) if q > 1 else (y - 1, 4)
    st = _progress()
    st["fund"] = fd
    st["fund_run"] = {"at": time.strftime("%Y-%m-%d %H:%M"), "revenue": n_rev, "fin": n_fin, "stopped": stopped or "完成",
                      "revenue_months": len(days("revenue")), "fin_quarters": len(days("fin"))}
    _save_progress(st)
    log.info("基本面回補：月營收 %d 個月、季報 %d 季，狀態：%s", n_rev, n_fin, stopped or "完成")
    return st["fund_run"]


# ------------------------------------------------------------------ 還原因子

def build_adjust() -> int:
    """除權息、減資等『非交易』價格變動：當日參考價 ≠ 前一交易日收盤 → 還原因子 = 參考價 / 前收。
    回測時把該日之前的價格乘上因子（多次相乘）即得還原價。"""
    prev: dict[str, float] = {}
    rows = []
    for d in days("quotes"):
        cur = {}
        for r in read("quotes", d):
            try:
                c, ref = float(r["close"]), float(r["ref"]) if r["ref"] else None
            except ValueError:
                continue
            p = prev.get(r["code"])
            if p and ref and abs(ref / p - 1) > 0.0005:
                rows.append({"date": d, "code": r["code"], "name": r["name"], "prev_close": p, "ref": ref,
                             "factor": round(ref / p, 6)})
            cur[r["code"]] = c
        prev = cur  # 只和『前一個交易日』比；前一天沒成交的股票不判斷，避免誤判
    buf = io.StringIO()
    w = csv.DictWriter(buf, ["date", "code", "name", "prev_close", "ref", "factor"], lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    data = gzip.compress(buf.getvalue().encode("utf-8"), compresslevel=9, mtime=0)
    p = ROOT / "adjust.csv.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists() or p.read_bytes() != data:
        p.write_bytes(data)
    return len(rows)

# ------------------------------------------------------------------ 歷史回補

def _progress() -> dict:
    p = ROOT / "progress.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def _save_progress(st: dict) -> None:
    p = ROOT / "progress.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")


def seed_from_history() -> int:
    """把目前 data/history 的行情先放進資料庫（不用重抓）"""
    from . import store
    n = 0
    for d in store.trading_days():
        if not has("quotes", d):
            save_quotes(d, list(store.load_day(d).values()))
            n += 1
    return n


EARLIEST = date(2004, 2, 11)   # 證交所依日期查詢行情最早可查的日子
FIRST_YEARS = 10               # 第一階段先補到 10 年；補完後自動往回補到 EARLIEST


def target_start(st: dict, today: date | None = None) -> date:
    """回補目標起點：先 10 年；10 年補完（stage1_done）後改為最早可查的日子"""
    today = today or date.today()
    ten = date(today.year - FIRST_YEARS, today.month, min(today.day, 28))
    return EARLIEST if st.get("stage1_done") else ten


def backfill(src, years: int | None = None, minutes: float = 40, delay: float = 2.5) -> dict:
    """由新到舊補行情、法人、融資融券；每次最多跑 minutes 分鐘，進度存在 progress.json。
    目標：先補到 10 年，補完自動延伸到最早（2004-02）。years 有給就用固定年數（測試用）。
    休市日會記下來不再重試；行情是必要的，法人／融資券在較舊的年份可能查無資料，各試 2 次後就放棄該日該類，
    不影響行情回補。連續失敗太多（可能被交易所暫時封鎖）就提早停止，下次再續。"""
    old_delay = config.HTTP_DELAY
    config.HTTP_DELAY = delay
    t0 = time.time()
    st = _progress()
    today = date.today()
    start = date(today.year - years, today.month, min(today.day, 28)) if years else target_start(st, today)
    st["start"] = start.isoformat()
    closed = set(st.get("closed", []))
    fails = st.get("fails", {})
    miss = st.setdefault("miss", {})                                   # 次要資料查無的次數
    for k in ("inst", "margin", "val"):
        miss.setdefault(k, {})
    gave_up = {k: set(v) for k, v in st.get("gave_up", {}).items()}   # 已放棄的日子（多半是那時還沒有這種資料）
    no_tpex = set(st.get("no_tpex", []))
    seeded = seed_from_history()
    d = today - timedelta(days=1)
    done = streak = 0
    stopped = ""
    while d >= start:
        if time.time() - t0 > minutes * 60:
            stopped = "時間到"
            break
        ds = d.isoformat()
        if d.weekday() >= 5 or ds in closed or fails.get(ds, 0) >= 3:
            d -= timedelta(days=1)
            continue
        need = [k for k in ("quotes", "inst", "margin", "val") if not has(k, d) and ds not in gave_up.get(k, set())
                and not (k == "inst" and d < INST_START)]
        if not need:
            d -= timedelta(days=1)
            continue
        ok = True
        if "quotes" in need:
            td, quotes = src.fetch_quotes(d)
            stat = getattr(src, "LAST_TWSE_STAT", "OK")
            if stat is not None and stat != "OK":
                closed.add(ds)        # 休市：證交所回應『沒有符合條件的資料』
                d -= timedelta(days=1)
                continue
            if not quotes or not any(q["market"] == "TWSE" for q in quotes) or td != d:
                ok = False
            else:
                save_quotes(d, quotes)
                if not any(q["market"] == "TPEX" for q in quotes):
                    no_tpex.add(ds)
                    log.warning("%s 只有上市行情", ds)
        for kind, fetch, save in (("inst", src.fetch_institutional, save_inst), ("margin", src.fetch_margin, save_margin),
                                  ("val", getattr(src, "fetch_valuation_by_date", lambda d: None), save_val)):
            if not ok or kind not in need:
                continue
            got = fetch(d)
            if got:
                save(d, got)
                miss[kind].pop(ds, None)
            else:
                miss[kind][ds] = miss[kind].get(ds, 0) + 1
                if miss[kind][ds] >= 2:
                    gave_up.setdefault(kind, set()).add(ds)
                    miss[kind].pop(ds, None)
        if ok:
            done += 1
            streak = 0
            fails.pop(ds, None)
            if done % 20 == 0:
                log.info("歷史回補：已完成 %d 天，目前到 %s", done, ds)
                _save_progress({**st, "closed": sorted(closed), "fails": fails, "no_tpex": sorted(no_tpex),
                                "gave_up": {k: sorted(v) for k, v in gave_up.items()}})
        else:
            fails[ds] = fails.get(ds, 0) + 1
            streak += 1
            if streak >= 8:
                stopped = "連續失敗，可能被暫時封鎖"
                break
        d -= timedelta(days=1)
    have = days("quotes")
    complete = not stopped and d < start
    st.update(closed=sorted(closed), fails=fails, no_tpex=sorted(no_tpex),
              gave_up={k: sorted(v) for k, v in gave_up.items()}, last_run=time.strftime("%Y-%m-%d %H:%M"),
              oldest=have[0] if have else None, n_days=len(have), stopped=stopped or "完成", complete=complete,
              by_year=_year_summary(no_tpex, gave_up))
    if complete and not years and not st.get("stage1_done"):
        st["stage1_done"] = time.strftime("%Y-%m-%d")   # 10 年補完，下次起往回補到最早
        st["complete"] = False
    _save_progress(st)
    config.HTTP_DELAY = old_delay
    log.info("歷史回補：本次 %d 天（先由現有歷史放入 %d 天），資料庫共 %d 天，最舊 %s，狀態：%s",
             done, seeded, len(have), st["oldest"], st["stopped"])
    return st


def _year_summary(no_tpex: set, gave_up: dict) -> dict:
    """每年各類資料的天數（給人看回補到哪、哪些資料舊年份沒有）"""
    out: dict[str, dict] = {}
    for kind in ("quotes", "inst", "margin", "val", "notices", "punish"):
        for ds in days(kind):
            out.setdefault(ds[:4], {}).setdefault(kind, 0)
            out[ds[:4]][kind] += 1
    for ds in no_tpex:
        out.setdefault(ds[:4], {}).setdefault("no_tpex", 0)
        out[ds[:4]]["no_tpex"] += 1
    for kind, v in gave_up.items():
        for ds in v:
            out.setdefault(ds[:4], {}).setdefault(f"no_{kind}", 0)
            out[ds[:4]][f"no_{kind}"] += 1
    return dict(sorted(out.items()))


def backfill_notices(src, years: int | None = None, max_months: int = 24) -> None:
    """上市注意股、處置股可依日期區間查詢：每月一次補齊（只補沒補過的月份），目標起點同行情回補。
    查無資料的月份記 2 次後放棄（太早期可能沒有資料）。每次最多補 max_months 個月。"""
    st = _progress()
    months = set(st.get("notice_months", []))
    empty = st.get("notice_empty", {})
    t = date.today()
    s0 = date(t.year - years, t.month, 1) if years else target_start(st, t)
    y, m = s0.year, s0.month
    n = 0
    while (y, m) <= (t.year, t.month):
        key = f"{y}-{m:02d}"
        a = date(y, m, 1)
        b = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        if key not in months and b < t and empty.get(key, 0) < 2 and n < max_months:
            n += 1
            ns = src.fetch_notices(a, b, tpex=False)
            ps = src.fetch_punish(a, b, tpex=False)
            save_notices(ns)
            save_punish(ps)
            if ns or ps:
                months.add(key)
                empty.pop(key, None)
            else:
                empty[key] = empty.get(key, 0) + 1
        y, m = (y + (m == 12), m % 12 + 1)
    st = _progress()
    st["notice_months"] = sorted(months)
    st["notice_empty"] = empty
    _save_progress(st)
    log.info("注意／處置股歷史：已補 %d 個月", len(months))
