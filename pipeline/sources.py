"""資料源：把證交所、櫃買中心、公開資訊觀測站各種格式整理成統一欄位。

所有 fetch_* 都回傳 list[dict]，欄位固定（見各函式 docstring），
後面的分析模組只吃這些統一格式，所以交易所改版只要修這個檔。
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from . import config
from .http import get_json
from .util import is_common_stock, num, parse_date, pick, roc, table_rows

log = logging.getLogger(__name__)
U = config.URLS

INDUSTRY = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織纖維", "05": "電機機械", "06": "電器電纜",
    "08": "玻璃陶瓷", "09": "造紙", "10": "鋼鐵", "11": "橡膠", "12": "汽車", "14": "建材營造",
    "15": "航運", "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他",
    "21": "化學", "22": "生技醫療", "23": "油電燃氣", "24": "半導體", "25": "電腦週邊",
    "26": "光電", "27": "通信網路", "28": "電子零組件", "29": "電子通路", "30": "資訊服務",
    "31": "其他電子", "32": "文化創意", "33": "農業科技", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "80": "管理股票", "91": "存託憑證",
}
INDUSTRY_BY_NAME = {v: k for k, v in INDUSTRY.items()}

_CN = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn_int(s: str) -> int | None:
    """'十二' → 12、'二十' → 20、'5' → 5"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if not s or any(c not in _CN for c in s):
        return None
    if "十" in s:
        a, _, b = s.partition("十")
        return (_CN[a] if a else 1) * 10 + (_CN[b] if b else 0)
    return _CN[s]


def parse_clauses(text: str) -> list[int]:
    """'第一款、第四款' / '第1、4款' / '異常標準第三款' → [1, 4]"""
    out: set[int] = set()
    for grp in re.findall(r"第([一二三四五六七八九十\d、,，及與]+)款", text or ""):
        for part in re.split(r"[、,，及與]", grp):
            n = cn_int(part)
            if n:
                out.add(n)
    return sorted(out)


def parse_minutes(text: str) -> int | None:
    """'約每五分鐘撮合一次' → 5、'每20分鐘' → 20"""
    m = re.search(r"每\s*([一二三四五六七八九十\d]+)\s*分鐘", text or "")
    return cn_int(m.group(1)) if m else None

# ------------------------------------------------------------------ 行情

def _quote(code, name, market, o, h, l, c, chg, vol, val, trades=None, avg=None):
    c = num(c)
    if c is None or not is_common_stock(str(code).strip()):
        return None
    chg = num(chg, 0.0)
    q = {
        "code": str(code).strip(), "name": str(name).strip(), "market": market,
        "open": num(o), "high": num(h), "low": num(l), "close": c,
        "change": chg, "prev_close": round(c - chg, 4),
        "volume": int(num(vol, 0)), "value": int(num(val, 0)), "trades": int(num(trades, 0)),
    }
    q["avg"] = num(avg) or (round(q["value"] / q["volume"], 2) if q["volume"] else c)
    return q


def fetch_quotes(d: date | None = None) -> tuple[date | None, list[dict]]:
    """全市場收盤行情。d=None 抓最新交易日。
    回傳 (交易日, [{code,name,market,open,high,low,close,change,prev_close,volume,value,trades,avg}])"""
    out: list[dict] = []
    trade_date: date | None = None

    # --- 上市 ---
    if d is not None:
        js = get_json(U["twse_quotes_by_date"].format(yyyymmdd=d.strftime("%Y%m%d")))
        if js and js.get("stat") == "OK":
            trade_date = parse_date(js.get("date")) or d
            for r in table_rows(js, must_have="證券代號"):
                sign = "-" if "-" in re.sub(r"<[^>]+>", "", str(r.get("漲跌(+/-)", ""))) else ""
                chg = f"{sign}{num(r.get('漲跌價差'), 0)}"
                q = _quote(r.get("證券代號"), r.get("證券名稱"), "TWSE", r.get("開盤價"), r.get("最高價"),
                           r.get("最低價"), r.get("收盤價"), chg, r.get("成交股數"), r.get("成交金額"), r.get("成交筆數"))
                if q:
                    out.append(q)
    else:
        js = get_json(U["twse_quotes"]) or []
        for r in js:
            trade_date = trade_date or parse_date(r.get("Date"))
            q = _quote(r.get("Code"), r.get("Name"), "TWSE", r.get("OpeningPrice"), r.get("HighestPrice"),
                       r.get("LowestPrice"), r.get("ClosingPrice"), r.get("Change"), r.get("TradeVolume"),
                       r.get("TradeValue"), r.get("Transaction"))
            if q:
                out.append(q)

    # --- 上櫃 ---
    tp: list[dict] = []
    if d is not None:
        tp = _tpex_by_date(d)
    else:
        tp_date = None
        for r in get_json(U["tpex_quotes"]) or []:
            tp_date = tp_date or parse_date(r.get("Date"))
            q = _quote(pick(r, "SecuritiesCompanyCode"), pick(r, "CompanyName"), "TPEX", pick(r, "Open"),
                       pick(r, "High"), pick(r, "Low"), pick(r, "Close"), pick(r, "Change"),
                       pick(r, "TradingShares", "TradeVolume"), pick(r, "TransactionAmount", "TradeValue"),
                       pick(r, "TransactionNumber"), pick(r, "Average", contains=False))
            if q:
                tp.append(q)
        # 櫃買 OpenAPI 常比證交所晚更新：日期不同或沒資料時，改用依日期查詢，避免混入前一天或整批漏掉
        if trade_date and (not tp or tp_date != trade_date):
            log.info("櫃買最新行情日期 %s 與上市 %s 不符，改用依日期查詢", tp_date, trade_date)
            tp = _tpex_by_date(trade_date)
            if not tp:
                log.warning("櫃買 %s 行情抓取失敗，本次只有上市資料", trade_date)
    out.extend(tp)
    if d is not None and out:
        trade_date = trade_date or d
    return trade_date, out


def _tpex_by_date(d: date) -> list[dict]:
    js = get_json(U["tpex_quotes_by_date"].format(yyyy=d.year, mm=f"{d.month:02d}", dd=f"{d.day:02d}"))
    rows = table_rows(js or {}, must_have="代號")
    if not rows:  # 舊版端點備援（無欄名，固定欄位順序）
        js = get_json(U["tpex_quotes_by_date_legacy"].format(roc=roc(d)))
        cols = ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額", "成交筆數"]
        rows = [dict(zip(cols, r)) for r in (js or {}).get("aaData", [])]
    out = []
    for r in rows:
        q = _quote(pick(r, "代號"), pick(r, "名稱"), "TPEX", pick(r, "開盤"), pick(r, "最高"), pick(r, "最低"),
                   pick(r, "收盤"), pick(r, "漲跌"), pick(r, "成交股數"), pick(r, "成交金額"),
                   pick(r, "成交筆數"), pick(r, "均價"))
        if q:
            out.append(q)
    return out


def fetch_holidays() -> set[date]:
    out = set()
    for r in get_json(U["holidays"]) or []:
        desc = str(pick(r, "Description", "Name", default=""))
        if "開始交易" in desc or "最後交易" in desc:
            continue
        d = parse_date(pick(r, "Date"))
        if d:
            out.add(d)
    return out

# ------------------------------------------------------------------ 公司、評價

def fetch_companies() -> dict[str, dict]:
    """{code: {code,name,market,industry_code,industry,capital,shares}}"""
    out = {}
    for market, key in (("TWSE", "twse_company"), ("TPEX", "tpex_company")):
        js = get_json(U[key]) or []
        before = len(out)
        if js and isinstance(js, list):
            log.info("%s 公司資料 %d 筆，欄位：%s", market, len(js), list(js[0].keys())[:8])
        for r in js:
            code = str(pick(r, "公司代號", "SecuritiesCompanyCode", default="")).strip()
            if not is_common_stock(code):
                continue
            ind = str(pick(r, "產業別", "SecuritiesIndustryCode", default="")).strip()
            ind = ind.zfill(2) if ind.isdigit() else INDUSTRY_BY_NAME.get(ind.replace("業", ""), ind)
            capital = num(pick(r, "實收資本額", "Paidin.Capital.NTDollars", "PaidInCapital"), 0) or 0
            shares = num(pick(r, "已發行普通股數", "IssueShares"), 0) or capital / 10
            out[code] = {
                "code": code, "name": str(pick(r, "公司簡稱", "CompanyAbbreviation", "公司名稱", "CompanyName", default=code)),
                "market": market, "industry_code": ind, "industry": INDUSTRY.get(ind, ind or "其他"),
                "capital": capital, "shares": shares,
            }
        if len(out) == before:
            log.warning("%s 公司基本資料抓取失敗或格式改變（%s）", market, U[key])
            from .util import write_json
            write_json(config.STATE_DIR / f"companies_debug_{market}.json",
                       {"url": U[key], "type": type(js).__name__, "len": len(js) if hasattr(js, "__len__") else None,
                        "sample": js[:2] if isinstance(js, list) else str(js)[:500]})
            if market == "TPEX":
                out.update(_tpex_isin())
    return out


def _tpex_isin() -> dict[str, dict]:
    """備援：從證交所 ISIN 一覽表取得上櫃股票的產業別（Big5 網頁）"""
    from .http import get_bytes
    raw = get_bytes(U["isin_tpex"])
    if not raw:
        return {}
    html = raw.decode("cp950", errors="replace")
    out = {}
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        tds = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) < 5:
            continue
        m = re.match(r"^(\d{4})[\s\u3000]+(.+)$", tds[0])
        if not m or not is_common_stock(m.group(1)):
            continue
        ind = tds[4].replace("業", "").strip()
        out[m.group(1)] = {"code": m.group(1), "name": m.group(2).strip(), "market": "TPEX",
                           "industry_code": INDUSTRY_BY_NAME.get(ind, ""), "industry": ind or "其他",
                           "capital": 0, "shares": 0}
    log.info("上櫃產業別改用 ISIN 一覽表：%d 檔", len(out))
    return out


def fetch_valuation() -> dict[str, dict]:
    """{code: {pe, pb, dy}}；PE 為空表示虧損"""
    out = {}
    for r in get_json(U["twse_pe"]) or []:
        out[str(r.get("Code", "")).strip()] = {"pe": num(r.get("PEratio")), "pb": num(r.get("PBratio")),
                                                "dy": num(r.get("DividendYield"))}
    for r in get_json(U["tpex_pe"]) or []:
        code = str(pick(r, "SecuritiesCompanyCode", default="")).strip()
        out[code] = {"pe": num(pick(r, "PriceEarningRatio", "PEratio")), "pb": num(pick(r, "PriceBookRatio", "PBratio")),
                     "dy": num(pick(r, "YieldRatio", "DividendYield"))}
    return out

# ------------------------------------------------------------------ 注意、處置

def fetch_notices(start: date, end: date) -> list[dict]:
    """注意股公告 [{date,code,name,market,clauses:[int],text}]"""
    out = []
    js = get_json(U["twse_notice"].format(start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d")))
    for r in table_rows(js or {}):
        code = str(pick(r, "證券代號", default="")).strip()
        text = str(pick(r, "注意交易資訊", default=""))
        d = parse_date(pick(r, "日期", default=""))
        if is_common_stock(code) and d:
            out.append({"date": d.isoformat(), "code": code, "name": str(pick(r, "證券名稱", default="")).strip(),
                        "market": "TWSE", "clauses": parse_clauses(text), "text": text})
    for r in get_json(U["tpex_notice"]) or []:
        code = str(pick(r, "SecuritiesCompanyCode", "證券代號", "Code", default="")).strip()
        text = str(pick(r, "TradingInformation", "注意交易資訊", "Information", default=""))
        d = parse_date(pick(r, "Date", "日期", default=""))
        if is_common_stock(code) and d and start <= d <= end:
            out.append({"date": d.isoformat(), "code": code, "name": str(pick(r, "CompanyName", "證券名稱", "Name", default="")),
                        "market": "TPEX", "clauses": parse_clauses(text), "text": text})
    return out


def _period(text: str) -> tuple[date | None, date | None]:
    ds = re.findall(r"\d{2,4}[/\-.]\d{1,2}[/\-.]\d{1,2}|\d{7,8}", text or "")
    ds = [parse_date(x.replace(".", "/")) for x in ds]
    ds = [x for x in ds if x]
    return (ds[0], ds[-1]) if len(ds) >= 2 else (None, None)


def fetch_punish(start: date, end: date) -> list[dict]:
    """處置股 [{code,name,market,announce,start,end,minutes,reason,times}]"""
    out = []
    js = get_json(U["twse_punish"].format(start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d")))
    for r in table_rows(js or {}):
        code = str(pick(r, "證券代號", default="")).strip()
        if not is_common_stock(code):
            continue
        s, e = _period(str(pick(r, "處置起迄", "處置期間", default="")))
        body = " ".join(str(v) for v in r.values())
        out.append({"code": code, "name": str(pick(r, "證券名稱", default="")).strip(), "market": "TWSE",
                    "announce": str(parse_date(pick(r, "公布日期", default="")) or ""),
                    "start": str(s or ""), "end": str(e or ""), "minutes": parse_minutes(body),
                    "reason": str(pick(r, "處置條件", default="")).strip(),
                    "times": cn_int(re.search(r"第([一二三四五\d]+)次", body).group(1)) if re.search(r"第([一二三四五\d]+)次", body) else 1})
    for r in get_json(U["tpex_punish"]) or []:
        code = str(pick(r, "SecuritiesCompanyCode", "證券代號", "Code", default="")).strip()
        if not is_common_stock(code):
            continue
        body = " ".join(str(v) for v in r.values())
        s, e = _period(str(pick(r, "DispositionPeriod", "處置期間", "處置起迄", default=body)))
        out.append({"code": code, "name": str(pick(r, "CompanyName", "證券名稱", "Name", default="")), "market": "TPEX",
                    "announce": str(parse_date(pick(r, "Date", "公布日期", default="")) or ""),
                    "start": str(s or ""), "end": str(e or ""), "minutes": parse_minutes(body),
                    "reason": str(pick(r, "DispositionReasons", "處置原因", "處置條件", default="")).strip(),
                    "times": cn_int(re.search(r"第([一二三四五\d]+)次", body).group(1)) if re.search(r"第([一二三四五\d]+)次", body) else 1})
    return [p for p in out if p["end"]]

# ------------------------------------------------------------------ 公告

def fetch_material() -> list[dict]:
    """重大訊息 [{date,time,code,name,market,subject,body,clause}]"""
    out = []
    for market, key in (("TWSE", "twse_material"), ("TPEX", "tpex_material")):
        for r in get_json(U[key]) or []:
            code = str(pick(r, "公司代號", "SecuritiesCompanyCode", default="")).strip()
            d = parse_date(pick(r, "發言日期", "SpokesmanDate", "Date", default=""))
            t = str(pick(r, "發言時間", "SpokesmanTime", default="")).zfill(6)
            out.append({
                "date": str(d or ""), "time": f"{t[:2]}:{t[2:4]}" if t.isdigit() else t,
                "code": code, "name": str(pick(r, "公司名稱", "CompanyName", default="")).strip(), "market": market,
                "subject": str(pick(r, "主旨", "Subject", default="")).strip(),
                "body": str(pick(r, "說明", "Description", default="")).strip(),
                "clause": str(pick(r, "符合條款", "Clause", default="")).strip(),
            })
    return [x for x in out if x["code"]]


def _lots(v) -> int | None:
    x = num(v)
    return None if x is None else int(round(x / 1000))


def fetch_institutional(d: date) -> dict[str, dict]:
    """三大法人買賣超（張）：{code: {f: 外資, t: 投信, d: 自營商}}。外資含外資自營商。"""
    out: dict[str, dict] = {}
    js = get_json(U["twse_inst"].format(yyyymmdd=d.strftime("%Y%m%d")))
    if js and js.get("stat", "OK") == "OK":
        for r in table_rows(js, must_have="證券代號"):
            code = str(r.get("證券代號", "")).strip()
            if not is_common_stock(code):
                continue
            f = num(pick(r, "外陸資買賣超股數(不含外資自營商)", "外陸資買賣超股數", "外資買賣超股數"), 0) or 0
            f += num(pick(r, "外資自營商買賣超股數", contains=False), 0) or 0
            out[code] = {"f": int(round(f / 1000)), "t": _lots(pick(r, "投信買賣超股數")) or 0,
                         "d": _lots(pick(r, "自營商買賣超股數", contains=False)) or 0}
    js = get_json(U["tpex_inst"].format(yyyy=d.year, mm=f"{d.month:02d}", dd=f"{d.day:02d}"))
    for r in table_rows(js or {}, must_have="代號"):
        code = str(pick(r, "代號", default="")).strip()
        if not is_common_stock(code):
            continue
        f = pick(r, "外資及陸資-買賣超股數", "外資及陸資買賣超股數", contains=False)
        if f is None:  # 沒有合計欄時自己加總
            f = (num(pick(r, "外資及陸資(不含外資自營商)-買賣超股數", "不含外資自營商)-買賣超"), 0) or 0) + \
                (num(pick(r, "外資自營商-買賣超股數"), 0) or 0)
        dd = pick(r, "自營商-買賣超股數", "自營商買賣超股數", contains=False)
        if dd is None:
            dd = (num(pick(r, "自營商(自行買賣)-買賣超股數"), 0) or 0) + (num(pick(r, "自營商(避險)-買賣超股數"), 0) or 0)
        out[code] = {"f": _lots(f) or 0, "t": _lots(pick(r, "投信-買賣超股數", "投信買賣超股數")) or 0, "d": _lots(dd) or 0}
    if not out:
        log.warning("三大法人 %s 抓取失敗或尚未公布", d)
    return out


def fetch_business(code: str) -> str:
    """公開資訊觀測站公司基本資料的『主要經營業務』，抓不到回空字串。"""
    from .http import session
    data = {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "queryName": "co_id",
            "inpuType": "co_id", "TYPEK": "all", "co_id": code}
    try:
        r = session().post(U["mops_profile"], data=data, timeout=config.HTTP_TIMEOUT)
        r.encoding = "utf-8"
        html = r.text
    except Exception as e:  # noqa: BLE001
        log.warning("公司基本資料 %s 抓取失敗：%s", code, e)
        return ""
    m = re.search(r"主要經營業務.*?<td[^>]*>(.*?)</td>", html, re.S)
    if not m:
        return ""
    txt = re.sub(r"<[^>]+>", " ", m.group(1))
    txt = re.sub(r"&nbsp;?", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()[:300]


def fetch_material_mops(d: date) -> list[dict] | None:
    """公開資訊觀測站 d 日全部重大訊息（上市、上櫃），含完整說明。失敗回 None。
    [{date,time,code,name,market,subject,body,clause}]"""
    import html as _html
    from .http import session
    data = {"step": "0", "newstuff": "1", "firstin": "1", "year": str(d.year - 1911), "month": str(d.month), "day": str(d.day)}
    try:
        r = session().post(U["mops_material_day"], data=data, timeout=config.HTTP_TIMEOUT)
        r.encoding = "utf-8"
        page = r.text
    except Exception as e:  # noqa: BLE001
        log.warning("觀測站重大訊息 %s 抓取失敗：%s", d, e)
        return None
    if "查詢過於頻繁" in page or "頁面無法執行" in page:
        log.warning("觀測站重大訊息 %s 被拒：查詢過於頻繁", d)
        return None
    out = []
    for form in re.findall(r"<form[^>]*ajax_t05st02.*?</form>", page, re.S | re.I):
        vals = [_html.unescape(m[1]) for m in re.findall(r"""name=['"]h\d+['"] value=(['"])(.*?)\1\s*/?>""", form, re.S)]
        if len(vals) < 9:
            continue
        name, code, ymd, hms, subject, _, _, _, body = vals[:9]
        typek = re.search(r'TYPEK\.value=(?:&quot;|")(\w+)', form)
        typek = typek.group(1) if typek else ""
        if typek not in ("sii", "otc"):
            continue
        code = code.strip()
        out.append({
            "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if len(ymd) == 8 else "",
            "time": f"{hms.zfill(6)[:2]}:{hms.zfill(6)[2:4]}",
            "code": code, "name": name.strip(), "market": "TWSE" if typek == "sii" else "TPEX",
            "subject": re.sub(r"\s+", " ", subject).strip(), "body": body.strip(), "clause": "",
        })
    log.info("觀測站重大訊息 %s：%d 筆", d, len(out))
    return out


def fetch_exrights() -> list[dict]:
    """上市、上櫃除權除息預告表 [{code,name,market,kind,from,to,detail}]"""
    out = []
    for r in get_json(U["twse_exright"]) or []:
        d = parse_date(r.get("Date"))
        code = str(r.get("Code", "")).strip()
        if d and is_common_stock(code):
            k = str(r.get("Exdividend", "")).replace("除", "")
            out.append({"code": code, "name": str(r.get("Name", "")).strip(), "market": "TWSE", "kind": k or "息",
                        "from": d.isoformat(), "to": d.isoformat(), "detail": f"現金股利 {r.get('CashDividend') or '—'}"})
    for r in get_json(U["tpex_exright"]) or []:
        d = parse_date(pick(r, "ExRrightsExDividendDate", "Date", default=""))
        code = str(pick(r, "SecuritiesCompanyCode", default="")).strip()
        if d and is_common_stock(code):
            k = str(pick(r, "ExRrightsExDividend", default="")).replace("除", "")
            out.append({"code": code, "name": str(pick(r, "CompanyName", default="")).strip(), "market": "TPEX",
                        "kind": k or "息", "from": d.isoformat(), "to": d.isoformat(),
                        "detail": f"現金股利 {num(pick(r, 'CashDividend', default=None)) or '—'}"})
    return out


def fetch_revenue() -> list[dict]:
    """月營收 [{ym,code,name,market,industry,rev,rev_prev,rev_ly,mom,yoy,cum,cum_yoy,note}]（單位：千元）"""
    out = []
    for market, key in (("TWSE", "twse_revenue"), ("TPEX", "tpex_revenue")):
        for r in get_json(U[key]) or []:
            code = str(pick(r, "公司代號", "SecuritiesCompanyCode", default="")).strip()
            if not is_common_stock(code):
                continue
            ym = str(pick(r, "資料年月", "DataYearMonth", default=""))
            out.append({
                "ym": ym, "code": code, "name": str(pick(r, "公司名稱", "CompanyName", default="")).strip(), "market": market,
                "industry": str(pick(r, "產業別", "Industry", default="")),
                "rev": num(pick(r, "營業收入-當月營收", "當月營收")), "rev_prev": num(pick(r, "營業收入-上月營收", "上月營收")),
                "rev_ly": num(pick(r, "營業收入-去年當月營收", "去年當月營收")),
                "mom": num(pick(r, "營業收入-上月比較增減(%)", "上月比較增減")), "yoy": num(pick(r, "營業收入-去年同月增減(%)", "去年同月增減")),
                "cum": num(pick(r, "累計營業收入-當月累計營收", "當月累計營收")),
                "cum_yoy": num(pick(r, "累計營業收入-前期比較增減(%)", "前期比較增減")),
                "note": str(pick(r, "備註", "Remark", default="")).strip().strip("-"),
            })
    return out


def fetch_eps() -> list[dict]:
    """季報 EPS [{year,quarter,code,name,market,industry,eps,revenue,op_income,net_income}]"""
    out = []
    for market, key in (("TWSE", "twse_eps"), ("TPEX", "tpex_eps")):
        for r in get_json(U[key]) or []:
            code = str(pick(r, "公司代號", "SecuritiesCompanyCode", default="")).strip()
            if not is_common_stock(code):
                continue
            out.append({
                "year": int(num(pick(r, "年度", "Year"), 0) or 0), "quarter": int(num(pick(r, "季別", "Season"), 0) or 0),
                "code": code, "name": str(pick(r, "公司名稱", "CompanyName", default="")).strip(), "market": market,
                "industry": str(pick(r, "產業別", "Industry", default="")),
                "eps": num(pick(r, "基本每股盈餘", "EPS")), "revenue": num(pick(r, "營業收入", "Revenue")),
                "op_income": num(pick(r, "營業利益", "OperatingIncome")), "net_income": num(pick(r, "稅後淨利", "NetIncome")),
            })
    return out

# ------------------------------------------------------------------ 券差借券費率

def fetch_borrow_fee(d: date) -> list[dict]:
    """[{date,code,name,market,lots,rate}]：rate 為日費率 %"""
    out = []
    js = get_json(U["twse_borrow_fee"].format(yyyymmdd=d.strftime("%Y%m%d")))
    for r in table_rows(js or {}):
        code = str(pick(r, "證券代號", "股票代號", "代號", default="")).strip()
        if is_common_stock(code):
            out.append({"date": d.isoformat(), "code": code, "name": str(pick(r, "證券名稱", "股票名稱", "名稱", default="")).strip(),
                        "market": "TWSE", "lots": num(pick(r, "借券數量", "數量", "股數"), 0) / 1000,
                        "rate": num(pick(r, "費率", "借券費率"), 0)})
    js = get_json(U["tpex_borrow_fee"].format(yyyy=d.year, mm=f"{d.month:02d}", dd=f"{d.day:02d}"))
    for r in table_rows(js or {}):
        code = str(pick(r, "證券代號", "股票代號", "代號", default="")).strip()
        if is_common_stock(code):
            out.append({"date": d.isoformat(), "code": code, "name": str(pick(r, "證券名稱", "股票名稱", "名稱", default="")).strip(),
                        "market": "TPEX", "lots": num(pick(r, "借券數量", "數量", "股數"), 0) / 1000,
                        "rate": num(pick(r, "費率", "借券費率"), 0)})
    return out


def recent_weekdays(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]
