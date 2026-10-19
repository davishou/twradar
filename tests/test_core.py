"""python -m pytest -q   （或 python -m unittest）"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pipeline import config
from pipeline.announce import RE_EPS, _months, _period, _traded
from pipeline.disposal import Calendar
from pipeline.sources import cn_int, parse_clauses, parse_minutes
from pipeline.util import limit_down, limit_up, num, parse_date, table_rows


class Price(unittest.TestCase):
    def test_limit_up_ticks(self):
        self.assertEqual(limit_up(10.0), 11.0)
        self.assertEqual(limit_up(9.5), 10.45)       # 10 元以上跳 0.05
        self.assertEqual(limit_up(48.0), 52.8)       # 52.8 在 0.1 級距
        self.assertEqual(limit_up(95.3), 104.5)      # 104.83 → 0.5 級距捨去
        self.assertEqual(limit_up(1055), 1160.0)     # 1160.5 → 5 元級距
        self.assertEqual(limit_down(1055), 950.0)
        self.assertEqual(limit_down(194.0), 175.0)   # 174.6 → 0.5 級距進位

    def test_num(self):
        self.assertEqual(num("1,234.5"), 1234.5)
        self.assertEqual(num("<p style= color:red>+</p>"), None)
        self.assertEqual(num("--"), None)
        self.assertEqual(num("-0.35"), -0.35)

    def test_dates(self):
        self.assertEqual(parse_date("1151016"), date(2026, 10, 16))
        self.assertEqual(parse_date("115/10/16"), date(2026, 10, 16))
        self.assertEqual(parse_date("20261016"), date(2026, 10, 16))

    def test_table_rows(self):
        js = {"tables": [{"fields": ["代號 ", "名稱"], "data": [["1101", "甲"]]}]}
        self.assertEqual(table_rows(js), [{"代號": "1101", "名稱": "甲"}])


class Parse(unittest.TestCase):
    def test_clauses(self):
        self.assertEqual(parse_clauses("第一款、第四款"), [1, 4])
        self.assertEqual(parse_clauses("異常標準第1、3款"), [1, 3])
        self.assertEqual(parse_clauses("第十二款"), [12])
        self.assertEqual(cn_int("二十"), 20)

    def test_minutes(self):
        self.assertEqual(parse_minutes("約每五分鐘撮合一次"), 5)
        self.assertEqual(parse_minutes("每20分鐘撮合"), 20)

    def test_eps(self):
        m = RE_EPS.search("5.每股盈餘(元)：-0.30")
        self.assertEqual(float(m.group(1)), -0.30)
        self.assertEqual(_months(_period("前三季自結")), 9)
        self.assertEqual(_months(_period("9月份自結損益")), 1)

    def test_traded(self):
        self.assertTrue(_traded("2026-10-16", "10:00", date(2026, 10, 16)))
        self.assertFalse(_traded("2026-10-16", "14:30", date(2026, 10, 16)))


class Sources(unittest.TestCase):
    """以交易所公開格式的樣本確認解析邏輯（實際欄名若改版，修 sources.py）"""

    def test_quotes_latest(self):
        from unittest import mock
        from pipeline import sources
        twse = [{"Date": "1151016", "Code": "2033", "Name": "甲", "TradeVolume": "1,000,000", "TradeValue": "59,800,000",
                 "OpeningPrice": "59.8", "HighestPrice": "59.8", "LowestPrice": "59.8", "ClosingPrice": "59.8",
                 "Change": "5.4000", "Transaction": "300"},
                {"Date": "1151016", "Code": "0050", "Name": "ETF", "ClosingPrice": "190", "Change": "1"}]
        tpex = [{"Date": "1151016", "SecuritiesCompanyCode": "3354", "CompanyName": "乙", "Close": "41.80", "Change": "+3.80",
                 "Open": "40.30", "High": "41.80", "Low": "40.00", "TradingShares": "2,728,000", "TransactionAmount": "111,000,000",
                 "TransactionNumber": "1,500"}]
        with mock.patch.object(sources, "get_json", side_effect=lambda u, **k: twse if "twse" in u else tpex):
            d, qs = sources.fetch_quotes()
        self.assertEqual(d, date(2026, 10, 16))
        self.assertEqual([q["code"] for q in qs], ["2033", "3354"])   # ETF 被排除
        self.assertAlmostEqual(qs[0]["prev_close"], 54.4)
        self.assertEqual(limit_up(qs[0]["prev_close"]), 59.8)
        self.assertAlmostEqual(qs[1]["prev_close"], 38.0)

    def test_quotes_by_date_twse(self):
        from unittest import mock
        from pipeline import sources
        mi = {"stat": "OK", "date": "20261016", "tables": [{"fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額",
              "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差"],
              "data": [["2424", "丙", "314,000", "100", "4,900,000", "14.50", "15.60", "14.50", "15.60", "<p style= color:green>-</p>", "0.40"]]}]}
        with mock.patch.object(sources, "get_json", side_effect=lambda u, **k: mi if "twse" in u else None):
            d, qs = sources.fetch_quotes(date(2026, 10, 16))
        self.assertEqual(qs[0]["change"], -0.4)
        self.assertAlmostEqual(qs[0]["prev_close"], 16.0)


class Cal(unittest.TestCase):
    def test_calendar(self):
        c = Calendar({date(2026, 10, 19)})
        self.assertEqual(c.next(date(2026, 10, 16)), date(2026, 10, 20))   # 跳過週末與假日
        self.assertEqual(c.count_between(date(2026, 10, 16), date(2026, 10, 21)), 3)


class Pipeline(unittest.TestCase):
    """用模擬資料跑完整流程，確認每個輸出檔都產生且結構正確"""

    def test_mock_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {k: getattr(config, k) for k in ("DATA_DIR", "HISTORY_DIR", "STATE_DIR", "OUT_DIR", "SITE_DIR")}
            t = Path(tmp)
            config.DATA_DIR, config.HISTORY_DIR, config.STATE_DIR = t / "data", t / "data/history", t / "data/state"
            config.SITE_DIR, config.OUT_DIR = t / "site", t / "site/data"
            from pipeline import active_etf, announce as ann, brief, limitup, store
            limitup.OUT, ann.OUT, brief.OUT = config.OUT_DIR, config.OUT_DIR / "announce", config.OUT_DIR
            active_etf.SNAP = config.DATA_DIR / "etf"
            store.trading_days.cache_clear()
            store.load_day.cache_clear()
            try:
                from pipeline import run
                run.build_mock()
                o = config.OUT_DIR
                for f in ("meta.json", "disposal.json", "stats.json", "line.json", "borrow.json", "etf.json",
                          "stock_history.json", "announce/att.json", "announce/rev.json"):
                    self.assertTrue((o / f).exists(), f)
                d = store.read_json(o / "disposal.json")
                for c in d["minus1"] + d["minus2"]:
                    self.assertIn(c["need"], (1, 2))
                meta = store.read_json(o / "meta.json")
                self.assertTrue(meta["mock"])
                daily = store.read_json(o / "daily" / f"{meta['daily_dates'][0]}.json")
                self.assertEqual(daily["count"], len(daily["stocks"]))
                for s in daily["stocks"]:
                    self.assertGreaterEqual(s["close"], limit_up(s["prev_close"]))
            finally:
                for k, v in old.items():
                    setattr(config, k, v)
                limitup.OUT, ann.OUT, brief.OUT = config.OUT_DIR, config.OUT_DIR / "announce", config.OUT_DIR
                active_etf.SNAP = config.DATA_DIR / "etf"
                store.trading_days.cache_clear()
                store.load_day.cache_clear()


if __name__ == "__main__":
    unittest.main()


class Brokers(unittest.TestCase):
    def test_parse_and_aggregate(self):
        from pipeline.brokers import aggregate, parse_rows
        text = ('序號,證券商,成交單價,買進股數,賣出股數,,序號,證券商,成交單價,買進股數,賣出股數\n'
                '1,9268凱基台北,139.50,"12,000",0,,2,9268凱基台北,140.00,5000,1000\n'
                '3,1020合　　庫,138.00,0,3000,,\n')
        rows = parse_rows(text)
        self.assertEqual(rows[2], ("合庫", 138.0, 0, 3000))
        agg = {r[0]: r for r in aggregate(rows)}
        self.assertEqual(agg["凱基台北"][1:3], [17.0, 1.0])
        self.assertAlmostEqual(agg["凱基台北"][3], 139.65)
        self.assertIsNone(agg["合庫"][3])
