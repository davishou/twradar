"""可轉債 IPO（預計發行／近期發行）：把三個公開來源合併成一張表。

  1. 證券商業同業公會 承銷公告（web.twsa.org.tw/edoc2）：申報日期、主辦承銷商、案件、有無擔保、詢價圈購或競價拍賣
  2. 同上 詢圈公告：承銷張數、詢圈張數、圈購期間、價格區間（百元價）
  3. 證交所 競價拍賣公告 API：投標期間、開標日、競拍張數、最低投標價、得標價（最低／最高／加權平均）、承銷價、撥券（掛牌）日、債券代號
  4. 櫃買 OpenAPI 轉(交)換債發行資料：發行日、到期日、發行時轉換價、年期（已發行者）
輸出 site/data/cbipo.json；另產生 site/data/cb_index.json（哪些股票有可轉債、即將發行），給全站表格標色。不呼叫 AI。
"""
from __future__ import annotations

import html as _html
import logging
import re
from datetime import date, timedelta

from . import config, store
from .util import num, parse_date, read_json, write_json

log = logging.getLogger(__name__)
TWSA = "https://web.twsa.org.tw/edoc2/default.aspx"
AUCTION = "https://www.twse.com.tw/rwd/zh/announcement/auction?date={y}&response=json"
OUT = config.OUT_DIR / "cbipo.json"
INDEX = config.OUT_DIR / "cb_index.json"
CB_RE = re.compile(r"轉換公司債|交換公司債")


def _cells(tr: str) -> list[str]:
    return [re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", x))).strip()
            for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]


def _links(tr: str) -> list[str]:
    return [_html.unescape(h) for h in re.findall(r'href="([^"]+)"', tr)]


def _twsa_rows(page: str, head_word: str) -> list[dict]:
    """找出表頭含 head_word 的表格，回傳 list[dict]（欄名→值），附公告檔連結"""
    for tbl in re.findall(r"<table[^>]*>(.*?)</table>", page, re.S | re.I):
        if head_word not in tbl or "<table" in tbl.lower():
            continue
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S | re.I)
        if not trs:
            continue
        head = [re.sub(r"\s+", "", _html.unescape(re.sub(r"<[^>]+>", "", x)))
                for x in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", trs[0], re.S | re.I)]
        if head_word not in "".join(head):
            continue
        out = []
        for tr in trs[1:]:
            c = _cells(tr)
            if len(c) >= len(head) - 1 and c and c[0][:1].isdigit():
                row = dict(zip(head, c))
                links = [u for u in _links(tr) if u.lower().endswith(".pdf") or "file" in u.lower()]
                if links:
                    row["_pdf"] = links[0] if links[0].startswith("http") else "https://web.twsa.org.tw/edoc2/" + links[0].lstrip("./")
                out.append(row)
        return out
    return []


def fetch_twsa() -> dict[str, list[dict]]:
    """今年的承銷公告與詢圈公告（只留轉換／交換公司債）"""
    from .http import session
    s = session()
    out = {"notice": [], "bookbuild": []}
    try:
        page = s.get(TWSA, timeout=config.HTTP_TIMEOUT).text
    except Exception as e:  # noqa: BLE001
        log.warning("公會承銷公告抓取失敗：%s", e)
        return out
    out["notice"] = [r for r in _twsa_rows(page, "案件名稱") if CB_RE.search(r.get("發行種類", ""))]
    form = {m[0]: _html.unescape(m[1]) for m in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page)
            if m[0].startswith("__")}
    year = re.search(r'name="ctl00\$cphMain\$ddlYear".*?<option[^>]*selected="selected"[^>]*value="(\d+)"', page, re.S)
    radios = re.findall(r'id="(ctl00_cphMain_rblReportType_\d+)"[^>]*value="(\w+)"', page)
    idx = next((i.rsplit("_", 1)[1] for i, v in radios if v == "BookBuilding"), "2")
    form.update({"__EVENTTARGET": f"ctl00$cphMain$rblReportType${idx}", "__EVENTARGUMENT": "",
                 "ctl00$cphMain$rblReportType": "BookBuilding",
                 "ctl00$cphMain$ddlYear": year.group(1) if year else str(date.today().year)})
    try:
        page2 = s.post(TWSA, data=form, timeout=config.HTTP_TIMEOUT).text
        out["bookbuild"] = [r for r in _twsa_rows(page2, "圈購期間") if CB_RE.search(r.get("發行性質", ""))]
    except Exception as e:  # noqa: BLE001
        log.warning("公會詢圈公告抓取失敗：%s", e)
    return out


def fetch_auctions(years: list[int]) -> list[dict]:
    """證交所競價拍賣公告（只留轉換／交換公司債）"""
    from .http import get_json
    from .util import table_rows
    out = []
    for y in years:
        js = get_json(AUCTION.format(y=y)) or {}
        for r in table_rows(js, must_have="證券名稱"):
            if CB_RE.search(str(r.get("發行性質", ""))):
                out.append(r)
    return out


# ------------------------------------------------------------------ 合併

def match_company(full: str, comp: dict) -> str | None:
    """公司全名 → 股票代號（先比全名，再找最長的簡稱）"""
    f = re.sub(r"[\s　]|-KY|ＫＹ|KY", "", full or "")
    if not f:
        return None
    for c, v in comp.items():
        if v.get("full") and re.sub(r"[\s　]|-KY|ＫＹ|KY", "", v["full"]) == f:
            return c
    best, blen = None, 0
    for c, v in comp.items():
        n = re.sub(r"-KY|KY|\*", "", v.get("name", ""))
        if len(n) >= 2 and f.startswith(n) and len(n) > blen:
            best, blen = c, len(n)
    return best


def _period(s: str) -> tuple[str | None, str | None]:
    ds = re.findall(r"\d{3,4}/\d{1,2}/\d{1,2}", s or "")
    d = [parse_date(x) for x in ds]
    d = [x.isoformat() for x in d if x]
    return (d[0] if d else None, d[-1] if d else None)


def build(today: date, twsa: dict, auctions: list[dict], issue: dict, cb_rows: list[dict], comp: dict, stocks: dict) -> dict:
    items: dict[str, dict] = {}

    def item(stock: str | None, name: str, guar: str, method: str) -> dict:
        """同一公司、同擔保、同銷售方式（詢圈／競拍）視為同一案"""
        m = "詢圈" if "詢" in (method or "") else "競拍"
        key = f"{stock or name}|{'有' if '有擔保' in guar else '無'}|{m}"
        return items.setdefault(key, {"stock": stock, "company": name, "guaranteed": "有擔保" in guar,
                                      "method": "詢價圈購" if m == "詢圈" else "競價拍賣"})

    for r in twsa.get("notice", []):
        stock = match_company(r.get("案件名稱", ""), comp)
        it = item(stock, r.get("案件名稱", ""), r.get("發行種類", ""), r.get("配售方式一", ""))
        it["filed"] = (parse_date(r.get("申報日期")) or today).isoformat() if r.get("申報日期") else None
        it["underwriter"] = r.get("主辦承銷商", "")
        it.setdefault("notice_pdf", r.get("_pdf"))
        it["status_note"] = r.get("案件狀態", "")
    for r in twsa.get("bookbuild", []):
        stock = match_company(r.get("發行公司", ""), comp)
        it = item(stock, r.get("發行公司", ""), r.get("發行性質", ""), "詢價圈購")
        a, b = _period(r.get("圈購期間", ""))
        it.update({"bb_start": a, "bb_end": b, "bb_price": r.get("價格(元)", ""),
                   "lots": num(r.get("承銷股數(千股/張)")), "bb_lots": num(r.get("詢圈銷售股數(千股/張)")),
                   "underwriter": it.get("underwriter") or r.get("主辦承銷商", "")})
    for r in auctions:
        code = str(r.get("證券代號", "")).strip()
        stock = code[:4] if code[:4].isdigit() else None
        it = item(stock, r.get("證券名稱", ""), r.get("發行性質", ""), "競價拍賣")
        it.update({"bond": code, "short": r.get("證券名稱", ""),
                   "auc_start": (parse_date(r.get("投標開始日")) or today).isoformat() if r.get("投標開始日") else None,
                   "auc_end": (parse_date(r.get("投標結束日")) or today).isoformat() if r.get("投標結束日") else None,
                   "auc_open": (parse_date(r.get("開標日期")) or today).isoformat() if r.get("開標日期") else None,
                   "auc_lots": num(r.get("競拍數量(張)")), "auc_min": num(r.get("最低投標價格(元)")),
                   "won_low": num(r.get("最低得標價格(元)")) or None, "won_high": num(r.get("最高得標價格(元)")) or None,
                   "won_avg": num(r.get("得標加權平均價格(元)")) or None, "uw_price": num(r.get("實際承銷價格(元)")) or None,
                   "won_lots": num(r.get("合格投標數量(張)")) or None, "won_n": num(r.get("總合格件")) or None,
                   "listing": (parse_date(r.get("撥券日期(上市、上櫃日期)")) or today).isoformat() if r.get("撥券日期(上市、上櫃日期)") else None,
                   "underwriter": r.get("主辦券商", "") or None, "cancel": r.get("取消競價拍賣(流標或取消)", "")})
    # 補發行資料（發行時轉換價、年期、到期）與現況
    iss_by_stock: dict[str, list] = {}
    for code, v in issue.items():
        if (v.get("issuer") or "").isdigit():
            iss_by_stock.setdefault(v["issuer"], []).append({**v, "bond": code})
    cb_by_code = {r["code"]: r for r in cb_rows}
    out = []
    for v in items.values():
        st = v.get("stock")
        cand = sorted(iss_by_stock.get(st, []), key=lambda x: x.get("issue_date") or "", reverse=True)
        iss = next((x for x in cand if v.get("bond") and x["bond"] == v["bond"]), None) or \
            next((x for x in cand if (x.get("issue_date") or "") >= (today - timedelta(days=120)).isoformat()), None)
        if iss:
            v.setdefault("bond", iss["bond"])
            v.update({"conv_price": iss.get("conv_price_issue"), "tenor": iss.get("tenor"), "issue_date": iss.get("issue_date"),
                      "maturity": iss.get("maturity"), "amount": iss.get("issue_amt")})
            v.setdefault("listing", iss.get("listing_date"))
            v["short"] = v.get("short") or iss.get("short")
        cur = cb_by_code.get(v.get("bond") or "")
        if cur:
            v.update({"cb_close": cur.get("close") or cur.get("price"), "cb_premium": cur.get("premium"),
                      "conv_value": cur.get("conv_value")})
        q = stocks.get(st or "") or {}
        v["stock_name"] = (comp.get(st or "") or {}).get("name", "")
        v["stock_close"] = q.get("close")
        if v.get("conv_price") and q.get("close"):
            v["parity"] = round(100 / v["conv_price"] * q["close"], 2)
        if not v.get("amount") and v.get("lots"):
            v["amount"] = v["lots"] * 100000
        v["status"] = _status(v, today)
        out.append(v)
    order = {"詢圈中": 0, "競拍中": 1, "待開標": 2, "待掛牌": 3, "已申報": 4, "已掛牌": 5, "取消": 6}
    out.sort(key=lambda x: (order.get(x["status"], 9), -(int((x.get("listing") or x.get("filed") or "0000-00-00").replace("-", "")))))
    return {"date": today.isoformat(), "items": out}


def _status(v: dict, today: date) -> str:
    t = today.isoformat()
    if v.get("cancel"):
        return "取消"
    if v.get("listing") and v["listing"] <= t:
        return "已掛牌"
    if v.get("auc_start") and v["auc_start"] <= t <= (v.get("auc_end") or t):
        return "競拍中"
    if v.get("auc_end") and v["auc_end"] < t and not v.get("won_avg"):
        return "待開標"
    if v.get("bb_start") and v["bb_start"] <= t <= (v.get("bb_end") or t):
        return "詢圈中"
    if v.get("listing") or v.get("won_avg") or (v.get("bb_end") and v["bb_end"] < t):
        return "待掛牌"
    return "已申報"


def write_index(cb_rows: list[dict], ipo: dict) -> None:
    """{股票代號: {"cb": 可轉債檔數, "ipo": 狀態}}，給全站表格標色"""
    idx: dict[str, dict] = {}
    for r in cb_rows:
        if r.get("stock"):
            idx.setdefault(r["stock"], {}).setdefault("cb", 0)
            idx[r["stock"]]["cb"] += 1
    for v in ipo.get("items", []):
        if v.get("stock") and v["status"] in ("已申報", "詢圈中", "競拍中", "待開標", "待掛牌"):
            idx.setdefault(v["stock"], {})["ipo"] = v["status"]
    write_json(INDEX, idx)


def run(today: date | None = None) -> dict:
    from . import cb
    today = today or date.today()
    comp = (store.state("companies", {}) or {}).get("data", {})
    cbjs = read_json(cb.OUT, {}) or {}
    issue = cb.fetch_issue()
    stocks = store.load_day(store.trading_days()[-1]) if store.trading_days() else {}
    res = build(today, fetch_twsa(), fetch_auctions([today.year, today.year - 1] if today.month <= 2 else [today.year]),
                issue, cbjs.get("rows", []), comp, stocks)
    # 只留今年申報、或還沒掛牌、或 60 天內掛牌的
    cut = (today - timedelta(days=60)).isoformat()
    res["items"] = [v for v in res["items"] if v["status"] != "已掛牌" or (v.get("listing") or "") >= cut]
    write_json(OUT, res)
    write_index(cbjs.get("rows", []), res)
    log.info("可轉債 IPO：%d 筆", len(res["items"]))
    return res
