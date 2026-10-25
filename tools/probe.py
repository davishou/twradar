"""探測資料源（除錯用）：把指定網址的原始回應存到 probe/，由 .github/workflows/probe.yml 上傳成 artifact。
這個環境連不到交易所，靠這個看真實格式。"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from pipeline.http import session  # noqa: E402

OUT = pathlib.Path("probe")
OUT.mkdir(exist_ok=True)
GET = {
    "rev_sii_102_1_0": "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_102_1_0.html",
    "rev_sii_115_9_0": "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_115_9_0.html",
    "rev_sii_115_9_1": "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_115_9_1.html",
    "rev_otc_102_1_0": "https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_102_1_0.html",
    "rev_otc_98_1_0": "https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_98_1_0.html",
    "pe_twse_20161025": "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=20161025&selectType=ALL&response=json",
    "pe_twse_20060104": "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=20060104&selectType=ALL&response=json",
    "pe_tpex_new_2016": "https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date=2016/10/25&response=json",
    "pe_tpex_old_2016": "https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/pera_result.php?l=zh-tw&o=json&d=105/10/25",
    "q_twse_20100105": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20100105&type=ALLBUT0999&response=json",
    "q_twse_20040211": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20040211&type=ALLBUT0999&response=json",
    "q_tpex_new_2010": "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=2010/01/05&type=EW&response=json",
    "q_tpex_old_2010": "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&d=99/01/05&se=EW",
    "inst_twse_20100105": "https://www.twse.com.tw/rwd/zh/fund/T86?date=20100105&selectType=ALLBUT0999&response=json",
    "inst_twse_20130102": "https://www.twse.com.tw/rwd/zh/fund/T86?date=20130102&selectType=ALLBUT0999&response=json",
    "inst_tpex_2010": "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=2010/01/05&response=json",
    "mg_twse_20100105": "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20100105&selectType=ALL&response=json",
    "mg_tpex_2010": "https://www.tpex.org.tw/www/zh-tw/margin/balance?date=2010/01/05&response=json",
    "notice_twse_2010": "https://www.twse.com.tw/rwd/zh/announcement/notice?startDate=20100101&endDate=20100131&response=json",
}
POST = {
    "fin_sii_102Q1": ("https://mopsov.twse.com.tw/mops/web/ajax_t163sb04",
                      {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "isQuery": "Y",
                       "TYPEK": "sii", "year": "102", "season": "01"}),
    "fin_otc_105Q3": ("https://mopsov.twse.com.tw/mops/web/ajax_t163sb04",
                      {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "isQuery": "Y",
                       "TYPEK": "otc", "year": "105", "season": "03"}),
}
summary = {}
for k, u in GET.items():
    try:
        r = session().get(u, timeout=40)
        b = r.content
        (OUT / f"{k}.bin").write_bytes(b[:400000])
        summary[k] = {"status": r.status_code, "bytes": len(b), "ctype": r.headers.get("content-type"), "head": b[:300].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        summary[k] = {"error": str(e)}
    time.sleep(3)
for k, (u, data) in POST.items():
    try:
        r = session().post(u, data=data, timeout=60)
        b = r.content
        (OUT / f"{k}.bin").write_bytes(b[:400000])
        summary[k] = {"status": r.status_code, "bytes": len(b), "head": b[:300].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        summary[k] = {"error": str(e)}
    time.sleep(5)
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
print(json.dumps({k: {x: v.get(x) for x in ("status", "bytes", "error")} for k, v in summary.items()}, ensure_ascii=False, indent=1))
