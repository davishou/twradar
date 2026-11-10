"""回測用歷史資料回補（由 .github/workflows/backfill_bt.yml 執行，結果推到 btdata 分支的 out/）

python tools/backfill_bt.py tpex_punish        上櫃處置 2004 起（櫃買 bulletin/disposal，每季一查）
python tools/backfill_bt.py twse_full          上市全額交割（變更交易）名單：每週一張快照，名單有變再逐日補，得到打入／恢復日
python tools/backfill_bt.py lend               標借：證交所 borrow/BFIB8U（2005 起）、櫃買 margin/lend（每月一查）
python tools/backfill_bt.py material 起年 迄年   觀測站重大訊息逐日掃描（2005 起），只留公開收購／變更交易／恢復交易等關鍵字；可續跑
python tools/backfill_bt.py taifex 起年 迄年     期交所台指期、台指選擇權每日行情 → fut_TX_YYYY.csv、opt_TXO_YYYY.csv.gz（research/fo_bt.py 用）
python tools/backfill_bt.py yahoo_intraday       加權指數 60 分 K（約 730 天）、5 分 K（60 天）→ twii_60m.csv、twii_5m.csv
python tools/backfill_bt.py treasury 起年 迄年   同上，但只留庫藏股（主旨含「買回」「庫藏」）公告 → treasury_YYYY.csv（research/treasury_bt.py 用）
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from pipeline import sources  # noqa: E402
from pipeline.http import session  # noqa: E402
from pipeline.util import parse_date  # noqa: E402

OUT = pathlib.Path("out")
OUT.mkdir(exist_ok=True)
S = session()
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def getj(url, params=None, tries=3, sleep=2.5):
    for k in range(tries):
        try:
            r = S.get(url, params=params, timeout=60)
            if r.status_code == 200 and r.text.lstrip().startswith(("{", "[")):
                time.sleep(sleep)
                return r.json()
        except Exception as e:  # noqa: BLE001
            log("err", url, params, e)
        time.sleep(sleep * (k + 2))
    return None


def roc(d: date) -> str:
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- 上櫃處置
def tpex_punish():
    rows = []
    d = date(2004, 1, 1)
    today = date.today()
    while d <= today:
        e = min(date(d.year + (d.month + 2) // 12, (d.month + 2) % 12 + 1, 1) - timedelta(days=1), today)
        js = getj("https://www.tpex.org.tw/www/zh-tw/bulletin/disposal",
                  {"startDate": d.strftime("%Y/%m/%d"), "endDate": e.strftime("%Y/%m/%d"), "response": "json"})
        n = 0
        for t in (js or {}).get("tables", []):
            for r in t.get("data", []):
                if len(r) < 9 or not str(r[2]).strip():
                    continue
                code = str(r[2]).strip()
                s0, e0 = sources._period(str(r[5]))
                body = " ".join(str(x) for x in r[4:9])
                m = re.search(r"第([一二三四五六七八九十\d]+)次", body)
                rows.append({"announce": str(parse_date(r[1]) or ""), "code": code, "name": str(r[3]).strip(), "market": "TPEX",
                             "start": str(s0 or ""), "end": str(e0 or ""), "minutes": sources.parse_minutes(body) or "",
                             "times": sources.cn_int(m.group(1)) if m else (2 if "二次" in body else 1),
                             "reason": re.sub(r"\s+", " ", str(r[6]))[:200], "measure": str(r[7])[:60]})
                n += 1
        log("tpex_punish", d, e, n, "ok" if js else "FAIL")
        d = e + timedelta(days=1)
    write_csv(OUT / "tpex_punish.csv", rows, ["announce", "code", "name", "market", "start", "end", "minutes", "times", "reason", "measure"])


# ---------------------------------------------------------------- 上市全額交割名單
def twse_full_snap(d: date):
    js = getj("https://www.twse.com.tw/rwd/zh/fullDelivery/TWT85U", {"date": d.strftime("%Y%m%d"), "response": "json"})
    if not js or js.get("stat") not in ("OK", "ok"):
        return None
    fields = js.get("fields") or (js.get("tables") or [{}])[0].get("fields", [])
    data = js.get("data") or sum([t.get("data", []) for t in js.get("tables", [])], [])
    out = {}
    for r in data:
        rec = dict(zip(fields, r))
        code = str(rec.get("證券代號", r[0] if r else "")).strip()
        if code:
            out[code] = {k: str(v).strip() for k, v in rec.items()}
    return out


def twse_full():
    p = OUT / "twse_full_snaps.json"
    snaps = json.loads(p.read_text()) if p.exists() else {}
    d = date(2004, 1, 7)
    today = date.today()
    t0 = time.time()
    while d <= today:
        if d.isoformat() not in snaps:
            for k in range(5):           # 週三起，遇假日往後一天
                dd = d + timedelta(days=k)
                s = twse_full_snap(dd)
                if s is not None:
                    snaps[dd.isoformat()] = s
                    break
        d += timedelta(days=7)
        if time.time() - t0 > 60 * 150:
            break
    p.write_text(json.dumps(snaps, ensure_ascii=False))
    # 有變化的週，逐日補
    keys = sorted(snaps)
    for a, b in zip(keys, keys[1:]):
        if set(snaps[a]) != set(snaps[b]) or any(snaps[a][c].get("分盤集合競價") != snaps[b][c].get("分盤集合競價") for c in set(snaps[a]) & set(snaps[b])):
            x = date.fromisoformat(a) + timedelta(days=1)
            while x < date.fromisoformat(b):
                if x.isoformat() not in snaps and x.weekday() < 5:
                    s = twse_full_snap(x)
                    if s is not None:
                        snaps[x.isoformat()] = s
                x += timedelta(days=1)
        if time.time() - t0 > 60 * 300:
            break
    p.write_text(json.dumps(snaps, ensure_ascii=False))
    # 整理成打入／恢復事件
    keys = sorted(snaps)
    ev = []
    for a, b in zip(keys, keys[1:]):
        A, B = snaps[a], snaps[b]
        for c in set(B) - set(A):
            ev.append({"date": b, "prev": a, "code": c, "name": B[c].get("證券名稱", ""), "event": "打入", "auction": B[c].get("分盤集合競價", "")})
        for c in set(A) - set(B):
            ev.append({"date": b, "prev": a, "code": c, "name": A[c].get("證券名稱", ""), "event": "恢復", "auction": A[c].get("分盤集合競價", "")})
        for c in set(A) & set(B):
            if A[c].get("分盤集合競價") != B[c].get("分盤集合競價"):
                ev.append({"date": b, "prev": a, "code": c, "name": B[c].get("證券名稱", ""), "event": "分盤變更",
                           "auction": f'{A[c].get("分盤集合競價", "")}→{B[c].get("分盤集合競價", "")}'})
    write_csv(OUT / "twse_full_events.csv", sorted(ev, key=lambda r: r["date"]), ["date", "prev", "code", "name", "event", "auction"])
    log("twse_full snaps", len(snaps), "events", len(ev), "fields", list(next(iter(snaps.values()), {}).get(next(iter(next(iter(snaps.values()), {})), ""), {}).keys()) if snaps else None)


# ---------------------------------------------------------------- 標借
def lend():
    rows = []
    today = date.today()
    d = date(2005, 1, 1)
    while d <= today:
        e = min(date(d.year + d.month // 12, d.month % 12 + 1, 1) - timedelta(days=1), today)
        js = getj("https://www.twse.com.tw/rwd/zh/borrow/BFIB8U",
                  {"startDate": d.strftime("%Y%m%d"), "endDate": e.strftime("%Y%m%d"), "response": "json"})
        n = 0
        if js:
            tabs = js.get("tables") or [js]
            for t in tabs:
                f = t.get("fields") or []
                for r in t.get("data") or []:
                    rec = dict(zip(f, r))
                    rec["market"] = "TWSE"
                    rows.append(rec)
                    n += 1
        log("twse lend", d, n, "ok" if js else "FAIL", (js or {}).get("stat"))
        d = e + timedelta(days=1)
    d = date(2005, 1, 1)
    while d <= today:
        e = min(date(d.year + d.month // 12, d.month % 12 + 1, 1) - timedelta(days=1), today)
        js = getj("https://www.tpex.org.tw/www/zh-tw/margin/lend",
                  {"startDate": d.strftime("%Y/%m/%d"), "endDate": e.strftime("%Y/%m/%d"), "response": "json"})
        n = 0
        for t in (js or {}).get("tables", []):
            f = t.get("fields") or []
            for r in t.get("data") or []:
                rec = dict(zip(f, r))
                rec["market"] = "TPEX"
                rows.append(rec)
                n += 1
        log("tpex lend", d, n, (js or {}).get("date"))
        d = e + timedelta(days=1)
    fields = sorted({k for r in rows for k in r})
    write_csv(OUT / "lend.csv", rows, fields)


# ---------------------------------------------------------------- 重大訊息關鍵字掃描
KW = re.compile(r"公開收購|變更交易方法|全額交割|普通交割|恢復.{0,6}交易方法|分盤集合競價|停止買賣|終止上市|終止櫃檯買賣")


KW_TREASURY = re.compile(r"庫藏|買回")


def material(y0: int = 2005, y1: int = 2026, minutes: float = 300, kw=KW, prefix: str = "material", subject_only: bool = False):
    prog_p = OUT / f"{prefix}_progress_{y0}_{y1}.json"
    prog = json.loads(prog_p.read_text()) if prog_p.exists() else {"next": f"{y0}-01-01", "fail": []}
    d = date.fromisoformat(prog["next"])
    today = min(date.today(), date(y1, 12, 31))
    t0 = time.time()
    buf: dict[int, list] = {}
    while d <= today and time.time() - t0 < minutes * 60:
        if d.weekday() < 5:
            rows = sources.fetch_material_mops(d)
            if rows is None:
                time.sleep(30)
                rows = sources.fetch_material_mops(d)
            if rows is None:
                prog["fail"].append(d.isoformat())
            else:
                for r in rows:
                    if kw.search(r["subject"]) or (not subject_only and kw.search(r["body"][:400])):
                        buf.setdefault(d.year, []).append({**r, "body": r["body"][:3000]})
            time.sleep(3.5)
        d += timedelta(days=1)
        prog["next"] = d.isoformat()
        if len(LOG) % 50 == 0:
            pass
    for y, rs in buf.items():
        p = OUT / f"{prefix}_{y}.csv"
        old = list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []
        keyset = {(o["date"], o["time"], o["code"], o["subject"]) for o in old}
        old += [r for r in rs if (r["date"], r["time"], r["code"], r["subject"]) not in keyset]
        write_csv(p, old, ["date", "time", "code", "name", "market", "subject", "body", "clause"])
    prog_p.write_text(json.dumps(prog, ensure_ascii=False))
    log(prefix, "next", prog["next"], "fail", len(prog["fail"]), {y: len(v) for y, v in buf.items()})

# ---------------------------------------------------------------- 期交所：台指期／台指選擇權每日行情（回測用）
FUT_F = ["date", "contract", "session", "open", "high", "low", "close", "volume", "settle", "oi"]
OPT_F = ["date", "contract", "strike", "cp", "open", "high", "low", "close", "volume", "settle", "oi", "bid", "ask", "expiry"]


def _taifex_month(kind: str, cid: str, y: int, m: int):
    import calendar
    import io
    a, b = f"{y}/{m:02d}/01", f"{y}/{m:02d}/{calendar.monthrange(y, m)[1]:02d}"
    for k in range(4):
        try:
            r = S.post(f"https://www.taifex.com.tw/cht/3/{kind}DataDown",
                       data={"down_type": "1", "commodity_id": cid, "commodity_id2": "", "queryStartDate": a, "queryEndDate": b}, timeout=180)
            txt = r.content.decode("big5", "replace")
            if r.status_code == 200 and txt.lstrip().startswith("交易日期"):
                time.sleep(3)
                return list(csv.reader(io.StringIO(txt)))
        except Exception as e:  # noqa: BLE001
            log("err", kind, y, m, e)
        time.sleep(10 * (k + 1))
    return None


def taifex(y0: int, y1: int):
    """台指期（TX，全部單式月份、一般＋盤後）與台指選擇權（TXO，只留一般交易時段、到期月份 ≤ 次月、有成交或有未平倉的列）
    → fut_TX_YYYY.csv、opt_TXO_YYYY.csv.gz。一年寫一次檔，已存在的年份跳過（今年除外）。"""
    import gzip
    today = date.today()
    for y in range(y0, y1 + 1):
        fp, op = OUT / f"fut_TX_{y}.csv", OUT / f"opt_TXO_{y}.csv.gz"
        if fp.exists() and op.exists() and y < today.year:
            continue
        frows, orows, bad = [], [], []
        for m in range(1, 13):
            if date(y, m, 1) > today:
                break
            rows = _taifex_month("fut", "TX", y, m)
            if rows is None:
                bad.append(f"fut{m}")
            else:
                h = [c.strip() for c in rows[0]]
                ix = {c: i for i, c in enumerate(h)}
                for r in rows[1:]:
                    if len(r) < 12 or "/" in r[ix["到期月份(週別)"]]:
                        continue                                    # 價差委託不要
                    g = lambda c: r[ix[c]].strip()  # noqa: E731
                    frows.append({"date": g("交易日期").replace("/", "-"), "contract": g("到期月份(週別)"), "session": g("交易時段") if "交易時段" in ix else "一般",
                                  "open": g("開盤價"), "high": g("最高價"), "low": g("最低價"), "close": g("收盤價"), "volume": g("成交量"),
                                  "settle": g("結算價"), "oi": g("未沖銷契約數")})
            rows = _taifex_month("opt", "TXO", y, m)
            if rows is None:
                bad.append(f"opt{m}")
            else:
                h = [c.strip() for c in rows[0]]
                ix = {c: i for i, c in enumerate(h)}
                nxt = (y * 12 + m) + 1                              # 次月（年×12＋月−1 的下一個）
                for r in rows[1:]:
                    if len(r) < 14:
                        continue
                    g = lambda c: r[ix[c]].strip() if c in ix and ix[c] < len(r) else ""  # noqa: E731
                    if g("交易時段") not in ("", "一般"):
                        continue
                    con = g("到期月份(週別)")
                    if not con[:6].isdigit() or int(con[:4]) * 12 + int(con[4:6]) > nxt:
                        continue
                    vol, oi = g("成交量"), g("未沖銷契約數")
                    if vol in ("", "0", "-") and oi in ("", "0", "-"):
                        continue
                    orows.append({"date": g("交易日期").replace("/", "-"), "contract": con, "strike": g("履約價").split(".")[0],
                                  "cp": "C" if g("買賣權").startswith("買") or g("買賣權").upper().startswith("C") else "P",
                                  "open": g("開盤價"), "high": g("最高價"), "low": g("最低價"), "close": g("收盤價"), "volume": vol,
                                  "settle": g("結算價"), "oi": oi, "bid": g("最後最佳買價"), "ask": g("最後最佳賣價"), "expiry": g("契約到期日")})
            log("taifex", y, m, "fut", len(frows), "opt", len(orows), "bad", bad)
        if frows:
            write_csv(fp, frows, FUT_F)
        if orows:
            with gzip.open(op, "wt", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=OPT_F)
                w.writeheader()
                w.writerows(orows)
        if bad:
            log("taifex", y, "缺", bad)


def yahoo_intraday():
    """加權指數盤中資料（Yahoo 只給最近：60 分 K 約 730 天、5 分 K 60 天）→ twii_60m.csv、twii_5m.csv（和舊檔合併，之後每次跑會累積）"""
    for interval, rng in (("60m", "730d"), ("5m", "60d")):
        try:
            r = S.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII", params={"interval": interval, "range": rng}, timeout=60,
                      headers={"User-Agent": "Mozilla/5.0"})
            j = r.json()["chart"]["result"][0]
            qd = j["indicators"]["quote"][0]
            rows = [{"ts": t, "open": o, "high": h, "low": l, "close": c} for t, o, h, l, c in
                    zip(j["timestamp"], qd["open"], qd["high"], qd["low"], qd["close"]) if c is not None]
        except Exception as e:  # noqa: BLE001
            log("yahoo", interval, "失敗", e)
            continue
        p = OUT / f"twii_{interval}.csv"
        old = list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []
        have = {int(o["ts"]) for o in old}
        old += [x for x in rows if x["ts"] not in have]
        old.sort(key=lambda x: int(x["ts"]))
        write_csv(p, old, ["ts", "open", "high", "low", "close"])
        log("yahoo", interval, len(rows), "合計", len(old))
        time.sleep(2)


if __name__ == "__main__":
    task = sys.argv[1]
    try:
        if task in ("material", "treasury"):
            a = [int(x) for x in sys.argv[2:4]] if len(sys.argv) > 3 else [2005, 2026]
            if task == "treasury":
                material(a[0], a[1], kw=KW_TREASURY, prefix="treasury", subject_only=True)
            else:
                material(a[0], a[1])
        elif task == "taifex":
            taifex(int(sys.argv[2]), int(sys.argv[3]))
        else:
            {"tpex_punish": tpex_punish, "twse_full": twse_full, "lend": lend, "yahoo_intraday": yahoo_intraday}[task]()
    finally:
        with open(OUT / f"log_{'_'.join(sys.argv[1:])}.txt", "a", encoding="utf-8") as f:
            f.write(f"\n==== {task} {time.strftime('%F %T')}\n" + "\n".join(LOG[-400:]))
