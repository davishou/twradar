"""分鐘 K 資料庫：永豐 Shioaji 抓 1 分 K → Parquet（每檔每月一個檔）→ Cloudflare R2。

資料不進 git（全市場好幾年的 1 分 K 有好幾 GB），放在私人 R2 bucket：
    minute/1m/<代號>/<YYYY-MM>.parquet   欄位 ts, open, high, low, close, volume(張), amount(元)
    minute/_progress.json                 進度（每日更新到哪天、每檔往回補到哪個月）

ts 是台灣時間（不帶時區），沿用 Shioaji 的標法：09:01 那根＝09:00~09:01 的成交（XQ 標成 09:00）。

指令（GitHub Actions minute.yml 會跑；本機要先設環境變數）：
    python -m pipeline.minute probe                  第一次設定用：登入、看流量、抓 2330 一天、測試 R2 讀寫
    python -m pipeline.minute daily [YYYY-MM-DD]     補最近的交易日（從上次更新到的日子接著抓，最多 30 天）
    python -m pipeline.minute backfill [分鐘]         由新到舊回補（最早 2018-12），流量快用完或時間到就停，下次續跑
    python -m pipeline.minute status                 看進度

環境變數：SHIOAJI_API_KEY、SHIOAJI_SECRET_KEY；
          R2_ACCOUNT_ID、R2_ACCESS_KEY_ID、R2_SECRET_ACCESS_KEY、R2_BUCKET（沒設 R2 就存到本機 MINUTE_DIR，預設 data/.cache/minute_store）

研究程式讀資料：
    from pipeline.minute import load, resample
    df = load("2330", "2024-01-01", "2024-03-31")      # 會快取到 data/.cache/minute
    k5 = resample(df, "5min")

永豐限制（sinotrade.github.io/tutor/limit）：行情查詢每 10 秒最多 50 次，超過停用 1 分鐘；
每日流量 500MB（近 30 天 API 下單 0 元）／2GB（1 元~1 億）／10GB，交易日早上 8 點重置，
流量用完後 kbars 會回空資料——所以回補時每 50 次查一次剩餘流量，快不夠就停，空資料不能當成「沒上市」。
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

TW = ZoneInfo("Asia/Taipei")
EARLIEST = "2018-12"          # Shioaji 1 分 K 最早到 2018-12-07
EMPTY_STOP = 3
PREFIX = "minute/1m"
PROGRESS = "minute/_progress.json"
COLS = ["ts", "open", "high", "low", "close", "volume", "amount"]
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / ".cache" / "minute"


# ---------------------------------------------------------------- 儲存（R2 或本機資料夾）
class LocalStore:
    def __init__(self, root):
        self.root = Path(root)

    def get(self, key: str) -> bytes | None:
        p = self.root / key
        return p.read_bytes() if p.exists() else None

    def put(self, key: str, data: bytes) -> None:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def keys(self, prefix: str) -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())


class R2Store:
    def __init__(self, account_id, key_id, secret, bucket):
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self.s3 = boto3.client(
            "s3", endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=key_id, aws_secret_access_key=secret, region_name="auto",
            config=Config(retries={"max_attempts": 5, "mode": "standard"}))

    def get(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None

    def put(self, key: str, data: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def keys(self, prefix: str) -> list[str]:
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            r = self.s3.list_objects_v2(**kw)
            out += [o["Key"] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return out
            token = r["NextContinuationToken"]


def open_store():
    e = os.environ
    if e.get("R2_BUCKET"):
        return R2Store(e["R2_ACCOUNT_ID"], e["R2_ACCESS_KEY_ID"], e["R2_SECRET_ACCESS_KEY"], e["R2_BUCKET"])
    return LocalStore(e.get("MINUTE_DIR") or ROOT / "data" / ".cache" / "minute_store")


# ---------------------------------------------------------------- 資料格式
def to_df(kb) -> pd.DataFrame:
    """Shioaji KBars（或同樣欄位的 dict）→ DataFrame。價格存 float32（讀取時四捨五入到 0.01）。"""
    d = {k: list(getattr(kb, k, None) if not isinstance(kb, dict) else kb.get(k) or [])
         for k in ("ts", "Open", "High", "Low", "Close", "Volume", "Amount")}
    if not d["ts"]:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame({
        "ts": pd.to_datetime(pd.Series(d["ts"], dtype="int64"), unit="ns").astype("datetime64[s]"),  # 奈秒、台灣時間
        "open": d["Open"], "high": d["High"], "low": d["Low"], "close": d["Close"],
        "volume": d["Volume"], "amount": d["Amount"]})
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype("float32")
    df["volume"] = df["volume"].astype("int64")
    df["amount"] = pd.Series(d["Amount"]).round().astype("int64")
    return df


def to_parquet(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, compression="zstd")
    return buf.getvalue()


def from_parquet(b: bytes) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(b))


def key_of(code: str, ym: str) -> str:
    return f"{PREFIX}/{code}/{ym}.parquet"


def write_months(store, code: str, df: pd.DataFrame, merge: bool = True) -> int:
    """依月份拆開寫入；merge=True 會和既有檔合併（同時間保留新抓的）。回傳寫了幾個檔。"""
    if df.empty:
        return 0
    n = 0
    for ym, part in df.groupby(df["ts"].dt.strftime("%Y-%m")):
        k = key_of(code, ym)
        if merge:
            old = store.get(k)
            if old:
                part = pd.concat([from_parquet(old), part])
        part = part.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)
        store.put(k, to_parquet(part[COLS]))
        n += 1
    return n


def months_back(start_ym: str, stop_ym: str = EARLIEST):
    """start_ym 往回到 stop_ym（含），新到舊。"""
    y, m = map(int, start_ym.split("-"))
    while f"{y:04d}-{m:02d}" >= stop_ym:
        yield f"{y:04d}-{m:02d}"
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)


def prev_month(ym: str) -> str:
    y, m = map(int, ym.split("-"))
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def month_end(ym: str) -> str:
    y, m = map(int, ym.split("-"))
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------- 進度
def load_progress(store) -> dict:
    b = store.get(PROGRESS)
    p = json.loads(b) if b else {}
    p.setdefault("back", {})      # 代號 → 已補到的最早月份
    p.setdefault("done", [])      # 已補到上市第一天（或 2018-12）的代號
    p.setdefault("empty", {})     # 代號 → 連續空月數
    p.setdefault("tried", {})     # 代號 → 回補查過的最早月份（有沒有資料都算）
    p.setdefault("runs", [])
    return p


def save_progress(store, p: dict) -> None:
    p["runs"] = p["runs"][-30:]
    store.put(PROGRESS, json.dumps(p, ensure_ascii=False, indent=1).encode())


# ---------------------------------------------------------------- 永豐
class Quota(Exception):
    """流量快用完／被限速，停下來等下次。"""


class Fetcher:
    """包住 Shioaji：控制每秒次數、檢查剩餘流量。測試時可傳入假的 api。"""
    MIN_GAP = 0.25          # 秒；每 10 秒最多 40 次（上限 50）
    RESERVE = 30 * 2**20    # 留 30MB 給隔天的每日更新

    def __init__(self, api, reserve: int | None = None):
        self.api = api
        self.reserve = self.RESERVE if reserve is None else reserve
        self.calls = 0
        self._last = 0.0

    @classmethod
    def login(cls):
        import shioaji as sj
        api = sj.Shioaji()
        api.login(api_key=os.environ["SHIOAJI_API_KEY"], secret_key=os.environ["SHIOAJI_SECRET_KEY"])
        try:
            if not list(api.Contracts.Stocks.TSE):
                api.fetch_contracts(contract_download=True)
        except Exception:
            api.fetch_contracts(contract_download=True)
        return cls(api)

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.MIN_GAP:
            time.sleep(self.MIN_GAP - gap)
        self._last = time.monotonic()
        self.calls += 1

    def remaining(self) -> int | None:
        try:
            self._wait()
            return int(self.api.usage().remaining_bytes)
        except Exception:
            return None

    def check(self):
        r = self.remaining()
        if r is not None and r < self.reserve:
            raise Quota(f"剩餘流量 {r / 2**20:.0f}MB")

    def contracts(self) -> dict:
        """上市櫃普通股＋ETF（4 碼數字或 00 開頭），不含權證、特別股。"""
        out = {}
        for mkt in ("TSE", "OTC"):
            for c in getattr(self.api.Contracts.Stocks, mkt):
                code = c.code
                if (len(code) == 4 and code.isdigit()) or (code.startswith("00") and len(code) <= 6):
                    out[code] = c
        return out

    def kbars(self, contract, start: str, end: str) -> pd.DataFrame:
        for i in range(3):
            self._wait()
            try:
                return to_df(self.api.kbars(contract, start=start, end=end))
            except Exception as e:
                if i == 2:
                    raise
                print(f"  kbars {contract.code} {start} 失敗：{e}，重試", file=sys.stderr)
                time.sleep(65 if "limit" in str(e).lower() else 5)

    def ranking(self, contracts: dict) -> list[str]:
        """依今天成交金額排序（大到小）；拿不到就照代號。"""
        cs = list(contracts.values())
        amt = {}
        for i in range(0, len(cs), 500):
            try:
                self._wait()
                for s in self.api.snapshots(cs[i:i + 500]):
                    amt[s.code] = s.total_amount
            except Exception as e:
                print(f"  snapshots 失敗：{e}", file=sys.stderr)
        return sorted(contracts, key=lambda c: (-amt.get(c, 0), c))


# ---------------------------------------------------------------- 每日更新
def now_tw() -> datetime:
    return datetime.now(TW)


def daily(fx: Fetcher, store, end: date | None = None) -> dict:
    """從上次更新到的隔天抓到 end（預設：14:00 後＝今天，否則昨天），最多 30 天。"""
    t = now_tw()
    end = end or (t.date() if t.hour >= 14 else t.date() - timedelta(days=1))
    p = load_progress(store)
    if "daily_first" not in p:                   # 第一次：從本月 1 號開始，之前的交給回補
        p["daily_first"] = end.strftime("%Y-%m")
        start = end.replace(day=1)
    else:
        start = date.fromisoformat(p["daily_last"]) + timedelta(days=1)
        start = max(start, end - timedelta(days=30))
    if start > end:
        return {"job": "daily", "skip": f"已更新到 {p['daily_last']}"}
    cs = fx.contracts()
    ok = bad = rows = 0
    t0 = time.time()
    for code, c in cs.items():
        try:
            df = fx.kbars(c, start.isoformat(), end.isoformat())
            write_months(store, code, df)
            rows += len(df)
            ok += 1
        except Exception as e:
            bad += 1
            print(f"  {code} 失敗：{e}", file=sys.stderr)
    res = {"job": "daily", "from": start.isoformat(), "to": end.isoformat(), "codes": ok, "failed": bad,
           "rows": rows, "sec": round(time.time() - t0), "at": t.isoformat(timespec="minutes")}
    if ok and bad < 0.05 * len(cs):
        p["daily_last"] = end.isoformat()
    p["runs"].append(res)
    save_progress(store, p)
    return res


# ---------------------------------------------------------------- 回補
def backfill(fx: Fetcher, store, minutes: float = 240) -> dict:
    """由新到舊一個月一層：每個月先把全部股票補完（成交金額大的先），再往前一個月。
    中斷後下次從同一層接著補。每檔一個月查一次（約 300KB 流量）。"""
    p = load_progress(store)
    if "daily_first" not in p:
        return {"job": "backfill", "skip": "還沒跑過 daily"}
    t0 = time.time()
    cs = fx.contracts()
    done = set(p["done"])
    order = [c for c in fx.ranking({k: v for k, v in cs.items() if k not in done}) if c in cs]
    fetched = written = 0
    stop = "全部補完"
    try:
        fx.check()
        for ym in months_back(prev_month(p["daily_first"])):
            todo = [c for c in order if c not in done and p["tried"].get(c, "9999") > ym]
            for code in todo:
                if time.time() - t0 > minutes * 60:
                    raise TimeoutError
                if fetched and fetched % 50 == 0:
                    fx.check()
                    save_progress(store, p)
                df = fx.kbars(cs[code], f"{ym}-01", month_end(ym))
                fetched += 1
                if df.empty:
                    # 流量用完也會回空資料：先確認還有流量，才當成「這個月真的沒資料」
                    fx.check()
                    p["empty"][code] = p["empty"].get(code, 0) + 1
                    if p["empty"][code] >= EMPTY_STOP:      # 連 3 個月沒資料＝還沒上市（停牌通常不會這麼久）
                        done.add(code)
                else:
                    written += write_months(store, code, df, merge=False)
                    p["back"][code] = ym
                    p["empty"].pop(code, None)
                p["tried"][code] = ym
            p["layer"] = ym
    except Quota as e:
        stop = str(e)
    except TimeoutError:
        stop = f"時間到（{minutes:.0f} 分鐘）"
    p["done"] = sorted(done | {c for c, ym in p["tried"].items() if ym <= EARLIEST})
    res = {"job": "backfill", "fetched": fetched, "files": written, "layer": p.get("layer"), "stop": stop,
           "done_codes": len(p["done"]), "remaining_mb": (fx.remaining() or 0) // 2**20,
           "min": round((time.time() - t0) / 60, 1), "at": now_tw().isoformat(timespec="minutes")}
    p["runs"].append(res)
    save_progress(store, p)
    return res


def status(store) -> dict:
    p = load_progress(store)
    backs = list(p["back"].values())
    return {"daily_first": p.get("daily_first"), "daily_last": p.get("daily_last"), "layer": p.get("layer"),
            "codes_backfilled": len(backs), "codes_done": len(p["done"]),
            "earliest_month": min(backs) if backs else None, "last_runs": p["runs"][-5:]}


def probe(fx: Fetcher, store) -> dict:
    r = fx.remaining()
    cs = fx.contracts()
    t = now_tw().date()
    df = pd.DataFrame()
    for i in range(1, 8):                          # 找最近一個有資料的交易日
        d = (t - timedelta(days=i)).isoformat()
        df = fx.kbars(cs["2330"], d, d)
        if not df.empty:
            break
    store.put("minute/_probe.parquet", to_parquet(df))
    back = from_parquet(store.get("minute/_probe.parquet"))
    return {"remaining_mb": None if r is None else r // 2**20, "contracts": len(cs),
            "tse_otc_sample": sorted(cs)[:5], "day": d, "rows": len(df),
            "first": str(df["ts"].iloc[0]) if len(df) else None, "last": str(df["ts"].iloc[-1]) if len(df) else None,
            "r2_roundtrip": len(back) == len(df), "parquet_kb": round(len(to_parquet(df)) / 1024, 1)}


# ---------------------------------------------------------------- 研究程式讀取
def load(code: str, start: str, end: str, store=None, cache: Path | None = CACHE) -> pd.DataFrame:
    """讀 [start, end] 的 1 分 K（日期含頭尾）。過去的月份會快取在本機，當月每次重抓。"""
    store = store or open_store()
    this_month = now_tw().strftime("%Y-%m")
    parts = []
    for ym in months_back(end[:7], start[:7]):
        b = None
        cp = cache / code / f"{ym}.parquet" if cache else None
        if cp and cp.exists() and ym < this_month:
            b = cp.read_bytes()
        else:
            b = store.get(key_of(code, ym))
            if b and cp and ym < this_month:
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_bytes(b)
        if b:
            parts.append(from_parquet(b))
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(parts).sort_values("ts")
    df = df[(df["ts"] >= pd.Timestamp(start)) & (df["ts"] < pd.Timestamp(end) + pd.Timedelta(days=1))]
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype("float64").round(2)
    return df.reset_index(drop=True)


def resample(df: pd.DataFrame, rule: str = "5min") -> pd.DataFrame:
    """1 分 K 合成 5／15／60 分 K（標在區間結束時間，同 Shioaji）。"""
    g = df.set_index("ts").resample(rule, label="right", closed="right")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(), "amount": g["amount"].sum()})
    return out.dropna(subset=["open"]).reset_index()


# ---------------------------------------------------------------- 指令
def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else "status"
    store = open_store()
    if cmd == "status":
        res = status(store)
    else:
        fx = Fetcher.login()
        if cmd == "probe":
            res = probe(fx, store)
        elif cmd == "daily":
            res = daily(fx, store, date.fromisoformat(argv[1]) if len(argv) > 1 and "-" in argv[1] else None)
        elif cmd == "backfill":
            res = backfill(fx, store, float(argv[1]) if len(argv) > 1 else 240)
        elif cmd == "auto":                            # 排程：先每日、再用剩下的時間與流量回補
            t0 = time.time()
            res = {"daily": daily(fx, store)}
            total = float(argv[1]) if len(argv) > 1 else 240
            res["backfill"] = backfill(fx, store, total - (time.time() - t0) / 60)
        else:
            raise SystemExit(f"不認得的指令 {cmd}")
    out = json.dumps(res, ensure_ascii=False, indent=1)
    print(out)
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write(f"### 分鐘 K：{cmd}\n```json\n{out}\n```\n")


if __name__ == "__main__":
    main(sys.argv[1:])
