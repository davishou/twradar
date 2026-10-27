import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import config, markets


class MarketsTest(unittest.TestCase):
    def test_roundtrip_returns_and_site(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            with mock.patch.object(markets, "MKT_DIR", t / "mkt"), mock.patch.object(markets, "OUT", t / "out" / "mkt"), \
                 mock.patch.object(config, "OUT_DIR", t / "out"), mock.patch.object(config, "STATE_DIR", t / "state"), \
                 mock.patch.object(markets, "SERIES", {"gold": markets.SERIES["gold"]}):
                rows = {"2024-12-31": [1, 1, 1, 100.0, 5], "2025-06-30": [1, 1, 1, 110.0, None], "2025-10-27": [1, 1, 1, 120.0, 7],
                        "2025-10-28": [1, 1, 1, 132.0, 8]}
                markets.save("gold", rows)
                self.assertEqual(sorted(p.name for p in (t / "mkt" / "gold").iterdir()), ["2024.csv", "2025.csv"])
                self.assertEqual(markets.load("gold")["2025-10-28"][3], 132.0)
                self.assertIsNone(markets.load("gold")["2025-06-30"][4])
                self.assertEqual(markets.build_site(), 1)
                js = markets.store.read_json(t / "out" / "mkt.json")
                g = js["items"]["gold"]
                self.assertEqual(g["chg"], 10.0)            # 120 → 132
                self.assertEqual(g["ytd"], 32.0)            # 去年底 100 → 132
                self.assertEqual(g["ath"], 132.0)
                self.assertTrue((t / "out" / "mkt" / "gold.json").exists())

    def test_suspect_spike_kept_but_flagged(self):
        rows = {f"2025-01-0{i}": [None, None, None, c, None] for i, c in enumerate([100, 101, 300, 102, 103], 1)}
        self.assertEqual(markets._check("gold", rows), ["2025-01-03"])

    def test_num_precision(self):
        self.assertEqual(markets._num(1.1600123456), 1.160012)
        self.assertEqual(markets._num(7676.774999), 7676.775)
        self.assertIsNone(markets._num(float("nan")))


if __name__ == "__main__":
    unittest.main()
