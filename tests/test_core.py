"""python -m pytest -q   （或 python -m unittest）"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pipeline import config
from pipeline.announce import _period_of, _traded, parse_att, parse_event, parse_fin, parse_treasury, pnum
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
        self.assertEqual(pnum("(0.04)"), -0.04)
        self.assertEqual(pnum("1,675"), 1675)
        self.assertEqual(_period_of("前三季自結")[1], 9)
        self.assertEqual(_period_of("9月份自結損益"), ("9月", 1))
        self.assertEqual(_period_of("公告本公司115年第三季合併報表自結數"), ("Q3", 3))

    def test_attention_formats(self):
        twse = ("3.財務業務資訊:\n     科目       115年 9月    同期增減   115年第2季   同期增減   115年第2季\n"
                "營業收入(百萬)         148       40.95          411   (16.29)         1,675\n"
                "每股(虧損)盈餘(元)  (0.04)     (84.62)       (0.12)  (126.67)          1.56\n")
        a = parse_att("本公司有價證券於集中交易市場達公布注意交易資訊標準 故公布相關財務業務等重大訊息", twse)
        self.assertEqual((a["eps"], a["q_eps"], a["rev"], a["period"], a["q_label"]), (-0.04, -0.12, 148, "9月", "Q2"))
        tpex = ("3.財務業務資訊:\n(1)單月\n (115年9月) (114年9月)\n營業收入(百萬元)  188  130  44.62%\n"
                "每股盈餘(元)  0.72  0.26  176.92%\n(2)單季\n (115第2季)\n每股盈餘 (元)  1.17  0.49  138.78%\n")
        b = parse_att("本公司有價證券近期多次達公佈注意交易資訊標準，故公告相關訊息", tpex)
        self.assertEqual((b["eps"], b["q_eps"], b["rev"]), (0.72, 1.17, 188))
        c = parse_att("公告本公司115年第三季合併報表自結數", "單季合併營業利益：NTD84,431仟元\n單季每股稅後盈餘：NTD0.62元")
        self.assertEqual((c["eps"], c["period"]), (0.62, "Q3"))

    def test_fin_treasury_event(self):
        f = parse_fin("起訖日期(XXX/XX/XX~XXX/XX/XX):115/01/01~115/09/30\n4.1月1日累計至本期止營業收入(仟元):759,950\n"
                      "5.1月1日累計至本期止營業毛利(毛損) (仟元):414,301\n6.1月1日累計至本期止營業利益(損失) (仟元):205,316\n"
                      "7.1月1日累計至本期止稅前淨利(淨損) (仟元):229,247\n10.1月1日累計至本期止基本每股盈餘(損失) (元):3.02")
        self.assertEqual((f["year"], f["q"], f["rev"], f["gross"], f["eps"]), (115, 3, 759950, 414301, 3.02))
        t = parse_treasury("1.董事會決議日期:115/10/19\n2.買回股份目的:轉讓股份予員工\n5.預定買回之期間:115/10/20~115/12/18\n"
                           "6.預定買回之數量(股):750,000\n7.買回區間價格(元):22.00~36.00，公司股價低於區間價格下限")
        self.assertEqual((t["shares"], t["purpose"], t["low"], t["high"], t["start"], t["end"]), (750000, "員工", 22.0, 36.0, "2026-10-20", "2026-12-18"))
        e = parse_event("光寶科技115年第三季法人說明會", "1.召開法人說明會之日期：115/10/30\n2.召開法人說明會之時間：14 時 00 分")
        self.assertEqual((e["kind"], e["from"]), ("法", "2026-10-30"))
        e = parse_event("115年第3季財務報告董事會預計召開日期為115年10月27日", "2.董事會預計召開日期:115/10/27")
        self.assertEqual((e["kind"], e["from"]), ("財", "2026-10-27"))
        e = parse_event("公告本公司訂定除息基準日", "2.除權、息類別（請填入「除權」、「除息」或「除權息」）:除息\n4.除權（息）交易日:115/11/02")
        self.assertEqual((e["kind"], e["from"]), ("息", "2026-11-02"))

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
            from pipeline import brokers as bk
            old_bk = (bk.OUT, bk.DEBUG_DIR)
            bk.OUT, bk.DEBUG_DIR = config.OUT_DIR / "brokers", config.STATE_DIR / "brokers_debug"
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
                bk.OUT, bk.DEBUG_DIR = old_bk
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


class ArchiveTest(unittest.TestCase):
    def test_write_read_adjust(self):
        import tempfile
        from pathlib import Path
        from pipeline import archive
        old = archive.ROOT
        archive.ROOT = Path(tempfile.mkdtemp())
        try:
            q = lambda c, ref: {"code": "1101", "name": "台泥", "market": "TWSE", "open": c, "high": c, "low": c,
                                "close": c, "change": round(c - ref, 2), "prev_close": ref, "volume": 1000, "value": 1, "trades": 1}
            archive.save_quotes(date(2026, 7, 1), [q(40.0, 40.0)])
            archive.save_quotes(date(2026, 7, 2), [q(39.0, 38.5)])   # 除息 1.5 元
            b1 = archive.path("quotes", "2026-07-02").read_bytes()
            archive.save_quotes(date(2026, 7, 2), [q(39.0, 38.5)])
            self.assertEqual(b1, archive.path("quotes", "2026-07-02").read_bytes())  # 內容相同檔案不變
            self.assertEqual(archive.read("quotes", "2026-07-02")[0]["ref"], "38.5")
            self.assertEqual(archive.build_adjust(), 1)
        finally:
            archive.ROOT = old


class TreasuryBackfill(unittest.TestCase):
    def test_backfill_and_merge(self):
        """回補是可續跑的；決議比執行結果晚補進來也只會有一筆計畫"""
        import tempfile
        from pathlib import Path
        from pipeline import announce as ann, store
        old = (config.STATE_DIR, ann.OUT, ann._time.sleep)
        tmp = Path(tempfile.mkdtemp())
        config.STATE_DIR, ann.OUT, ann._time.sleep = tmp / "state", tmp / "out", (lambda s: None)
        try:
            dec = {"date": "2026-06-01", "time": "17:00", "code": "1234", "name": "測試", "market": "TWSE",
                   "subject": "公告本公司董事會決議買回庫藏股",
                   "body": "1.董事會決議日期:115/06/01\n2.買回股份目的:轉讓股份予員工\n5.預定買回之數量(股):1,000,000\n"
                           "7.買回區間價格(元):20.00~30.00\n8.預定買回之期間:115/06/02~115/08/01"}
            res = {"date": "2026-08-03", "time": "17:00", "code": "1234", "name": "測試", "market": "TWSE",
                   "subject": "公告本公司買回股份期間屆滿", "body": "1.原預定買回之數量(股):1,000,000\n"
                   "2.原預定買回之期間:115/06/02~115/08/01\n3.本次已買回股份數量(股):500,000\n6.平均每股買回價格(元):25.00"}
            other = {**dec, "subject": "公告本公司董事會決議發放股利", "code": "9999"}
            days = {"2026-06-01": [dec, other], "2026-08-03": [res]}
            calls = []

            def fetch(d):
                calls.append(d)
                return days.get(d.isoformat(), [])
            today = date(2026, 10, 25)
            r = ann.backfill_treasury(fetch, today, days=185, minutes=5)
            self.assertEqual((r["found"], r["left"]), (2, 0))
            raw = ann.treasury_raw_items()
            self.assertEqual({x["code"] for x in raw}, {"1234"})   # 只留庫藏股公告
            n = len(calls)
            ann.backfill_treasury(fetch, today, days=185, minutes=5)
            self.assertEqual(len(calls), n)                          # 抓過的日子不再抓
            out = ann.build([], [], [], date(2026, 10, 23), [], treasury_extra=raw)["treasury"]
            self.assertEqual(len(out), 1)
            p = out[0]
            self.assertEqual((p["shares"], p["done_shares"], p["progress"], p["purpose"]), (1000000, 500000, 50, "員工"))
            self.assertEqual(p["status"], "完成")
            self.assertFalse(p["new"])
        finally:
            config.STATE_DIR, ann.OUT, ann._time.sleep = old


class DisposalPeers(unittest.TestCase):
    def test_industry_average_raises_threshold(self):
        """同類股 6 日平均漲 15%：第一款往上門檻＝max(32%, 全體+20%, 同類+20%)＝35%；本益比 ≥60 倍時不比同類"""
        import tempfile
        from pathlib import Path
        from pipeline import disposal, store
        old = config.HISTORY_DIR
        config.HISTORY_DIR = Path(tempfile.mkdtemp())
        store.trading_days.cache_clear(); store.load_day.cache_clear()
        try:
            codes = [f"90{i:02d}" for i in range(6)] + ["8000"]
            comp = {c: {"market": "TWSE", "industry": "測試業" if c != "8000" else "其他"} for c in codes}
            days = [date(2026, 9, d) for d in (1, 2, 3, 4, 7, 8)]
            for i, d in enumerate(days):
                qs = []
                for c in codes:
                    px = 10.0 if c == "8000" else (10.0 if i == 0 else 11.5)   # 同類漲 15%，其他股不動
                    qs.append({"code": c, "name": c, "market": "TWSE", "close": px, "prev_close": px, "volume": 1000})
                store.save_day(d, qs)
            p = disposal.Peers(comp, {"9000": {"pe": 20}})
            r = disposal.clause1("9000", "TWSE", days[-1], 11.5, p)
            self.assertAlmostEqual(r["ind_avg"], 15.0)
            self.assertIsNone(r["ind_skip"])
            self.assertGreaterEqual(r["up"]["price"], 13.5)                 # 10 × 1.35
            r2 = disposal.clause1("9000", "TWSE", days[-1], 11.5, disposal.Peers(comp, {"9000": {"pe": 80}}))
            self.assertEqual(r2["ind_skip"], "本益比≥60倍")
            self.assertLess(r2["up"]["price"], 13.5)                         # 只看 32% 與全體
            self.assertEqual(disposal.Peers(comp, {}).info("8000", "TWSE")[1], "同類未達 5 家")
        finally:
            config.HISTORY_DIR = old
            store.trading_days.cache_clear(); store.load_day.cache_clear()
