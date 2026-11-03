"""第二輪探測：標借（證交所 BFIB8U、櫃買）、變更交易（證交所 TWT85U、櫃買）歷史介面"""
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from pipeline.http import session  # noqa: E402

OUT = pathlib.Path("probe")
OUT.mkdir(exist_ok=True)
S = session()
summary = {}
GET = {
    "tw_bfib8u_range": "https://www.twse.com.tw/rwd/zh/marginTrading/BFIB8U?startDate=20120601&endDate=20120630&response=json",
    "tw_bfib8u_date": "https://www.twse.com.tw/rwd/zh/marginTrading/BFIB8U?date=20120621&response=json",
    "tw_bfib8u_ex": "https://www.twse.com.tw/rwd/zh/exchangeReport/BFIB8U?startDate=20120601&endDate=20120630&response=json",
    "tw_bfib8u_page": "https://www.twse.com.tw/zh/page/trading/exchange/BFIB8U.html",
    "tw_twt85u_date": "https://www.twse.com.tw/rwd/zh/exchangeReport/TWT85U?date=20130403&response=json",
    "tw_twt85u_range": "https://www.twse.com.tw/rwd/zh/exchangeReport/TWT85U?startDate=20130101&endDate=20131231&response=json",
    "tw_twt85u_now": "https://www.twse.com.tw/rwd/zh/exchangeReport/TWT85U?response=json",
    "tw_twt85u_page": "https://www.twse.com.tw/zh/page/trading/exchange/TWT85U.html",
    "tp_main_js": "https://www.tpex.org.tw/rsrc/js/main.js",
    "tp_global_js": "https://www.tpex.org.tw/rsrc/asset/js/global.js",
    "tp_lend_new": "https://www.tpex.org.tw/www/zh-tw/margin/lend?date=2012/06/21&response=json",
    "tp_lend_new2": "https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=2012/06/21&response=json",
    "tp_lend_old": "https://www.tpex.org.tw/web/stock/margin_trading/lend/lend_result.php?l=zh-tw&d=101/06/21&o=json",
    "tp_cmode_new": "https://www.tpex.org.tw/www/zh-tw/bulletin/cmode?date=2013/04/03&response=json",
    "tp_cmode_new2": "https://www.tpex.org.tw/www/zh-tw/afterTrading/cmode?date=2013/04/03&response=json",
    "tp_cmode_old": "https://www.tpex.org.tw/web/stock/aftertrading/cmode/cmode_result.php?l=zh-tw&d=102/04/03&o=json",
    "tp_disp_2004": "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?startDate=2004/01/01&endDate=2004/12/31&response=json",
    "tp_attn_2004": "https://www.tpex.org.tw/www/zh-tw/bulletin/attention?startDate=2004/01/01&endDate=2004/01/31&response=json",
}
for k, u in GET.items():
    try:
        r = S.get(u, timeout=40)
        t = r.content
        (OUT / f"{k}.txt").write_bytes(t[:3_000_000])
        summary[k] = {"status": r.status_code, "len": len(t), "head": t[:600].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        summary[k] = {"err": str(e)}
    time.sleep(1.5)
for f in ("tp_main_js", "tp_global_js", "tw_bfib8u_page", "tw_twt85u_page"):
    p = OUT / f"{f}.txt"
    if p.exists():
        s = p.read_text("utf-8", "replace")
        summary[f"urls_{f}"] = sorted(set(re.findall(r"""["'](/(?:www|rwd|web)/[^"'\s]+)["']""", s)))[:200]
        summary[f"kw_{f}"] = re.findall(r".{0,80}(?:標借|lend|cmode|變更交易).{0,80}", s)[:40]
(OUT / "summary2.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
