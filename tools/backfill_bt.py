"""回測用歷史資料回補（由 .github/workflows/backfill_bt.yml 執行，結果推到 btdata 分支的 out/）

python tools/backfill_bt.py tpex_punish        上櫃處置 2004 起（櫃買 bulletin/disposal，每季一查）
python tools/backfill_bt.py twse_full          上市全額交割（變更交易）名單：每週一張快照，名單有變再逐日補，得到打入／恢復日
python tools/backfill_bt.py lend               標借：證交所 borrow/BFIB8U（2005 起）、櫃買 margin/lend（每月一查）
python tools/backfill_bt.py material 起年 迄年   觀測站重大訊息逐日掃描（2005 起），只留公開收購／變更交易／恢復交易等關鍵字；可續跑
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


def material(y0: int = 2005, y1: int = 2026, minutes: float = 330):
    prog_p = OUT / f"material_progress_{y0}_{y1}.json"
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
                    if KW.search(r["subject"]) or KW.search(r["body"][:400]):
                        buf.setdefault(d.year, []).append({**r, "body": r["body"][:3000]})
            time.sleep(3.5)
        d += timedelta(days=1)
        prog["next"] = d.isoformat()
        if len(LOG) % 50 == 0:
            pass
    for y, rs in buf.items():
        p = OUT / "material" / f"{y}.csv"
        old = list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []
        keyset = {(o["date"], o["time"], o["code"], o["subject"]) for o in old}
        old += [r for r in rs if (r["date"], r["time"], r["code"], r["subject"]) not in keyset]
        write_csv(p, old, ["date", "time", "code", "name", "market", "subject", "body", "clause"])
    prog_p.write_text(json.dumps(prog, ensure_ascii=False))
    log("material next", prog["next"], "fail", len(prog["fail"]), {y: len(v) for y, v in buf.items()})


if __name__ == "__main__":
    task = sys.argv[1]
    try:
        if task == "material":
            a = [int(x) for x in sys.argv[2:4]] if len(sys.argv) > 3 else [2005, 2026]
            material(a[0], a[1])
        else:
            {"tpex_punish": tpex_punish, "twse_full": twse_full, "lend": lend}[task]()
    finally:
        with open(OUT / f"log_{'_'.join(sys.argv[1:])}.txt", "a", encoding="utf-8") as f:
            f.write(f"\n==== {task} {time.strftime('%F %T')}\n" + "\n".join(LOG[-400:]))
