"""分鐘 K（pipeline/minute.py）：用假的 Shioaji 與本機資料夾測試，不連網。"""
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace as NS

import pandas as pd

from pipeline import minute as M


def bars(day: str, n: int = 3, px: float = 100.0):
    ts = pd.date_range(f"{day} 09:01", periods=n, freq="1min")
    return {"ts": list(ts.as_unit("ns").asi8), "Open": [px] * n, "High": [px + 1] * n, "Low": [px - 1] * n,
            "Close": [px + 0.5] * n, "Volume": [10] * n, "Amount": [px * 10000] * n}


class FakeApi:
    """2330 從 2018-12 起有資料；6999 從 2025-06 起才上市；流量可設定用完。"""
    def __init__(self):
        c = lambda code: NS(code=code)
        self.Contracts = NS(Stocks=NS(TSE=[c("2330"), c("0050"), c("00631L"), c("030001"), c("2881A")],
                                      OTC=[c("6999")]))
        self.remaining = 10**9
        self.calls = []

    def usage(self):
        return NS(remaining_bytes=self.remaining)

    def snapshots(self, cs):
        return [NS(code=x.code, total_amount={"2330": 9, "6999": 5}.get(x.code, 1)) for x in cs]

    def kbars(self, contract, start, end):
        self.calls.append((contract.code, start))
        first = {"2330": "2018-12", "0050": "2018-12", "00631L": "2018-12", "6999": "2025-06"}[contract.code]
        if start[:7] < first or self.remaining < 10**6:
            return {"ts": []}
        days = pd.bdate_range(start, end)[:2]
        out = {k: [] for k in ("ts", "Open", "High", "Low", "Close", "Volume", "Amount")}
        for d in days:
            for k, v in bars(d.strftime("%Y-%m-%d")).items():
                out[k] += v
        return out


class Minute(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = M.LocalStore(self.tmp.name)
        self.api = FakeApi()
        self.fx = M.Fetcher(self.api, reserve=0)
        self.fx.MIN_GAP = 0

    def tearDown(self):
        self.tmp.cleanup()

    def test_universe(self):
        self.assertEqual(sorted(self.fx.contracts()), ["0050", "00631L", "2330", "6999"])  # 無權證、特別股

    def test_months(self):
        self.assertEqual(list(M.months_back("2019-02", "2018-12")), ["2019-02", "2019-01", "2018-12"])
        self.assertEqual(M.month_end("2024-02"), "2024-02-29")
        self.assertEqual(M.prev_month("2025-01"), "2024-12")

    def test_daily_merge_and_resume(self):
        r = M.daily(self.fx, self.store, date(2026, 11, 12))
        self.assertEqual((r["from"], r["codes"]), ("2026-11-01", 4))
        r2 = M.daily(self.fx, self.store, date(2026, 11, 13))
        self.assertEqual(r2["from"], "2026-11-13")
        df = M.load("2330", "2026-11-01", "2026-11-30", store=self.store, cache=None)
        self.assertFalse(df["ts"].duplicated().any())
        self.assertEqual(df["close"].iloc[0], 100.5)
        self.assertIn("skip", M.daily(self.fx, self.store, date(2026, 11, 13)))

    def test_backfill_layers_and_listing(self):
        M.daily(self.fx, self.store, date(2026, 11, 12))
        r = M.backfill(self.fx, self.store, minutes=5)
        self.assertEqual(r["stop"], "全部補完")
        p = M.load_progress(self.store)
        self.assertEqual(p["back"]["2330"], "2018-12")
        self.assertEqual(p["back"]["6999"], "2025-06")       # 上市前連 3 個月空就停
        self.assertIn("6999", p["done"])
        self.assertTrue(self.store.get(M.key_of("2330", "2018-12")))
        # 第一層（2026-10）成交金額大的先抓
        self.assertEqual([c for c, s in self.api.calls if s == "2026-10-01"][:2], ["2330", "6999"])

    def test_quota_stops_without_marking(self):
        M.daily(self.fx, self.store, date(2026, 11, 12))
        self.fx.reserve = 5 * 10**6
        self.api.remaining = 10**6 // 2                    # 流量用完：kbars 回空
        r = M.backfill(self.fx, self.store, minutes=5)
        self.assertIn("剩餘流量", r["stop"])
        self.assertEqual(M.load_progress(self.store)["done"], [])

    def test_resample(self):
        df = M.to_df(bars("2026-11-12", n=10))
        k5 = M.resample(df, "5min")
        self.assertEqual(len(k5), 2)
        self.assertEqual(k5["volume"].tolist(), [50, 50])
        self.assertEqual(str(k5["ts"].iloc[0]), "2026-11-12 09:05:00")


if __name__ == "__main__":
    unittest.main()
