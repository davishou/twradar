"""國際行情：商品（金銀油銅鐵礦、農產品）、各國指數、匯率利率的全部歷史與現價。

資料源：Yahoo Finance 圖表介面（不需金鑰；商品是期貨連續月，報價延遲約 10~20 分鐘）。
Yahoo 沒有的指數：台灣櫃買、滬深300、泰國、菲律賓、波蘭、沙烏地用鉅亨網（cnyes:）；
俄羅斯用莫斯科交易所官方 ISS（moex:）；越南用 DNSE／SSI 券商介面（vn:）；挪威用 Euronext 官方歷史檔（euronext:）。
第一次抓某個代號時一次拿全部歷史，之後每次只補最近幾天。
選用：GitHub Secret FRED_API_KEY（美國聖路易聯準銀行，免費申請）有設時，用官方資料核對收盤價。

存放：data/archive/mkt/<id>/<年>.csv（純文字 CSV，每年一檔；只有今年的檔會變動，git 存差異很省空間）
網站：部署時 `python -m pipeline.markets site` 產生 site/data/mkt.json（總表）與 site/data/mkt/<id>.json（全歷史），不進 git。

  python -m pipeline.markets update      抓新資料（缺的代號自動補全部歷史）
  python -m pipeline.markets site        產生網站 JSON
  python -m pipeline.markets mock        產生模擬資料（本機預覽用）
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone

from . import config, store
from .util import now_tw

log = logging.getLogger(__name__)

MKT_DIR = config.DATA_DIR / "archive" / "mkt"
OUT = config.OUT_DIR / "mkt"
YAHOO = "https://query{n}.finance.yahoo.com/v8/finance/chart/{sym}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
EPOCH_1900 = -2208988800

# (id, Yahoo 代號, 名稱, 單位)；分組順序就是網頁顯示順序
GROUPS = [
    ("貴金屬", [
        ("gold", "GC=F", "黃金", "美元/盎司"),
        ("silver", "SI=F", "白銀", "美元/盎司"),
        ("platinum", "PL=F", "白金", "美元/盎司"),
        ("palladium", "PA=F", "鈀金", "美元/盎司"),
    ]),
    ("能源", [
        ("wti", "CL=F", "WTI 原油", "美元/桶"),
        ("brent", "BZ=F", "布蘭特原油", "美元/桶"),
        ("natgas", "NG=F", "天然氣", "美元/百萬英熱單位"),
        ("gasoline", "RB=F", "汽油 RBOB", "美元/加侖"),
        ("heatoil", "HO=F", "熱燃油", "美元/加侖"),
    ]),
    ("工業金屬", [
        ("copper", "HG=F", "銅", "美元/磅"),
        ("ironore", "TIO=F", "鐵礦石 62%", "美元/噸"),
        ("hrc", "HRC=F", "熱軋鋼捲", "美元/短噸"),
        ("aluminum", "ALI=F", "鋁", "美元/噸"),
    ]),
    ("農產品", [
        ("corn", "ZC=F", "玉米", "美分/英斗"),
        ("wheat", "ZW=F", "小麥", "美分/英斗"),
        ("kcwheat", "KE=F", "硬紅冬麥", "美分/英斗"),
        ("soybean", "ZS=F", "黃豆", "美分/英斗"),
        ("soyoil", "ZL=F", "黃豆油", "美分/磅"),
        ("soymeal", "ZM=F", "黃豆粉", "美元/短噸"),
        ("oats", "ZO=F", "燕麥", "美分/英斗"),
        ("rice", "ZR=F", "稻米", "美元/英擔"),
        ("coffee", "KC=F", "咖啡", "美分/磅"),
        ("cocoa", "CC=F", "可可", "美元/噸"),
        ("sugar", "SB=F", "原糖", "美分/磅"),
        ("cotton", "CT=F", "棉花", "美分/磅"),
        ("oj", "OJ=F", "柳橙汁", "美分/磅"),
    ]),
    ("畜產・林產", [
        ("cattle", "LE=F", "活牛", "美分/磅"),
        ("feeder", "GF=F", "育肥牛", "美分/磅"),
        ("hogs", "HE=F", "瘦豬", "美分/磅"),
        ("lumber", "LBR=F", "木材", "美元/千板呎"),
    ]),
    ("美國股市", [
        ("spx", "^GSPC", "S&P 500", "點"),
        ("dji", "^DJI", "道瓊工業", "點"),
        ("nasdaq", "^IXIC", "那斯達克", "點"),
        ("sox", "^SOX", "費城半導體", "點"),
        ("rut", "^RUT", "羅素 2000", "點"),
        ("nya", "^NYA", "紐約綜合", "點"),
    ]),
    ("美洲股市", [
        ("tsx", "^GSPTSE", "加拿大 S&P/TSX", "點"),
        ("bvsp", "^BVSP", "巴西 Bovespa", "點"),
        ("mxx", "^MXX", "墨西哥 IPC", "點"),
        ("merv", "^MERV", "阿根廷 Merval", "點"),
    ]),
    ("東亞股市", [
        ("taiex", "^TWII", "台灣加權", "點"),
        ("otc", "cnyes:TWS:OTC01:INDEX", "台灣櫃買指數", "點"),
        ("n225", "^N225", "日經 225", "點"),
        ("kospi", "^KS11", "韓國綜合", "點"),
        ("hsi", "^HSI", "香港恆生", "點"),
        ("hscei", "^HSCE", "恆生國企", "點"),
        ("csi300", "cnyes:GI:CSI300:INDEX", "滬深 300", "點"),
        ("sse", "000001.SS", "上證綜合", "點"),
        ("szse", "399001.SZ", "深證成指", "點"),
    ]),
    ("南亞・東南亞・大洋洲", [
        ("sensex", "^BSESN", "印度 Sensex", "點"),
        ("nifty", "^NSEI", "印度 Nifty 50", "點"),
        ("sti", "^STI", "新加坡海峽時報", "點"),
        ("klci", "^KLSE", "馬來西亞 KLCI", "點"),
        ("jkse", "^JKSE", "印尼綜合", "點"),
        ("set", "cnyes:GI:SET:INDEX", "泰國 SET", "點"),
        ("psei", "cnyes:GI:PCOMP:INDEX", "菲律賓 PSEi", "點"),
        ("vni", "vn:VNINDEX", "越南 VN 指數", "點"),
        ("asx", "^AXJO", "澳洲 ASX 200", "點"),
        ("nz50", "^NZ50", "紐西蘭 NZX 50", "點"),
    ]),
    ("歐洲股市", [
        ("dax", "^GDAXI", "德國 DAX", "點"),
        ("ftse", "^FTSE", "英國富時 100", "點"),
        ("cac", "^FCHI", "法國 CAC 40", "點"),
        ("sx5e", "^STOXX50E", "歐洲斯托克 50", "點"),
        ("aex", "^AEX", "荷蘭 AEX", "點"),
        ("ibex", "^IBEX", "西班牙 IBEX 35", "點"),
        ("ftsemib", "FTSEMIB.MI", "義大利 FTSE MIB", "點"),
        ("smi", "^SSMI", "瑞士 SMI", "點"),
        ("bel20", "^BFX", "比利時 BEL 20", "點"),
        ("atx", "^ATX", "奧地利 ATX", "點"),
        ("psi", "PSI20.LS", "葡萄牙 PSI", "點"),
        ("iseq", "^ISEQ", "愛爾蘭 ISEQ", "點"),
        ("omxs30", "^OMX", "瑞典 OMX 30", "點"),
        ("omxc25", "^OMXC25", "丹麥 OMX 25", "點"),
        ("omxh25", "^OMXH25", "芬蘭 OMX 25", "點"),
        ("osebx", "euronext:NO0007035327-XOSL", "挪威 OSEBX", "點"),
        ("wig", "cnyes:GI:WIG:INDEX", "波蘭 WIG", "點"),
        ("imoex", "moex:IMOEX", "俄羅斯 MOEX（盧布）", "點"),
        ("rts", "moex:RTSI", "俄羅斯 RTS（美元）", "點"),
    ]),
    ("中東・非洲", [
        ("bist100", "XU100.IS", "土耳其 BIST 100", "點"),
        ("ta125", "^TA125.TA", "以色列 TA-125", "點"),
        ("tasi", "cnyes:GI:TASI:INDEX", "沙烏地 Tadawul", "點"),
        ("jse", "^J203.JO", "南非全股", "點"),
    ]),
    ("匯率", [
        ("dxy", "DX-Y.NYB", "美元指數", "點"),
        ("usdtwd", "TWD=X", "美元/台幣", "台幣"),
        ("usdjpy", "JPY=X", "美元/日圓", "日圓"),
        ("usdcny", "CNY=X", "美元/人民幣", "人民幣"),
        ("usdkrw", "KRW=X", "美元/韓元", "韓元"),
        ("usdhkd", "HKD=X", "美元/港幣", "港幣"),
        ("usdsgd", "SGD=X", "美元/新加坡幣", "新加坡幣"),
        ("usdinr", "INR=X", "美元/印度盧比", "盧比"),
        ("usdthb", "THB=X", "美元/泰銖", "泰銖"),
        ("usdidr", "IDR=X", "美元/印尼盾", "印尼盾"),
        ("usdmyr", "MYR=X", "美元/馬幣", "令吉"),
        ("usdphp", "PHP=X", "美元/菲律賓披索", "披索"),
        ("usdvnd", "VND=X", "美元/越南盾", "越南盾"),
        ("eurusd", "EURUSD=X", "歐元/美元", "美元"),
        ("gbpusd", "GBPUSD=X", "英鎊/美元", "美元"),
        ("audusd", "AUDUSD=X", "澳幣/美元", "美元"),
        ("nzdusd", "NZDUSD=X", "紐幣/美元", "美元"),
        ("usdchf", "CHF=X", "美元/瑞郎", "瑞郎"),
        ("usdcad", "CAD=X", "美元/加幣", "加幣"),
        ("eurjpy", "EURJPY=X", "歐元/日圓", "日圓"),
        ("usdbrl", "BRL=X", "美元/巴西幣", "雷亞爾"),
        ("usdmxn", "MXN=X", "美元/墨西哥披索", "披索"),
        ("usdzar", "ZAR=X", "美元/南非幣", "蘭特"),
        ("usdtry", "TRY=X", "美元/土耳其里拉", "里拉"),
        ("usdrub", "RUB=X", "美元/盧布", "盧布"),
    ]),
    ("利率・波動率", [
        ("us13w", "^IRX", "美國 13 週國庫券", "%"),
        ("us5y", "^FVX", "美國 5 年債殖利率", "%"),
        ("us10y", "^TNX", "美國 10 年債殖利率", "%"),
        ("us30y", "^TYX", "美國 30 年債殖利率", "%"),
        ("vix", "^VIX", "VIX 恐慌指數", "點"),
        ("gvz", "^GVZ", "黃金波動率", "點"),
        ("ovx", "^OVX", "原油波動率", "點"),
    ]),
    ("加密貨幣", [
        ("btc", "BTC-USD", "比特幣", "美元"),
        ("eth", "ETH-USD", "以太幣", "美元"),
    ]),
]
# 網頁的大分類（使用者要求：金屬放一起、各國股市一個區塊、匯率獨立、利率波動率加密放一起）；細分類顯示在名稱旁
COARSE = {"貴金屬": "金屬", "工業金屬": "金屬", "能源": "能源", "農產品": "農畜產", "畜產・林產": "農畜產",
          "美國股市": "全球股市", "美洲股市": "全球股市", "東亞股市": "全球股市", "南亞・東南亞・大洋洲": "全球股市",
          "歐洲股市": "全球股市", "中東・非洲": "全球股市", "匯率": "匯率", "利率・波動率": "利率・波動率・加密", "加密貨幣": "利率・波動率・加密"}
SUBNAME = {"美國股市": "美國", "美洲股市": "美洲", "東亞股市": "東亞", "南亞・東南亞・大洋洲": "南亞・東南亞・大洋洲", "歐洲股市": "歐洲",
           "中東・非洲": "中東・非洲", "利率・波動率": "利率・波動率", "加密貨幣": "加密貨幣"}
SERIES = {s[0]: {"id": s[0], "sym": s[1], "name": s[2], "unit": s[3], "group": g} for g, items in GROUPS for s in items}

# FRED 對照（選用核對）：id → (FRED 代號, 容許的中位數誤差, 是否用絕對差)
# 原油 FRED 是現貨、Yahoo 是近月期貨，本來就有小差距；匯率 FRED 是紐約中午價
FRED = {
    "wti": ("DCOILWTICO", 0.03, False), "brent": ("DCOILBRENTEU", 0.04, False),
    "us10y": ("DGS10", 0.05, True), "spx": ("SP500", 0.003, False), "dji": ("DJIA", 0.003, False),
    "nasdaq": ("NASDAQCOM", 0.003, False), "vix": ("VIXCLS", 0.02, False),
    "usdtwd": ("DEXTAUS", 0.01, False), "usdjpy": ("DEXJPUS", 0.01, False),
    "usdcny": ("DEXCHUS", 0.01, False), "eurusd": ("DEXUSEU", 0.01, False),
    "us5y": ("DGS5", 0.05, True), "us30y": ("DGS30", 0.05, True), "usdkrw": ("DEXKOUS", 0.01, False), "gbpusd": ("DEXUSUK", 0.01, False),
    "usdinr": ("DEXINUS", 0.01, False), "usdcad": ("DEXCAUS", 0.01, False), 
}

FIELDS = ("date", "open", "high", "low", "close", "volume")


# ---------------- 存取 ----------------
def _num(x, nd=6):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    if v == 0:
        return 0.0
    # 保留 7 位有效數字（指數兩位小數、匯率四位小數都夠）
    d = max(0, min(nd, 6 - int(math.floor(math.log10(abs(v))))))
    return round(v, d)


def load(sid: str) -> dict[str, list]:
    """回傳 {日期: [開, 高, 低, 收, 量]}"""
    out: dict[str, list] = {}
    d = MKT_DIR / sid
    if not d.exists():
        return out
    for f in sorted(d.glob("*.csv")):
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out[r["date"]] = [_num(r.get(k)) for k in FIELDS[1:]]
    return out


def save(sid: str, rows: dict[str, list]) -> None:
    by_year: dict[str, list] = {}
    for d in sorted(rows):
        by_year.setdefault(d[:4], []).append([d, *rows[d]])
    d = MKT_DIR / sid
    d.mkdir(parents=True, exist_ok=True)
    for y, rs in by_year.items():
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(FIELDS)
        for r in rs:
            w.writerow(["" if v is None else (int(v) if i == 5 and v is not None else v) for i, v in enumerate(r)])
        f = d / f"{y}.csv"
        txt = buf.getvalue()
        if not f.exists() or f.read_text(encoding="utf-8") != txt:
            f.write_text(txt, encoding="utf-8")


# ---------------- Yahoo ----------------
def _session():
    from .http import session
    s = session()
    return s


def fetch_yahoo(sym: str, start: int | None = None, rng: str | None = None) -> tuple[dict, dict] | None:
    """回傳 (rows, meta)。start=None 且 rng=None 代表全部歷史。"""
    params = {"interval": "1d", "includePrePost": "false", "events": "div,split"}
    if rng:
        params["range"] = rng
    else:
        params["period1"] = str(EPOCH_1900 if start is None else start)
        params["period2"] = str(int(time.time()) + 86400)
    s = _session()
    for n in (1, 2):
        try:
            r = s.get(YAHOO.format(n=n, sym=sym), params=params, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=40)
            if r.status_code != 200:
                log.warning("Yahoo %s query%d：HTTP %s", sym, n, r.status_code)
                time.sleep(2)
                continue
            res = (r.json().get("chart") or {}).get("result") or []
            if not res:
                continue
            res = res[0]
            meta = res.get("meta") or {}
            ts = res.get("timestamp") or []
            q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
            off = int(meta.get("gmtoffset") or 0)
            rows: dict[str, list] = {}
            for i, t in enumerate(ts):
                c = _num((q.get("close") or [None] * len(ts))[i])
                if c is None:
                    continue
                d = datetime.fromtimestamp(t + off, tz=timezone.utc).date().isoformat()
                g = lambda k: _num((q.get(k) or [None] * len(ts))[i])  # noqa: E731
                rows[d] = [g("open"), g("high"), g("low"), c, g("volume")]
            return rows, meta
        except Exception as e:  # noqa: BLE001
            log.warning("Yahoo %s query%d 失敗：%s", sym, n, e)
            time.sleep(2)
    return None


CNYES = "https://ws.api.cnyes.com/ws/api/v1/charting/history"


def fetch_cnyes(sym: str, since: str | None = None, max_pages: int = 15) -> tuple[dict, dict] | None:
    """鉅亨網日線：每次約回 1,250 天（新到舊），往前翻頁直到沒資料或早於 since。"""
    s = _session()
    rows: dict[str, list] = {}
    frm = int(time.time()) + 86400
    for _ in range(max_pages):
        d = None
        for attempt in range(3):            # 中途某頁失敗就重試，避免歷史只抓到一半
            try:
                r = s.get(CNYES, params={"resolution": "D", "symbol": sym, "from": frm, "to": 0},
                          headers={"User-Agent": UA, "Referer": "https://www.cnyes.com/"}, timeout=40)
                if r.status_code == 200:
                    d = r.json().get("data") or {}
                    break
                log.warning("鉅亨 %s：HTTP %s", sym, r.status_code)
            except Exception as e:  # noqa: BLE001
                log.warning("鉅亨 %s 失敗：%s", sym, e)
            time.sleep(3 * (attempt + 1))
        if d is None:
            break
        t = d.get("t") or []
        if not t:
            break
        col = lambda k: d.get(k) or [None] * len(t)  # noqa: E731
        for i, ts in enumerate(t):
            c = _num(col("c")[i])
            if c is None:
                continue
            rows[datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()] = [_num(col("o")[i]), _num(col("h")[i]), _num(col("l")[i]), c, _num(col("v")[i])]
        frm = min(t) - 1
        if since and min(rows) <= since:
            break
        time.sleep(0.4)
    return (rows, {"source": "cnyes"}) if rows else None



def fetch_moex(sec: str, since: str | None = None) -> tuple[dict, dict] | None:
    """莫斯科交易所官方 ISS：每頁 100 筆，從 since（沒有就從頭）往後翻。"""
    s = _session()
    rows: dict[str, list] = {}
    start = 0
    while start < 20000:
        try:
            r = s.get(f"https://iss.moex.com/iss/history/engines/stock/markets/index/securities/{sec}.json",
                      params={"from": since or "1990-01-01", "start": start, "iss.meta": "off", "history.columns": "TRADEDATE,OPEN,HIGH,LOW,CLOSE"},
                      headers={"User-Agent": UA}, timeout=40)
            data = (r.json().get("history") or {}).get("data") or []
        except Exception as e:  # noqa: BLE001
            log.warning("MOEX %s 失敗：%s", sec, e)
            break
        if not data:
            break
        for d, o, h, l, c in data:
            if _num(c) is not None:
                rows[d] = [_num(o), _num(h), _num(l), _num(c), None]
        start += len(data)
        time.sleep(0.2)
    return (rows, {"source": "moex"}) if rows else None


def fetch_vn(sym: str) -> tuple[dict, dict] | None:
    """越南：DNSE（entrade）圖表介面，失敗改 SSI。時間戳換成越南時間（UTC+7）取日期。"""
    s = _session()
    now = int(time.time()) + 86400
    for url, params in (("https://services.entrade.com.vn/chart-api/v2/ohlcs/index", {"from": 0, "to": now, "symbol": sym, "resolution": "1D"}),
                        ("https://iboard-api.ssi.com.vn/statistics/charts/history", {"resolution": "1D", "symbol": sym, "from": 946684800, "to": now})):
        try:
            j = s.get(url, params=params, headers={"User-Agent": UA}, timeout=60).json()
            d = j.get("data") if isinstance(j.get("data"), dict) else j
            t = d.get("t") or []
        except Exception as e:  # noqa: BLE001
            log.warning("越南 %s（%s）失敗：%s", sym, url, e)
            continue
        if not t:
            continue
        col = lambda k: d.get(k) or [None] * len(t)  # noqa: E731
        rows = {}
        for i, ts in enumerate(t):
            c = _num(col("c")[i])
            if c is not None:
                rows[datetime.fromtimestamp(int(ts) + 7 * 3600, tz=timezone.utc).date().isoformat()] = [_num(col("o")[i]), _num(col("h")[i]), _num(col("l")[i]), c, _num(col("v")[i])]
        if rows:
            return rows, {"source": url}
    return None


def fetch_euronext(code: str, since: str | None = None) -> tuple[dict, dict] | None:
    """Euronext 官方歷史檔（CSV，分號分隔，日期 dd/mm/yyyy）"""
    try:
        r = _session().get(f"https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax/{code}",
                           params={"format": "csv", "decimal_separator": ".", "date_form": "d/m/Y", "op": "", "adjusted": "Y", "base100": "",
                                   "startdate": since or "1990-01-01", "enddate": date.today().isoformat()},
                           headers={"User-Agent": UA}, timeout=60)
        lines = r.text.lstrip("\ufeff").splitlines()
    except Exception as e:  # noqa: BLE001
        log.warning("Euronext %s 失敗：%s", code, e)
        return None
    rows = {}
    for ln in lines:
        f = ln.split(";")
        if len(f) < 6 or f[0].count("/") != 2:
            continue
        dd, mm, yy = f[0].split("/")
        c = _num(f[5])
        if c is not None:
            rows[f"{yy}-{mm}-{dd}"] = [_num(f[1]), _num(f[2]), _num(f[3]), c, None]
    return (rows, {"source": "euronext"}) if rows else None


def _check(sid: str, rows: dict[str, list]) -> list[str]:
    """可疑資料：單日跳動很大又立刻彈回（常見的錯誤報價）。只記錄不刪除，避免把真實行情（例如 2020/4 油價負值）刪掉。"""
    ds = sorted(rows)
    lim = 0.3 if sid in ("btc", "natgas", "vix") else 0.2
    bad = []
    for a, b, c in zip(ds, ds[1:], ds[2:]):
        x, y, z = rows[a][3], rows[b][3], rows[c][3]
        if not x or not y or not z or x <= 0 or y <= 0 or z <= 0:
            continue
        r1, r2 = y / x - 1, z / y - 1
        if abs(r1) > lim and abs(r2) > lim * 0.7 and r1 * r2 < 0:
            bad.append(b)
    return bad[-20:]


def update(full: bool = False, quick: bool = False, only: list[str] | None = None) -> dict:
    """quick=True：只抓最近 5 天（盤中更新現價用）。缺歷史的代號一律抓全部。"""
    st = store.state("markets", {}) or {}
    live = st.setdefault("live", {})
    info = st.setdefault("info", {})
    ok = fail = 0
    for sid, s in SERIES.items():
        if only and sid not in only:
            continue
        rows = load(sid)
        if quick and rows and s["sym"].split(":")[0] in ("moex", "vn", "euronext"):
            continue                       # 這幾個來源每晚更新收盤就好，盤中不重抓
        since = None if (full or not rows) else (date.fromisoformat(max(rows)) - timedelta(days=14)).isoformat()
        if s["sym"].startswith("moex:"):
            got = fetch_moex(s["sym"][5:], since)
        elif s["sym"].startswith("vn:"):
            got = fetch_vn(s["sym"][3:])
        elif s["sym"].startswith("euronext:"):
            got = fetch_euronext(s["sym"][9:], since)
        elif s["sym"].startswith("cnyes:"):
            got = fetch_cnyes(s["sym"][6:], since=None if (full or not rows) else (date.fromisoformat(max(rows)) - timedelta(days=14)).isoformat(),
                              max_pages=1 if quick and rows else 15)
        elif full or not rows:
            got = fetch_yahoo(s["sym"])
            if got and len(got[0]) < 30:          # 少數代號用起始日查只回一天，改用 range=max
                time.sleep(0.6)
                alt = fetch_yahoo(s["sym"], rng="max")
                if alt and len(alt[0]) > len(got[0]):
                    got = alt
        elif quick:
            got = fetch_yahoo(s["sym"], rng="5d")
        else:
            last = max(rows)
            got = fetch_yahoo(s["sym"], start=int(datetime.fromisoformat(last).replace(tzinfo=timezone.utc).timestamp()) - 14 * 86400)
        time.sleep(0.4)
        if not got or not got[0]:
            fail += 1
            info.setdefault(sid, {})["error"] = now_tw().strftime("%Y-%m-%d %H:%M") + " 抓取失敗"
            continue
        new, meta = got
        before = len(rows)
        rows.update(new)
        save(sid, rows)
        ok += 1
        px, t = _num(meta.get("regularMarketPrice")), meta.get("regularMarketTime")
        if px is not None and t:
            live[sid] = {"price": px, "time": datetime.fromtimestamp(int(t), tz=timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
                         "state": meta.get("marketState") or ""}
        i = info.setdefault(sid, {})
        i.pop("error", None)
        i.update({"currency": meta.get("currency"), "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
                  "first": min(rows), "n": len(rows), "suspect": _check(sid, rows)})
        if len(rows) > before:
            log.info("%s %s：新增 %d 天（共 %d 天，%s 起）", sid, s["sym"], len(rows) - before, len(rows), min(rows))
    st["updated"] = now_tw().strftime("%Y-%m-%d %H:%M")
    st["ok"], st["fail"] = ok, fail
    if not quick:
        try:
            st["fred"] = verify_fred()
            chk = verify_tpex()
            if chk:
                st["fred"].setdefault("items", {})["otc"] = chk
        except Exception as e:  # noqa: BLE001
            log.warning("FRED 核對失敗：%s", e)
    store.save_state("markets", st)
    log.info("國際行情：成功 %d、失敗 %d", ok, fail)
    return st


def maybe_quick(every_min: int = 30) -> None:
    """給每 5 分鐘的公告工作用：距離上次超過 every_min 分鐘才更新一次現價"""
    st = store.state("markets", {}) or {}
    last = st.get("updated")
    if last and (now_tw().replace(tzinfo=None) - datetime.strptime(last, "%Y-%m-%d %H:%M")).total_seconds() < every_min * 60:
        return
    update(quick=True)


def verify_fred() -> dict:
    """用 FRED 官方資料核對最近 30 個共同交易日的收盤，記中位數誤差。沒設 FRED_API_KEY 就跳過。"""
    key = os.getenv("FRED_API_KEY", "").strip()
    if not key:
        return {"skipped": "沒有設定 FRED_API_KEY"}
    s = _session()
    out = {"at": now_tw().strftime("%Y-%m-%d %H:%M"), "items": {}}
    start = (date.today() - timedelta(days=90)).isoformat()
    for sid, (fid, tol, absdiff) in FRED.items():
        try:
            r = s.get("https://api.stlouisfed.org/fred/series/observations",
                      params={"series_id": fid, "api_key": key, "file_type": "json", "observation_start": start}, timeout=30)
            obs = {o["date"]: float(o["value"]) for o in r.json().get("observations", []) if o.get("value") not in (".", "", None)}
        except Exception as e:  # noqa: BLE001
            out["items"][sid] = {"fred": fid, "error": str(e)[:80]}
            continue
        rows = load(sid)
        common = sorted(set(obs) & set(rows))[-30:]
        if not common:
            out["items"][sid] = {"fred": fid, "n": 0}
            continue
        diffs = sorted(abs(rows[d][3] - obs[d]) if absdiff else abs(rows[d][3] / obs[d] - 1) for d in common if obs[d])
        med = diffs[len(diffs) // 2]
        out["items"][sid] = {"fred": fid, "label": f"FRED {fid}", "n": len(common), "median": round(med, 5), "ok": med <= tol}
        time.sleep(0.3)
    return out


def verify_tpex() -> dict | None:
    """櫃買指數（鉅亨）和櫃買中心官方本月資料核對"""
    try:
        r = _session().get("https://www.tpex.org.tw/www/zh-tw/indexInfo/inx", params={"date": date.today().strftime("%Y/%m/%d"), "response": "json"}, timeout=30)
        data = ((r.json().get("tables") or [{}])[0].get("data")) or []
    except Exception as e:  # noqa: BLE001
        log.warning("櫃買指數核對失敗：%s", e)
        return None
    off = {x[0].replace("/", "-"): float(x[4].replace(",", "")) for x in data if len(x) > 4}
    rows = load("otc")
    common = [d for d in off if d in rows]
    if not common:
        return {"label": "櫃買中心官方", "n": 0}
    diffs = sorted(abs(rows[d][3] / off[d] - 1) for d in common)
    med = diffs[len(diffs) // 2]
    return {"label": "櫃買中心官方", "n": len(common), "median": round(med, 5), "ok": med <= 0.001}


# ---------------- 網站 JSON ----------------
def _ret(ds: list[str], cs: list[float], days: int | None = None, since: str | None = None):
    if not cs:
        return None
    last = cs[-1]
    if since:
        prev = [c for d, c in zip(ds, cs) if d < since]
        base = prev[-1] if prev else None
    else:
        target = (date.fromisoformat(ds[-1]) - timedelta(days=days)).isoformat()
        prev = [c for d, c in zip(ds, cs) if d <= target]
        base = prev[-1] if prev and ds[0] <= target else None
    if not base or base <= 0 or last is None:
        return None
    return round((last / base - 1) * 100, 2)


def _coarse_groups() -> list[dict]:
    out: dict[str, dict] = {}
    for g, its in GROUPS:
        c = COARSE.get(g, g)
        o = out.setdefault(c, {"name": c, "ids": [], "subs": []})
        o["subs"].append({"name": SUBNAME.get(g, g), "ids": [x[0] for x in its]})
        o["ids"] += [x[0] for x in its]
    return list(out.values())


def build_site() -> int:
    st = store.state("markets", {}) or {}
    live, info = st.get("live", {}), st.get("info", {})
    fred = (st.get("fred") or {}).get("items", {})
    OUT.mkdir(parents=True, exist_ok=True)
    items = {}
    for sid, s in SERIES.items():
        rows = load(sid)
        if not rows:
            items[sid] = {**{k: s[k] for k in ("name", "sym", "unit")}, "empty": True, "error": (info.get(sid) or {}).get("error")}
            continue
        ds = sorted(rows)
        cs = [rows[d][3] for d in ds]
        y1 = (date.fromisoformat(ds[-1]) - timedelta(days=365)).isoformat()
        win = [(d, c) for d, c in zip(ds, cs) if d > y1]
        ath_i = max(range(len(cs)), key=lambda i: cs[i])
        lv = live.get(sid) or {}
        # 每週取一點的一年走勢（卡片小圖）
        wk, seen = [], set()
        for d, c in win:
            k = date.fromisoformat(d).isocalendar()[:2]
            if k in seen:
                wk[-1] = c
            else:
                seen.add(k)
                wk.append(c)
        wk[-1] = cs[-1]
        it = {
            "name": s["name"], "sym": s["sym"].split(":", 1)[1] if ":" in s["sym"] and not s["sym"].startswith("^") else s["sym"],
            "src": {"cnyes": "鉅亨網", "moex": "莫斯科交易所", "vn": "DNSE／SSI", "euronext": "Euronext"}.get(s["sym"].split(":")[0], "Yahoo"),
            "unit": s["unit"], "sub": SUBNAME.get(s["group"], s["group"]),
            "date": ds[-1], "close": cs[-1], "prev": cs[-2] if len(cs) > 1 else None,
            "chg": round((cs[-1] / cs[-2] - 1) * 100, 2) if len(cs) > 1 and cs[-2] and cs[-2] > 0 else None,
            "w1": _ret(ds, cs, 7), "m1": _ret(ds, cs, 30), "m3": _ret(ds, cs, 91), "ytd": _ret(ds, cs, since=ds[-1][:4] + "-01-01"),
            "y1": _ret(ds, cs, 365), "y5": _ret(ds, cs, 365 * 5), "y10": _ret(ds, cs, 3652),
            "hi52": max(c for _, c in win), "lo52": min(c for _, c in win),
            "ath": cs[ath_i], "ath_date": ds[ath_i], "first": ds[0], "n": len(ds),
            "live": lv.get("price"), "live_time": lv.get("time"),
            "spark": [_num(x, 4) for x in wk],
            "suspect": (info.get(sid) or {}).get("suspect") or [],
        }
        # 歷史水位：全部歷史、近 10 年的最高最低（前端用現價算位置），以及有幾 % 的交易日收盤低於現在
        lv = {}
        y10 = (date.fromisoformat(ds[-1]) - timedelta(days=3652)).isoformat()
        for key, sub in (("all", list(zip(ds, cs))), ("y10", [(d, c) for d, c in zip(ds, cs) if d > y10])):
            if len(sub) < 3:
                continue
            lo_d, lo = min(sub, key=lambda x: x[1])
            hi_d, hi = max(sub, key=lambda x: x[1])
            below = sum(1 for _, c in sub if c < cs[-1])
            lv[key] = {"lo": lo, "lo_d": lo_d, "hi": hi, "hi_d": hi_d, "pr": round(below / len(sub) * 100, 1), "from": sub[0][0]}
        it["lv"] = lv
        it["atl"], it["atl_date"] = (lv["all"]["lo"], lv["all"]["lo_d"]) if "all" in lv else (min(cs), ds[cs.index(min(cs))])
        if sid in fred:
            it["fred"] = fred[sid]
        items[sid] = it
        with (OUT / f"{sid}.json").open("w", encoding="utf-8") as f:
            json.dump({"id": sid, "d": ds, "c": cs, "o": [rows[d][0] for d in ds[-520:]], "h": [rows[d][1] for d in ds[-520:]],
                       "l": [rows[d][2] for d in ds[-520:]]}, f, ensure_ascii=False, separators=(",", ":"))
    out = {"updated": st.get("updated"), "fred": st.get("fred", {}).get("skipped") or st.get("fred", {}).get("at"),
           "groups": _coarse_groups(), "items": items}
    store.write_json(config.OUT_DIR / "mkt.json", out)
    return sum(1 for v in items.values() if not v.get("empty"))


# ---------------- 模擬資料（本機預覽） ----------------
MOCK_BASE = {"gold": 4000, "silver": 48, "platinum": 1550, "palladium": 1400, "wti": 62, "brent": 66, "natgas": 3.4, "copper": 5.1,
             "ironore": 104, "aluminum": 2750, "corn": 420, "wheat": 530, "soybean": 1040, "coffee": 380, "spx": 7600, "dji": 47000,
             "nasdaq": 25500, "sox": 7100, "vix": 17, "taiex": 27500, "n225": 49000, "kospi": 3900, "hsi": 26000, "sse": 3950,
             "sensex": 84000, "dax": 24200, "ftse": 9600, "cac": 8200, "sx5e": 5650, "dxy": 99, "usdtwd": 30.6, "usdjpy": 152,
             "usdcny": 7.12, "eurusd": 1.16, "us10y": 4.0, "btc": 112000}


def build_mock(years: int = 30) -> None:
    rnd = random.Random(7)
    end = date.today()
    days = [end - timedelta(days=i) for i in range(int(years * 365.25), -1, -1)]
    days = [d for d in days if d.weekday() < 5]
    for sid in SERIES:
        base = MOCK_BASE.get(sid, 100)
        v, path = 1.0, []
        for _ in days:
            v *= math.exp(rnd.gauss(0.00015, 0.012))
            path.append(v)
        k = base / path[-1]
        rows = {}
        for d, p in zip(days, path):
            c = p * k
            rows[d.isoformat()] = [_num(c * (1 + rnd.gauss(0, .003))), _num(c * 1.008), _num(c * 0.992), _num(c), None]
        save(sid, rows)
    st = {"updated": now_tw().strftime("%Y-%m-%d %H:%M"), "info": {}, "live": {}, "fred": {"skipped": "模擬資料"}}
    store.save_state("markets", st)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cmd = argv[0] if argv else "update"
    if cmd == "update":
        ids = [a for a in argv[1:] if a in SERIES]          # 例：update full set psei（只重抓這幾個）
        update(full="full" in argv, quick="quick" in argv, only=ids or None)
    elif cmd == "site":
        print("國際行情網站檔：", build_site(), "個")
    elif cmd == "mock":
        build_mock()
        build_site()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
