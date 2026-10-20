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
}


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
    return sorted(p.name[:10] for p in (ROOT / kind).glob("*/*.csv.gz"))

# ------------------------------------------------------------------ 每日寫入

def save_quotes(d: date, quotes: list[dict]) -> None:
    write("quotes", d, [{**q, "ref": q.get("prev_close")} for q in quotes])


def save_inst(d: date, inst: dict) -> None:
    write("inst", d, [{"code": c, "foreign": v.get("f"), "trust": v.get("t"), "dealer": v.get("d")} for c, v in inst.items()])


def save_margin(d: date, margin: dict) -> None:
    write("margin", d, [{"code": c, "fin_bal": v[0], "fin_lim": v[1], "short_bal": v[2], "short_lim": v[3]}
                        for c, v in margin.items() if not c.startswith("_")])


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


def backfill(src, years: int = 5, minutes: float = 40, delay: float = 2.5) -> dict:
    """由新到舊補行情、法人、融資融券；每次最多跑 minutes 分鐘，進度存在 progress.json。
    休市日會記下來不再重試；連續失敗太多（可能被交易所暫時封鎖）就提早停止，下次再續。"""
    old_delay = config.HTTP_DELAY
    config.HTTP_DELAY = delay
    t0 = time.time()
    st = _progress()
    today = date.today()
    start = date(today.year - years, today.month, min(today.day, 28))
    st.setdefault("start", start.isoformat())
    start = date.fromisoformat(st["start"])
    closed = set(st.get("closed", []))
    fails = st.get("fails", {})
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
        need = [k for k in ("quotes", "inst", "margin") if not has(k, d)]
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
            if not quotes or not any(q["market"] == "TWSE" for q in quotes):
                ok = False
            elif td != d:
                ok = False
            else:
                save_quotes(d, quotes)
                if not any(q["market"] == "TPEX" for q in quotes):
                    log.warning("%s 只有上市行情", ds)
        if ok and "inst" in need:
            inst = src.fetch_institutional(d)
            if inst:
                save_inst(d, inst)
            else:
                ok = False
        if ok and "margin" in need:
            m = src.fetch_margin(d)
            if m:
                save_margin(d, m)
            else:
                ok = False
        if ok:
            done += 1
            streak = 0
            fails.pop(ds, None)
            if done % 20 == 0:
                log.info("歷史回補：已完成 %d 天，目前到 %s", done, ds)
        else:
            fails[ds] = fails.get(ds, 0) + 1
            streak += 1
            if streak >= 8:
                stopped = "連續失敗，可能被暫時封鎖"
                break
        d -= timedelta(days=1)
    have = days("quotes")
    st.update(closed=sorted(closed), fails=fails, last_run=time.strftime("%Y-%m-%d %H:%M"),
              oldest=have[0] if have else None, n_days=len(have), stopped=stopped or "完成",
              complete=not stopped and d < start)
    _save_progress(st)
    config.HTTP_DELAY = old_delay
    log.info("歷史回補：本次 %d 天（先由現有歷史放入 %d 天），資料庫共 %d 天，最舊 %s，狀態：%s",
             done, seeded, len(have), st["oldest"], st["stopped"])
    return st


def backfill_notices(src, years: int = 5) -> None:
    """上市注意股、處置股可依日期區間查詢：每月一次補齊（只補沒補過的月份）"""
    st = _progress()
    months = set(st.get("notice_months", []))
    t = date.today()
    y, m = t.year - years, t.month
    while (y, m) <= (t.year, t.month):
        key = f"{y}-{m:02d}"
        a = date(y, m, 1)
        b = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        if key not in months and b < t:
            ns = src.fetch_notices(a, b, tpex=False)
            ps = src.fetch_punish(a, b, tpex=False)
            save_notices(ns)
            save_punish(ps)
            if ns or ps:
                months.add(key)
        y, m = (y + (m == 12), m % 12 + 1)
    st = _progress()
    st["notice_months"] = sorted(months)
    _save_progress(st)
    log.info("注意／處置股歷史：已補 %d 個月", len(months))
