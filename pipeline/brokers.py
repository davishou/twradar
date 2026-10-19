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
    m = re.match(r"^[0-9A-Za-z]{4}(.+)$", s)
    return m.group(1) if m else s


def decode(raw: bytes) -> str:
    """報表可能是 UTF-8（含 BOM）或 Big5，先試 UTF-8，失敗再用 cp950"""
    for enc in ("utf-8-sig", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def site_dates(text: str) -> set[date]:
    """抓出網頁或報表裡出現的日期：2026/10/19、2026-10-19、115/10/19、115年10月19日"""
    out = set()
    for y, m, d in re.findall(r"(20\d\d)\s*[/\-年]\s*(\d{1,2})\s*[/\-月]\s*(\d{1,2})", text):
        try:
            out.add(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    for y, m, d in re.findall(r"(?<!\d)(1\d\d)\s*[/年]\s*(\d{1,2})\s*[/月]\s*(\d{1,2})", text):
        try:
            out.add(date(int(y) + 1911, int(m), int(d)))
        except ValueError:
            pass
    return out


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
    """逐價成交 → 每家券商 [名稱, 買張, 賣張, 買均, 賣均, 買價標準差, 賣價標準差]，依成交量排序。
    標準差表示這家券商買（賣）的價格分散程度：0 代表都在同一價位成交。"""
    acc = defaultdict(lambda: [0, 0.0, 0.0, 0, 0.0, 0.0])
    for br, px, b, s in rows:
        a = acc[br]
        a[0] += b
        a[1] += b * px
        a[2] += b * px * px
        a[3] += s
        a[4] += s * px
        a[5] += s * px * px
    out = []
    for br, (b, bv, bq, s, sv, sq) in acc.items():
        bm, sm = (bv / b if b else None), (sv / s if s else None)
        bsd = (max(bq / b - bm * bm, 0) ** .5) if b else None
        ssd = (max(sq / s - sm * sm, 0) ** .5) if s else None
        out.append([br, round(b / 1000, 3), round(s / 1000, 3),
                    round(bm, 2) if b else None, round(sm, 2) if s else None,
                    round(bsd, 2) if b else None, round(ssd, 2) if s else None])
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
            text = decode(r.content)
            # 報表本身沒有日期；若網頁上有日期就比對，沒有就交給 build() 用價量比對
            found = site_dates(text + html)
            if found and target not in found:
                return None, f"網站資料日期是 {sorted(found)[-1]}，不是 {target}"
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
    r.encoding = "utf-8"
    html = r.text
    if not (DEBUG_DIR / "tpex_menu.html").exists():
        _debug("tpex_menu.html", f"<!-- {r.status_code} {r.url} -->\n" + html)
    if re.search(r"recaptcha|g-recaptcha|turnstile", html, re.I):
        return None, "櫃買查詢頁有 Cloudflare 真人驗證，無法自動抓取上櫃分點"
    return None, "櫃買分點尚未支援（已存下查詢頁供調整）"


# ------------------------------------------------------------------ 主流程

def matches_day(rows, t: dict) -> str:
    """確認逐價資料屬於 t 這一天：成交價都在當天高低價之間，買進總量與當天成交量相符。
    回傳空字串代表通過，否則回傳原因。"""
    hi, lo, lots = t.get("high"), t.get("low"), t.get("lots") or 0
    # 報表含零股成交，零股的價格可能超出整股高低價，所以只用 1000 股以上的列比對
    board = [(px, b, s) for _, px, b, s in rows if b >= 1000 or s >= 1000]
    if hi and lo and board:
        out = sum(b + s for px, b, s in board if px > hi + 1e-6 or px < lo - 1e-6)
        tot = sum(b + s for _, b, s in board) or 1
        if out / tot > 0.02:
            return f"有 {out / tot:.0%} 的成交價超出當天 {lo}~{hi}，可能不是同一天的資料"
    buy = sum(b for _, _, b, _ in rows) / 1000
    if lots >= 20 and abs(buy - lots) / lots > 0.10:
        return f"報表買進合計 {buy:,.0f} 張與當天成交量 {lots:,} 張不符，可能不是同一天的資料"
    return ""


def target(q: dict, name: str | None = None, inst: dict | None = None, role: str = "limit") -> dict:
    """把行情整理成要抓分點的股票資訊。role：limit＝當日漲停、next＝昨日漲停（看隔日動向）"""
    from .util import limit_up
    return {"code": q["code"], "name": name or q["name"], "market": q["market"], "close": q["close"],
            "prev_close": q["prev_close"], "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
            "avg": q.get("avg"), "lots": int(q.get("volume", 0)) // 1000, "limit": limit_up(q["prev_close"]),
            "inst": inst, "role": role}


def _write(folder, d: date, t: dict, branches: list) -> None:
    write_json(folder / f"{t['code']}.json", {
        "date": d.isoformat(), **{k: t[k] for k in ("code", "name", "market", "close", "prev_close", "open", "high",
                                                   "low", "avg", "lots", "limit", "inst", "role")},
        "branches": branches})


def build(d: date, targets: list[dict]) -> dict:
    """抓 targets 每一檔的分點資料（證交所網站只保留最近一個交易日，所以 d 必須是今天的交易日）。"""
    folder = OUT / d.isoformat()
    status = read_json(folder / "_status.json", {}) or {}
    st = status.setdefault("stocks", {})
    for t in targets:
        code = t["code"]
        if st.get(code, {}).get("ok") and (folder / f"{code}.json").exists():
            continue
        fn = fetch_twse if t["market"] == "TWSE" else fetch_tpex
        rows, msg = fn(code, d)
        if rows is not None:
            bad = matches_day(rows, t)
            if bad:
                rows, msg = None, bad
        st[code] = {"ok": rows is not None, "msg": msg, "market": t["market"], "role": t["role"]}
        log.info("分點 %s %s：%s", code, t["name"], msg)
        if rows is None:
            continue
        _write(folder, d, t, aggregate(rows))
        time.sleep(config.BROKER_DELAY)
    status["date"] = d.isoformat()
    status["ok"] = sum(v["ok"] for v in st.values())
    status["total"] = len(st)
    write_json(folder / "_status.json", status)
    return status


NAMES = ["凱基台北", "富邦", "元大", "摩根士丹利", "美商高盛亞", "港商野村", "星洲瑞銀", "摩根大通", "美林證券",
         "統一", "國票天祥", "永豐金敦北", "永昌麻豆", "永豐金", "國泰敦南", "凱基桃園", "新光", "永豐金中正",
         "兆豐台中", "新光台中", "台新敦南", "國泰館前", "康和仁愛", "合庫桃園", "第一金證券", "富邦建國",
         "國泰板橋", "國泰台中", "玉山台中", "凱基信義", "凱基城中", "元大內湖民", "台新", "華南永昌",
         "群益金鼎", "元富", "兆豐", "統一城中", "凱基松山", "富邦台北", "元大土城永寧", "犇亞", "宏遠"]


def build_mock(d: date, targets: list[dict], prev: date | None = None, seed: int = 7) -> None:
    """模擬資料：產生看起來合理的分點進出（隔日股會讓前一天的大買家賣出），供離線預覽前端"""
    import random
    folder = OUT / d.isoformat()
    st = {}
    for t in targets:
        rnd = random.Random(f"{seed}-{d}-{t['code']}")
        lots = max(t["lots"], 50)
        lo = t.get("low") or t["prev_close"]
        hi = t.get("high") or t["close"]
        if t["role"] == "limit":
            lo = t["prev_close"] + (t["close"] - t["prev_close"]) * rnd.uniform(0.1, 0.6)
        pool = rnd.sample(NAMES, min(len(NAMES), rnd.randint(28, 42)))
        bias = {}
        if t["role"] == "next" and prev:
            old = read_json(OUT / prev.isoformat() / f"{t['code']}.json")
            if old:
                buyers = sorted(old["branches"], key=lambda x: -(x[1] - x[2]))[:15]
                for x in buyers:
                    if rnd.random() < .7:
                        bias[x[0]] = max(x[1] - x[2], 0)
                pool = list(dict.fromkeys(list(bias) + pool))
        w = []
        for n in pool:
            wb = rnd.random() ** 3 if rnd.random() > .3 else 0
            ws = rnd.random() ** 3 if rnd.random() > .3 else 0
            if n in bias:
                ws = bias[n] / lots * rnd.uniform(.6, 1.6)
                wb = wb * .3
            w.append((wb, ws))
        sb = sum(x[0] for x in w) or 1
        ss = sum(x[1] for x in w) or 1
        rows = []
        for n, (wb, ws) in zip(pool, w):
            b, s = round(lots * wb / sb), round(lots * ws / ss)
            if b + s == 0:
                continue
            px = lambda: round(hi - (hi - lo) * rnd.random() ** 1.4, 2)  # noqa: E731
            rows.append([n, b, s, px() if b else None, px() if s else None,
                         round(rnd.random() * (hi - lo) * .2, 2) if b else None, round(rnd.random() * (hi - lo) * .2, 2) if s else None])
        rows.sort(key=lambda x: -(x[1] + x[2]))
        t = dict(t, inst=t.get("inst") or {"f": rnd.randint(-lots // 8, lots // 4), "t": 0, "d": rnd.randint(-lots // 30, lots // 20)})
        _write(folder, d, t, rows)
        st[t["code"]] = {"ok": True, "msg": "模擬資料", "market": t["market"], "role": t["role"]}
    write_json(folder / "_status.json", {"date": d.isoformat(), "stocks": st, "ok": len(st), "total": len(st)})
