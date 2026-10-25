"""可轉債（轉換公司債）：每日行情、轉換價、餘額、賣回／贖回條件，算出轉換價值、溢價率、賣回報酬率、理論權利金。

資料來源（全部是櫃買中心公開資料，不呼叫 AI）：
  1. 每日買賣斷交易行情表 RSta0113（2007 起）：開高低收、成交張數金額、均價
  2. 轉換公司債資訊看板 RSdrs001（2017 起）：目前轉換價、轉換期間、最近賣回權日期與價格、強制贖回、
     原始發行總額、上月底餘額、參考價、標的股價、停止交易
  3. OpenAPI bond_ISSBD5_data（最新）：發行日、到期日、最新餘額、擔保、評等、受託銀行、承銷商、發行時轉換價
計算：
  轉換價值 = 100 ÷ 轉換價 × 股價
  轉換溢價率 = CB 價 ÷ 轉換價值 − 1
  已轉換比例 = 1 − 餘額 ÷ 發行總額
  賣回年化報酬 = (下次賣回價 ÷ CB 價)^(1/年數) − 1（沒有賣回權就用到期，以面額 100 計）
  理論權利金（百元報價）= CB 價 − 下次賣回價 ÷ (1 + 折現率)^年數（折現率預設 3%，與券商實際 CBAS 報價可能不同）

輸出：
  site/data/cb.json             最新一天全部可轉債
  data/cb_history/日期.json      每日快照（保留 260 個交易日，畫圖與回測用）
  data/archive/cbq/、cbb/       原始行情與看板（長期保存，history 工作回補）
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, timedelta

from . import config, store
from .util import num, parse_date, read_json, write_json

log = logging.getLogger(__name__)
BASE = "https://www.tpex.org.tw/storage/bond_zone/tradeinfo/cb/{y}/{y}{m:02d}/{kind}.{ymd}-C.csv"
ISSUE_URL = "https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data"
HIST_DIR = config.DATA_DIR / "cb_history"
OUT = config.OUT_DIR / "cb.json"
KEEP = 260
DISCOUNT = 0.03
QUOTES_START = date(2007, 1, 2)
BOARD_START = date(2017, 1, 3)


# ------------------------------------------------------------------ 抓取與解析

def _csv_rows(text: str) -> list[dict]:
    """櫃買 CSV：HEADER 一列欄名，BODY 多列資料"""
    head, out = None, []
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if row[0] == "HEADER":
            head = [h.strip() for h in row[1:]]
        elif row[0] == "BODY" and head:
            out.append({h: (v.strip() if isinstance(v, str) else v) for h, v in zip(head, row[1:])})
    return out


def fetch_csv(kind: str, d: date) -> list[dict] | None:
    """kind：RSta0113（行情）或 RSdrs001（看板）。查無（假日、尚未公布）回 None"""
    from .http import session
    url = BASE.format(y=d.year, m=d.month, kind=kind, ymd=d.strftime("%Y%m%d"))
    try:
        r = session().get(url, timeout=config.HTTP_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        log.warning("可轉債 %s %s 抓取失敗：%s", kind, d, e)
        return None
    if r.status_code != 200 or len(r.content) < 50:
        return None
    rows = _csv_rows(r.content.decode("cp950", "replace"))
    return rows or None


def parse_quotes(rows: list[dict]) -> dict[str, dict]:
    """行情表：等價列有代號；緊接著的議價列沒有代號，屬於上一檔（只加總議價成交）"""
    out: dict[str, dict] = {}
    last = None
    for r in rows:
        code = r.get("代號", "")
        if code:
            last = code
            out[code] = {"name": r.get("名稱", "").strip(), "close": num(r.get("收市")), "chg": num(r.get("漲跌")),
                         "open": num(r.get("開市")), "high": num(r.get("最高")), "low": num(r.get("最低")),
                         "trades": num(r.get("筆數")), "lots": num(r.get("單位")), "value": num(r.get("金額")),
                         "avg": num(r.get("均價")), "ref_next": num(r.get("明日參價"))}
        elif last and r.get("交易") == "議價" and num(r.get("單位")):
            o = out[last]
            o["nego_lots"] = num(r.get("單位"))
            o["nego_close"] = num(r.get("收市"))
    return out


def _d(s) -> str | None:
    s = (s or "").strip()
    d = parse_date(s) if s else None
    return d.isoformat() if d else None


def parse_board(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for r in rows:
        code = r.get("債券代碼", "")
        if not code:
            continue
        out[code] = {
            "name": r.get("債券簡稱", "").strip(), "conv_start": _d(r.get("轉換起日")), "conv_end": _d(r.get("轉換迄日")),
            "conv_price": num(r.get("轉換價格")) or None, "conv_next_date": _d(r.get("下次轉換價格生效日期")),
            "stop_conv_start": _d(r.get("最近停止轉換起日")), "stop_conv_end": _d(r.get("最近停止轉換迄日")),
            "put_start": _d(r.get("最近賣回權起日")), "put_end": _d(r.get("最近賣回權迄日")),
            "put_price": num(r.get("最近賣回權價格")) or None,
            "call_start": _d(r.get("強制贖回起日")), "call_end": _d(r.get("強制贖回迄日")),
            "call_price": num(r.get("強制贖回價格")) or None, "delist": _d(r.get("終止櫃檯買賣日")),
            "issue_amt": num(r.get("原始發行總額")), "out_amt": num(r.get("上月底發行餘額")),
            "ref_price": num(r.get("轉債參考價格")), "stock_price": num(r.get("轉換標的股票價格")),
            "halt_start": _d(r.get("停止交易起日")), "halt_end": _d(r.get("停止交易迄日")),
            "coupon": num(r.get("票面利率")),
        }
    return out


def fetch_issue() -> dict[str, dict]:
    """OpenAPI 轉(交)換債發行資料（只取有交易代碼的）"""
    from .http import get_json
    out = {}
    for r in get_json(ISSUE_URL) or []:
        code = str(r.get("BondCode") or "").strip()
        if not code:
            continue
        g = lambda k: (r.get(k) or "").strip() if isinstance(r.get(k), str) else r.get(k)  # noqa: E731
        out[code] = {
            "issuer": g("IssuerCode"), "issuer_name": g("IssuerName"), "short": g("ShortName"),
            "issue_date": _d(g("IssueDate")), "maturity": _d(g("MaturityDate")), "listing_date": _d(g("ListingDate")),
            "issue_amt": num(g("IssueAmount")), "out_amt": num(g("OutstandingAmount")),
            "out_change_date": _d(g("OutstandingChangeDate")), "coupon": num(g("CouponRate")),
            "put_date": _d(g("PutOptionDate")), "put_price": num(g("PutOptionPrice")) or None,
            "conv_price_issue": num(g("Conversion/ExchangePriceAtIssuance")) or None,
            "guaranteed": g("Guaranteed") == "1", "guarantee": g("GuaranteeDescription"),
            "rating": " ".join(x for x in (g("BondRatingAgency"), g("BondRating")) if x),
            "issuer_rating": " ".join(x for x in (g("IssuerRatingAgency"), g("IssuerRating")) if x),
            "guarantor_rating": " ".join(x for x in (g("GuarantorRatingAgency"), g("GuarantorRating")) if x),
            "tenor": num(g("TenorYear")), "trustee": g("Trustee"), "underwriter": g("Underwriter"),
            "status": g("ListingStatus"),
        }
    return out


# ------------------------------------------------------------------ 計算

def _years(a: date, b: str | None) -> float | None:
    if not b:
        return None
    try:
        return (date.fromisoformat(b) - a).days / 365.0
    except ValueError:
        return None


def stock_stats(d: date, codes: set[str]) -> dict[str, dict]:
    """標的股票近 20 日：MA5、MA20、5 日／20 日均量（張）"""
    days = store.days_before(d, 20)
    ser: dict[str, list] = {}
    for x in days:
        day = store.load_day(x)
        for c in codes:
            q = day.get(c)
            if q and q.get("close"):
                ser.setdefault(c, []).append((q["close"], (q.get("volume") or 0) / 1000))
    out = {}
    for c, v in ser.items():
        cl, vo = [a for a, _ in v], [b for _, b in v]
        out[c] = {"ma5": round(sum(cl[-5:]) / len(cl[-5:]), 2), "ma20": round(sum(cl) / len(cl), 2) if len(cl) >= 20 else None,
                  "v5": round(sum(vo[-5:]) / len(vo[-5:])), "v20": round(sum(vo) / len(vo)) if len(vo) >= 20 else None}
    return out


def build_rows(d: date, quotes: dict, board: dict, issue: dict, stocks: dict,
               inst: dict | None = None, comp: dict | None = None, stats: dict | None = None) -> list[dict]:
    inst, comp, stats = inst or {}, comp or {}, stats or {}
    rows = []
    for code in sorted(set(board) | set(quotes)):
        q, b, i = quotes.get(code, {}), board.get(code, {}), issue.get(code, {})
        if b.get("delist") and b["delist"] < d.isoformat():
            continue
        stock = (i.get("issuer") if (i.get("issuer") or "").isdigit() and len(i.get("issuer")) == 4 else None) or code[:4]
        sq = stocks.get(stock) or {}
        spx = sq.get("close") or b.get("stock_price")
        cp = b.get("conv_price")
        close = q.get("close")
        px = close or b.get("ref_price") or q.get("avg")
        cv = round(100 / cp * spx, 2) if cp and spx else None
        prem = round((px / cv - 1) * 100, 2) if px and cv else None
        issue_amt = i.get("issue_amt") or b.get("issue_amt")
        out_amt = i.get("out_amt") if i.get("out_amt") is not None else b.get("out_amt")
        # 下一個賣回日：看板的最近賣回權（未過期）優先，其次發行資料的賣回日，都沒有就用到期日（面額 100）
        put_d, put_p = None, None
        for dd, pp in ((b.get("put_end") or b.get("put_start"), b.get("put_price")), (i.get("put_date"), i.get("put_price"))):
            if dd and dd >= d.isoformat() and pp:
                put_d, put_p = dd, pp
                break
        maturity = i.get("maturity") or b.get("conv_end")
        tgt_d, tgt_p, tgt_kind = (put_d, put_p, "賣回") if put_d else (maturity, 100.0, "到期")
        yrs = _years(d, tgt_d)
        yld = round(((tgt_p / px) ** (1 / yrs) - 1) * 100, 2) if px and yrs and yrs > 0.02 and tgt_p else None
        floor = tgt_p / (1 + DISCOUNT) ** yrs if tgt_p and yrs is not None and yrs >= 0 else None
        shares = (comp.get(stock) or {}).get("shares")
        conv_shares = out_amt / cp if out_amt and cp else None           # 餘額可轉換的股數
        st, iv = stats.get(stock) or {}, inst.get(stock) or {}
        rows.append({
            "code": code, "name": q.get("name") or b.get("name") or i.get("short", ""), "stock": stock,
            "stock_lots": round(sq["volume"] / 1000) if sq.get("volume") else None, **{k: st.get(k) for k in ("ma5", "ma20", "v5", "v20")},
            "inst": [iv.get("f"), iv.get("t"), iv.get("d")] if iv else None,
            "ratio": round(100000 / cp / 1000, 4) if cp else None,           # 每張 CB 可轉換幾張股票
            "conv_lots": round(conv_shares / 1000) if conv_shares else None,
            "dilution": round(conv_shares / shares * 100, 2) if conv_shares and shares else None,
            "remain": round(out_amt / issue_amt * 100, 2) if issue_amt and out_amt is not None else None,
            "days_left": (date.fromisoformat(maturity) - d).days if maturity else None,
            "stock_name": sq.get("name") or i.get("issuer_name", ""), "market": sq.get("market", ""),
            "close": close, "chg": q.get("chg"), "chg_pct": round(q["chg"] / (close - q["chg"]) * 100, 2) if close and q.get("chg") is not None and close != q["chg"] else None,
            "open": q.get("open"), "high": q.get("high"), "low": q.get("low"), "avg": q.get("avg"),
            "lots": q.get("lots"), "value": q.get("value"), "trades": q.get("trades"), "nego_lots": q.get("nego_lots"),
            "ref": b.get("ref_price"), "price": px,
            "stock_close": spx, "stock_chg": round((sq["close"] / sq["prev_close"] - 1) * 100, 2) if sq.get("close") and sq.get("prev_close") else None,
            "conv_price": cp, "conv_price_issue": i.get("conv_price_issue"), "conv_next_date": b.get("conv_next_date"),
            "conv_value": cv, "premium": prem,
            "conv_start": b.get("conv_start"), "conv_end": b.get("conv_end"),
            "stop_conv": [b.get("stop_conv_start"), b.get("stop_conv_end")] if b.get("stop_conv_start") else None,
            "issue_amt": issue_amt, "out_amt": out_amt, "out_amt_board": b.get("out_amt"),
            "converted": round((1 - out_amt / issue_amt) * 100, 2) if issue_amt and out_amt is not None else None,
            "issue_date": i.get("issue_date"), "listing_date": i.get("listing_date"), "maturity": maturity,
            "put_date": put_d, "put_price": put_p, "target": tgt_kind, "target_date": tgt_d, "target_price": tgt_p,
            "years": round(yrs, 2) if yrs is not None else None, "put_yield": yld,
            "put_ret": round((tgt_p / px - 1) * 100, 2) if px and tgt_p else None,
            "option": round(px - floor, 2) if px and floor else None,
            "call": [b.get("call_start"), b.get("call_end"), b.get("call_price")] if b.get("call_start") else None,
            "halt": [b.get("halt_start"), b.get("halt_end")] if b.get("halt_start") else None,
            "coupon": i.get("coupon") if i.get("coupon") is not None else b.get("coupon"),
            "guaranteed": i.get("guaranteed"), "guarantee": i.get("guarantee"),
            "rating": i.get("rating") or i.get("guarantor_rating") or i.get("issuer_rating") or "",
            "trustee": i.get("trustee"), "underwriter": i.get("underwriter"), "tenor": i.get("tenor"),
        })
    return rows


# ------------------------------------------------------------------ 每日工作

def snapshot(d: date, rows: list[dict]) -> None:
    """每日快照：圖表與回測用（只留關鍵數字）"""
    keep = ("close", "lots", "conv_value", "premium", "stock_close", "conv_price", "out_amt", "put_yield", "option",
            "open", "high", "low")
    write_json(HIST_DIR / f"{d.isoformat()}.json", {"date": d.isoformat(), "fields": list(keep),
                                                    "rows": {r["code"]: [r.get(k) for k in keep] for r in rows}})
    ds = sorted(p.stem for p in HIST_DIR.glob("????-??-??.json"))
    for x in ds[:-KEEP]:
        (HIST_DIR / f"{x}.json").unlink(missing_ok=True)


HIST_FIELDS = ("open", "high", "low", "close", "lots", "conv_value", "premium", "out_amt")


def history_series(n: int = 250) -> dict:
    """部署時產生 site/data/cb_hist.json：每檔近 n 日 [日期索引, 開, 高, 低, 收, 張數, 轉換價值, 溢價率, 餘額]"""
    files = sorted(HIST_DIR.glob("????-??-??.json"))[-n:]
    dates, series = [], {}
    for k, p in enumerate(files):
        js = read_json(p) or {}
        f = js.get("fields", [])
        dates.append(js.get("date", p.stem))
        ix = {x: f.index(x) for x in HIST_FIELDS if x in f}
        for code, v in (js.get("rows") or {}).items():
            series.setdefault(code, []).append([k, *(v[ix[x]] if x in ix else None for x in HIST_FIELDS)])
    return {"dates": dates, "fields": ["i", *HIST_FIELDS], "s": series}


def _arch_rows(kind: str, d: str) -> dict[str, dict]:
    from . import archive
    out = {}
    for r in archive.read(kind, d):
        out[r["code"]] = {k: (None if v == "" else (num(v) if k not in ("name",) and not k.endswith(("start", "end", "date", "delist")) else v))
                          for k, v in r.items() if k != "code"}
    return out


def rebuild_history(n: int = KEEP) -> int:
    """用長期資料庫的行情＋看板重建近 n 日快照（補齊圖表；只補還沒有的日子）。發行資料用最新一份近似"""
    from . import archive
    have = {p.stem for p in HIST_DIR.glob("????-??-??.json")}
    qdays = archive.days("cbq")[-n:]
    bdays = archive.days("cbb")
    if not qdays:
        return 0
    issue = fetch_issue()
    done = 0
    for ds in qdays:
        if ds in have:
            continue
        bd = max((x for x in bdays if x <= ds), default=None)
        if not bd:
            continue
        d = date.fromisoformat(ds)
        rows = build_rows(d, _arch_rows("cbq", ds), _arch_rows("cbb", bd), issue, store.load_day(d))
        have.add(ds)
        snapshot(d, rows)
        done += 1
    return done


def run(d: date | None = None, src=None, inst: dict | None = None, comp: dict | None = None) -> dict | None:
    """抓某天（預設最近交易日）的行情與看板，產生 cb.json 與快照；資料還沒公布就回 None"""
    from . import archive
    d = d or (store.trading_days()[-1] if store.trading_days() else date.today())
    qrows = fetch_csv("RSta0113", d)
    brows = fetch_csv("RSdrs001", d)
    if not qrows and not brows:
        log.info("可轉債 %s 尚未公布", d)
        return None
    if qrows:
        archive.write("cbq", d, [{"code": k, **v} for k, v in parse_quotes(qrows).items()])
    if brows:
        archive.write("cbb", d, [{"code": k, **v} for k, v in parse_board(brows).items()])
    issue = fetch_issue()
    stocks = store.load_day(d)
    codes = {c[:4] for c in set(parse_board(brows or [])) | set(parse_quotes(qrows or []))} | \
            {v["issuer"] for v in issue.values() if (v.get("issuer") or "").isdigit()}
    rows = build_rows(d, parse_quotes(qrows or []), parse_board(brows or []), issue, stocks,
                      inst, comp or (store.state("companies", {}) or {}).get("data", {}), stock_stats(d, codes))
    snapshot(d, rows)
    res = {"date": d.isoformat(), "discount": DISCOUNT, "n": len(rows), "has_board": bool(brows), "rows": rows,
           "updated": date.today().isoformat()}
    write_json(OUT, res)
    log.info("可轉債 %s：%d 檔（行情 %s、看板 %s）", d, len(rows), bool(qrows), bool(brows))
    return res


def backfill(minutes: float = 15) -> dict:
    """長期資料庫回補：行情 2007 起、看板 2017 起，由新到舊，可續跑"""
    import time as _t
    from . import archive
    t0 = _t.time()
    st = archive._progress()
    cb = st.setdefault("cb", {"closed": []})
    closed = set(cb.get("closed", []))
    noboard = set(cb.get("noboard", []))
    d, n, stopped = date.today() - timedelta(days=1), 0, ""
    while d >= QUOTES_START:
        if _t.time() - t0 > minutes * 60:
            stopped = "時間到"
            break
        ds = d.isoformat()
        if d.weekday() >= 5 or ds in closed:
            d -= timedelta(days=1)
            continue
        need_q = not archive.has("cbq", d)
        need_b = d >= BOARD_START and not archive.has("cbb", d) and ds not in noboard
        if need_q or need_b:
            got = False
            if need_q:
                rows = fetch_csv("RSta0113", d)
                if rows:
                    archive.write("cbq", d, [{"code": k, **v} for k, v in parse_quotes(rows).items()])
                    got = True
            if need_b:
                rows = fetch_csv("RSdrs001", d)
                if rows:
                    archive.write("cbb", d, [{"code": k, **v} for k, v in parse_board(rows).items()])
                    got = True
                else:
                    noboard.add(ds)
            if not got:
                closed.add(ds)       # 休市或查無
            n += 1
            _t.sleep(0.6)
        d -= timedelta(days=1)
    st = archive._progress()
    st["cb"] = {"closed": sorted(closed), "noboard": sorted(noboard), "last_run": _t.strftime("%Y-%m-%d %H:%M"), "fetched": n,
                "stopped": stopped or "完成", "quotes_days": len(archive.days("cbq")), "board_days": len(archive.days("cbb"))}
    archive._save_progress(st)
    log.info("可轉債歷史回補：本次 %d 天，狀態 %s", n, stopped or "完成")
    return st["cb"]


def write_hist_files(n: int = 250) -> int:
    """部署時：每檔一個 site/data/cbh/代號.json（點開才載入），價格兩位小數、餘額以億元計"""
    import shutil
    h = history_series(n)
    out = config.OUT_DIR / "cbh"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    r2 = lambda x: None if x is None else round(x, 2)  # noqa: E731
    for code, rows in h["s"].items():
        ix = [x[0] for x in rows]
        write_json(out / f"{code}.json", {"dates": [h["dates"][i] for i in ix],
                                          "rows": [[r2(v) for v in x[1:8]] + [None if x[8] is None else round(x[8] / 1e8, 2)] for x in rows]})
    return len(h["s"])


def main() -> int:
    """python -m pipeline.cb hist → 產生 site/data/cbh/*.json（部署時，不進 git）"""
    import sys
    if sys.argv[1:] == ["hist"]:
        write_hist_files()
        return 0
    return 0 if run() else 1


if __name__ == "__main__":
    raise SystemExit(main())
