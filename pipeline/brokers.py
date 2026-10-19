"""券商分點進出（券商買賣證券日報表）。

證交所：https://bsr.twse.com.tw/bshtm/ ，只提供「最近一個交易日」，每檔查詢都要輸入驗證碼，
這裡用 ddddocr 辨識，失敗就換一張重試。所以這支程式要在收盤後、隔日開盤前執行（排程 17:05）。

櫃買中心：查詢頁可能改用 Google reCAPTCHA，無法自動辨識。目前先嘗試舊版流程，
失敗時把網頁存到 data/state/brokers_debug/ 方便之後調整。

輸出：site/data/brokers/{日期}/{代號}.json
  {"date","code","name","market","close","prev_close","lots","inst",
   "branches": [[券商, 買進張, 賣出張, 買均, 賣均], ...]}
以及 site/data/brokers/{日期}/_status.json 記錄每檔成功或失敗原因。
"""
from __future__ import annotations

import csv
import io
import logging
import re
import time
from collections import defaultdict
from datetime import date
from urllib.parse import urljoin

import requests

from . import config
from .http import _TLSAdapter
from .util import write_json, read_json

log = logging.getLogger(__name__)
OUT = config.OUT_DIR / "brokers"
DEBUG_DIR = config.STATE_DIR / "brokers_debug"
U = config.URLS

_ocr = None


def _solver():
    """延遲載入 ddddocr；沒裝時回 None（分點功能停用，其他功能不受影響）"""
    global _ocr
    if _ocr is None:
        try:
            import ddddocr
            try:
                _ocr = ddddocr.DdddOcr(show_ad=False)
            except TypeError:
                _ocr = ddddocr.DdddOcr()
        except Exception as e:  # noqa: BLE001
            log.warning("驗證碼辨識套件無法載入（pip install ddddocr）：%s", e)
            _ocr = False
    return _ocr or None


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _TLSAdapter())
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                      "Accept-Language": "zh-TW,zh;q=0.9"})
    return s


def _debug(name: str, text: str) -> None:
    if config.BROKER_DEBUG:
        p = DEBUG_DIR / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text[:300_000], "utf-8")


def _hidden(html: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"<input[^>]+>", html, re.I):
        tag = m.group(0)
        if 'type="hidden"' not in tag.lower().replace("'", '"'):
            continue
        n = re.search(r'name=["\']([^"\']+)', tag)
        v = re.search(r'value=["\']([^"\']*)', tag)
        if n:
            out[n.group(1)] = v.group(1) if v else ""
    return out


def _clean_broker(s: str) -> str:
    """'9268凱基台北' / '1020合　　庫' → '凱基台北' / '合庫'"""
    s = re.sub(r"[\s　]+", "", str(s))
    m = re.match(r"^[0-9A-Z]{4}(.+)$", s)
    return m.group(1) if m else s


def parse_rows(text: str) -> list[tuple[str, float, int, int]]:
    """解析日報表 CSV（或已轉成逗號分隔的文字）：每列可能並排兩筆
    序號,證券商,成交單價,買進股數,賣出股數 → [(券商, 價格, 買股, 賣股)]"""
    out = []
    for row in csv.reader(io.StringIO(text)):
        cells = [c.strip().strip('="') for c in row]
        i = 0
        while i + 4 < len(cells):
            seq, br, px, b, s = cells[i:i + 5]
            if seq.isdigit() and br and re.fullmatch(r"\d+(\.\d+)?", px.replace(",", "")) \
                    and b.replace(",", "").isdigit() and s.replace(",", "").isdigit():
                out.append((_clean_broker(br), float(px.replace(",", "")), int(b.replace(",", "")), int(s.replace(",", ""))))
                i += 5
            else:
                i += 1
    return out


def aggregate(rows) -> list[list]:
    """逐價成交 → 每家券商 [名稱, 買張, 賣張, 買均, 賣均]，依成交量排序"""
    acc = defaultdict(lambda: [0, 0.0, 0, 0.0])
    for br, px, b, s in rows:
        a = acc[br]
        a[0] += b
        a[1] += b * px
        a[2] += s
        a[3] += s * px
    out = []
    for br, (b, bv, s, sv) in acc.items():
        out.append([br, round(b / 1000, 3), round(s / 1000, 3),
                    round(bv / b, 2) if b else None, round(sv / s, 2) if s else None])
    out.sort(key=lambda x: -(x[1] + x[2]))
    return out


# ------------------------------------------------------------------ 證交所

def fetch_twse(code: str, target: date) -> tuple[list | None, str]:
    """回傳 (逐價資料, 狀態說明)。逐價資料為 None 代表失敗。"""
    ocr = _solver()
    if not ocr:
        return None, "沒有驗證碼辨識套件"
    s = _session()
    last = ""
    for attempt in range(1, config.BROKER_RETRIES + 1):
        try:
            r = s.get(U["twse_bsr_menu"], timeout=config.HTTP_TIMEOUT)
            html = r.text
            m = re.search(r"""<img[^>]+src=['"]([^'"]*CaptchaImage[^'"]*)""", html, re.I)
            if not m:
                _debug("twse_menu.html", html)
                return None, "找不到驗證碼圖片（網頁可能改版）"
            img = s.get(urljoin(U["twse_bsr_menu"], m.group(1)), timeout=config.HTTP_TIMEOUT).content
            guess = re.sub(r"[^0-9A-Za-z]", "", ocr.classification(img) or "").upper()
            if len(guess) != 5:
                time.sleep(0.5)
                continue
            form = _hidden(html)
            form.update({"RadioButton_Normal": "RadioButton_Normal", "TextBox_Stkno": code,
                         "CaptchaControl1": guess, "btnOK": "查詢"})
            time.sleep(config.BROKER_DELAY)
            r = s.post(U["twse_bsr_menu"], data=form, timeout=config.HTTP_TIMEOUT)
            html = r.text
            err = re.search(r'id="Label_ErrorMsg"[^>]*>(.*?)</span>', html, re.S)
            err = re.sub(r"<[^>]+>", "", err.group(1)).strip() if err else ""
            if "驗證碼" in err:
                last = err
                continue
            if err and "HyperLink_DownloadCSV" not in html:
                return None, err  # 例如「查無資料」
            link = re.search(r'id="HyperLink_DownloadCSV"[^>]*href="([^"]+)"', html) or \
                re.search(r'href="([^"]+)"[^>]*id="HyperLink_DownloadCSV"', html)
            url = urljoin(U["twse_bsr_menu"], link.group(1).replace("&amp;", "&")) if link else \
                urljoin(U["twse_bsr_menu"], "bsContent.aspx?v=t")
            r = s.get(url, timeout=config.HTTP_TIMEOUT)
            text = r.content.decode("cp950", errors="replace")
            # 確認資料日期是今天（網站只保留最近一個交易日）
            ds = re.findall(r"(20\d\d)[/-](\d\d)[/-](\d\d)", text + html)
            if ds and not any(date(int(y), int(mo), int(d)) == target for y, mo, d in ds):
                return None, f"網站資料日期不是 {target}（{'-'.join(ds[0])}）"
            rows = parse_rows(text)
            if not rows:  # CSV 失敗時改讀 HTML 表格
                page = s.get(urljoin(U["twse_bsr_menu"], "bsContent.aspx"), timeout=config.HTTP_TIMEOUT).text
                cells = re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S)
                flat = "\n".join(",".join(re.sub(r"<[^>]+>|&nbsp;", "", c).strip()
                                          for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)) for tr in cells)
                rows = parse_rows(flat)
                if not rows:
                    _debug(f"twse_{code}.txt", text + "\n\n----- html -----\n" + page)
                    return None, "下載成功但解析不到資料（格式可能改版）"
            return rows, f"成功（第 {attempt} 次）"
        except requests.RequestException as e:
            last = f"連線錯誤：{e}"
            time.sleep(3)
    return None, f"驗證碼辨識失敗 {config.BROKER_RETRIES} 次" + (f"（{last}）" if last else "")


# ------------------------------------------------------------------ 櫃買

def fetch_tpex(code: str, target: date) -> tuple[list | None, str]:
    """櫃買查詢頁目前未確認可自動化：先探測頁面，存下來供調整。"""
    s = _session()
    try:
        r = s.get(U["tpex_bsr_menu"], timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as e:
        return None, f"連線錯誤：{e}"
    html = r.text
    if not (DEBUG_DIR / "tpex_menu.html").exists():
        _debug("tpex_menu.html", f"<!-- {r.status_code} {r.url} -->\n" + html)
    if re.search(r"recaptcha|g-recaptcha|turnstile", html, re.I):
        return None, "櫃買查詢頁使用 Google reCAPTCHA，無法自動抓取"
    return None, "櫃買分點尚未支援（已存下查詢頁供調整）"


# ------------------------------------------------------------------ 主流程

def build(d: date, daily: dict, inst: dict | None = None, only_twse_today: bool = True) -> dict:
    """抓當日所有漲停股的分點資料。daily 是 limitup.build_daily 的結果。"""
    folder = OUT / d.isoformat()
    status = read_json(folder / "_status.json", {}) or {}
    st = status.setdefault("stocks", {})
    for stock in daily.get("stocks", []):
        code = stock["code"]
        if st.get(code, {}).get("ok") and (folder / f"{code}.json").exists():
            continue
        fn = fetch_twse if stock["market"] == "TWSE" else fetch_tpex
        rows, msg = fn(code, d)
        st[code] = {"ok": rows is not None, "msg": msg, "market": stock["market"]}
        log.info("分點 %s %s：%s", code, stock["name"], msg)
        if rows is None:
            continue
        write_json(folder / f"{code}.json", {
            "date": d.isoformat(), "code": code, "name": stock["name"], "market": stock["market"],
            "close": stock["close"], "prev_close": stock["prev_close"], "lots": stock["lots"],
            "inst": (inst or {}).get(code) or stock.get("inst"), "branches": aggregate(rows),
        })
        time.sleep(config.BROKER_DELAY)
    status["date"] = d.isoformat()
    status["ok"] = sum(v["ok"] for v in st.values())
    status["total"] = len(st)
    write_json(folder / "_status.json", status)
    return status


def build_mock(d: date, daily: dict, seed: int = 7) -> None:
    """模擬資料：產生看起來合理的分點進出，供離線預覽前端"""
    import random
    names = ["凱基台北", "富邦", "元大", "摩根士丹利", "美商高盛亞", "港商野村", "星洲瑞銀", "摩根大通", "美林證券",
             "統一", "國票天祥", "永豐金敦北", "永昌麻豆", "永豐金", "國泰敦南", "凱基桃園", "新光", "永豐金中正",
             "兆豐台中", "新光台中", "台新敦南", "國泰館前", "康和仁愛", "合庫桃園", "第一金證券", "富邦建國",
             "國泰板橋", "國泰台中", "玉山台中", "凱基信義", "凱基城中", "元大內湖民", "台新", "華南永昌",
             "群益金鼎", "元富", "兆豐", "統一城中", "凱基松山", "富邦台北", "元大土城永寧", "犇亞", "宏遠"]
    folder = OUT / d.isoformat()
    st = {}
    for stock in daily.get("stocks", []):
        rnd = random.Random(f"{seed}-{d}-{stock['code']}")
        lots = max(stock["lots"], 50)
        pc, c = stock["prev_close"], stock["close"]
        lo = pc + (c - pc) * rnd.uniform(0.1, 0.6)
        pool = rnd.sample(names, min(len(names), rnd.randint(28, 42)))
        w = [(rnd.random() ** 3 if rnd.random() > .3 else 0, rnd.random() ** 3 if rnd.random() > .3 else 0) for _ in pool]
        sb = sum(x[0] for x in w) or 1
        ss = sum(x[1] for x in w) or 1
        rows = []
        for n, (wb, ws) in zip(pool, w):
            b, s = round(lots * wb / sb), round(lots * ws / ss)
            if b + s == 0:
                continue
            px = lambda: round(c - (c - lo) * rnd.random() ** 1.6, 2)  # noqa: E731
            rows.append([n, b, s, px() if b else None, px() if s else None])
        rows.sort(key=lambda x: -(x[1] + x[2]))
        inst = stock.get("inst") or {"f": rnd.randint(-lots // 8, lots // 4), "t": 0, "d": rnd.randint(-lots // 30, lots // 20)}
        write_json(folder / f"{stock['code']}.json", {
            "date": d.isoformat(), "code": stock["code"], "name": stock["name"], "market": stock["market"],
            "close": c, "prev_close": pc, "lots": stock["lots"], "inst": inst, "branches": rows})
        st[stock["code"]] = {"ok": True, "msg": "模擬資料", "market": stock["market"]}
    write_json(folder / "_status.json", {"date": d.isoformat(), "stocks": st, "ok": len(st), "total": len(st)})
