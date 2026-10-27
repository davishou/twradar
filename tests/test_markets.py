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
                self.assertEqual(g["lv"]["all"]["lo"], 100.0)
                self.assertEqual(g["lv"]["all"]["hi"], 132.0)
                self.assertEqual(g["lv"]["all"]["pr"], 75.0)   # 4 天中有 3 天低於現價

    def test_suspect_spike_kept_but_flagged(self):
        rows = {f"2025-01-0{i}": [None, None, None, c, None] for i, c in enumerate([100, 101, 300, 102, 103], 1)}
        self.assertEqual(markets._check("gold", rows), ["2025-01-03"])

    def test_num_precision(self):
        self.assertEqual(markets._num(1.1600123456), 1.160012)
        self.assertEqual(markets._num(7676.774999), 7676.775)
        self.assertIsNone(markets._num(float("nan")))


if __name__ == "__main__":
    unittest.main()


class CnyesTest(unittest.TestCase):
    def test_pages_newest_first(self):
        pages = [{"t": [1793059200, 1792972800], "o": [2, 1], "h": [2, 1], "l": [2, 1], "c": [11.0, 10.0], "v": [5, 4]}, {"t": []}]
        calls = []

        class R:
            status_code = 200
            def __init__(self, d): self.d = d
            def json(self): return {"data": self.d}

        def get(url, params=None, **kw):
            calls.append(params["from"])
            return R(pages[len(calls) - 1])
        with mock.patch.object(markets, "_session", return_value=mock.Mock(get=get)), mock.patch.object(markets.time, "sleep"):
            rows, meta = markets.fetch_cnyes("GI:SET:INDEX")
        self.assertEqual(sorted(rows), ["2026-10-26", "2026-10-27"])
        self.assertEqual(rows["2026-10-27"][3], 11.0)
        self.assertEqual(calls[1], 1792972800 - 1)       # 第二頁從最舊那天往前翻


class OtherSourcesTest(unittest.TestCase):
    def test_euronext_csv(self):
        txt = '﻿"Historical Data"\n"From 2000-01-01 to 2026-10-27"\nNO0007035327\nDate;Open;High;Low;Last;Close;"Number of Shares"\n26/10/2026;2098.36;2125.60;2096.17;2125.05;2125.05;0\n23/10/2026;2085.67;2106.09;2082.98;2101.12;2101.12;0\n'
        sess = mock.Mock(get=mock.Mock(return_value=mock.Mock(text=txt)))
        with mock.patch.object(markets, "_session", return_value=sess):
            rows, _ = markets.fetch_euronext("NO0007035327-XOSL", since="2026-10-01")
        self.assertEqual(rows["2026-10-26"][3], 2125.05)
        self.assertEqual(sorted(rows), ["2026-10-23", "2026-10-26"])

    def test_moex_pages(self):
        pages = [{"history": {"data": [["2026-10-01", 1, 2, 0.5, 2278.53], ["2026-10-02", 1, 2, 0.5, 2279.75]]}}, {"history": {"data": []}}]
        it = iter(pages)
        sess = mock.Mock(get=lambda *a, **k: mock.Mock(json=lambda: next(it)))
        with mock.patch.object(markets, "_session", return_value=sess), mock.patch.object(markets.time, "sleep"):
            rows, _ = markets.fetch_moex("IMOEX")
        self.assertEqual(rows["2026-10-02"][3], 2279.75)
