"""季度財報資料庫：從公開資訊觀測站「綜合損益表彙總表」取得各公司每季累計數，
換算成單季，供自結、季報頁比較「上季」用。

存在 data/state/fin_db.json：{code: {"115Q2": {rev, gross, op, nonop, pretax, eps, fetched}}}（累計值，單位千元）
"""
from __future__ import annotations

import html as _html
import logging
import re
import time
from datetime import date

from . import config, store
from .util import num

log = logging.getLogger(__name__)
URL = "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04"
FIELDS = {  # 欄名關鍵字 → 欄位（一般業；金融業欄名不同，只取得到的）
    "營業收入": "rev", "收益合計": "rev", "淨收益": "rev",
    "營業毛利（毛損）淨額": "gross", "營業毛利（毛損）": "gross",
    "營業利益（損失）": "op", "營業外收入及支出": "nonop",
    "稅前淨利（淨損）": "pretax", "繼續營業單位稅前淨利（淨損）": "pretax", "繼續營業單位稅前損益": "pretax",
    "基本每股盈餘（元）": "eps",
}


def _quarters_back(n: int) -> list[tuple[int, int]]:
    """最近 n 個『應已公布』的季度（民國年, 季），新→舊"""
    t = date.today()
    y, q = t.year - 1911, (t.month - 1) // 3  # 本季尚未結束，從上一季開始
    if q == 0:
        y, q = y - 1, 4
    out = []
    for _ in range(n):
        out.append((y, q))
        y, q = (y, q - 1) if q > 1 else (y - 1, 4)
    return out


def _parse(page: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tbl in re.findall(r"<table[^>]*>(.*?)</table>", page, re.S | re.I):
        heads = [re.sub(r"<[^>]+>|\s", "", _html.unescape(h)) for h in re.findall(r"<th[^>]*>(.*?)</th>", tbl, re.S | re.I)]
        if "公司代號" not in heads:
            continue
        cols = {}
        for i, h in enumerate(heads):
            for k, f in FIELDS.items():
                if h == k and f not in cols.values():
                    cols[i] = f
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S | re.I):
            tds = [re.sub(r"<[^>]+>", "", _html.unescape(x)).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
            if len(tds) < len(heads) or not re.fullmatch(r"\d{4}", tds[0]):
                continue
            out[tds[0]] = {f: num(tds[i]) for i, f in cols.items()}
    return out


def fetch_quarter(typek: str, y: int, q: int) -> dict[str, dict] | None:
    from .http import session
    data = {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "isQuery": "Y",
            "TYPEK": typek, "year": str(y), "season": f"{q:02d}"}
    try:
        r = session().post(URL, data=data, timeout=60)
        r.encoding = "utf-8"
        page = r.text
    except Exception as e:  # noqa: BLE001
        log.warning("綜合損益表 %s %sQ%s 抓取失敗：%s", typek, y, q, e)
        return None
    if "查詢過於頻繁" in page:
        log.warning("綜合損益表 %s %sQ%s：查詢過於頻繁", typek, y, q)
        return None
    return _parse(page)


def update(n_quarters: int = 6, refresh_recent: int = 2) -> dict:
    """補齊最近 n 季；最新 refresh_recent 季每 3 天重抓一次（陸續有公司公布）"""
    db = store.state("fin_db", {}) or {}
    meta = db.setdefault("_fetched", {})
    today = date.today()
    for i, (y, q) in enumerate(_quarters_back(n_quarters)):
        label = f"{y}Q{q}"
        last = meta.get(label)
        if last and (i >= refresh_recent or (today - date.fromisoformat(last)).days < 3):
            continue
        got = 0
        for typek in ("sii", "otc"):
            rows = fetch_quarter(typek, y, q)
            time.sleep(4)
            if rows is None:
                continue
            for code, v in rows.items():
                db.setdefault(code, {})[label] = v
                got += 1
        if got:
            meta[label] = today.isoformat()
            log.info("財報資料庫 %s：%d 家", label, got)
    store.save_state("fin_db", db)
    return db


def single(db: dict, code: str, y: int, q: int) -> dict | None:
    """單季數字（累計相減）。缺前一季累計時，Q1 直接用累計，其餘回 None"""
    c = db.get(code) or {}
    cur = c.get(f"{y}Q{q}")
    if not cur:
        return None
    if q == 1:
        s = dict(cur)
    else:
        prev = c.get(f"{y}Q{q - 1}")
        if not prev:
            return None
        s = {k: (cur.get(k) - prev.get(k)) if cur.get(k) is not None and prev.get(k) is not None else None for k in cur}
    rev = s.get("rev")
    s["gm"] = round(s["gross"] / rev * 100, 2) if rev and s.get("gross") is not None else None
    s["om"] = round(s["op"] / rev * 100, 2) if rev and s.get("op") is not None else None
    s["nonop_pct"] = round(s["nonop"] / s["pretax"] * 100, 2) if s.get("pretax") and s.get("nonop") is not None else None
    if s.get("eps") is not None:
        s["eps"] = round(s["eps"], 2)
    s["label"] = f"Q{q}"
    return s


def latest_single(db: dict, code: str, before: tuple[int, int] | None = None) -> dict | None:
    """最近一個可算出單季數字的季度（可限定早於 before）"""
    c = db.get(code) or {}
    labels = sorted((tuple(map(int, k.split("Q"))) for k in c if re.fullmatch(r"\d+Q\d", k)), reverse=True)
    for y, q in labels:
        if before and (y, q) >= before:
            continue
        s = single(db, code, y, q)
        if s:
            s["year"] = y
            return s
    return None
