"""探測回測用的歷史資料源（處置上櫃歷史、標借、重大訊息歷史、變更交易方法）。結果寫到 probe/。
python tools/probe_bt.py"""
import json
import pathlib
import re
import sys
import time
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from pipeline.http import session  # noqa: E402
from pipeline import sources  # noqa: E402

OUT = pathlib.Path("probe")
OUT.mkdir(exist_ok=True)
S = session()
summary = {}

GET = {
    # 櫃買處置（新舊站猜測）
    "tpex_disp_new1": "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?startDate=2010/01/01&endDate=2010/03/31&response=json",
    "tpex_disp_new2": "https://www.tpex.org.tw/www/zh-tw/announce/market/disposal?startDate=2010/01/01&endDate=2010/03/31&response=json",
    "tpex_disp_old": "https://www.tpex.org.tw/web/bulletin/disposal_information/disposal_information_result.php?l=zh-tw&sd=99/01/01&ed=99/03/31&o=json",
    "tpex_disp_page": "https://www.tpex.org.tw/zh-tw/announce/market/disposal.html",
    "tpex_attn_new": "https://www.tpex.org.tw/www/zh-tw/bulletin/attention?startDate=2010/01/01&endDate=2010/01/31&response=json",
    "tpex_attn_page": "https://www.tpex.org.tw/zh-tw/announce/market/attention.html",
    # 標借
    "tpex_sbl_openapi": "https://www.tpex.org.tw/openapi/v1/tpex_margin_sbl",
    "tpex_swagger": "https://www.tpex.org.tw/openapi/swagger.json",
    "twse_swagger": "https://openapi.twse.com.tw/v1/swagger.json",
    "twse_margin_page": "https://www.twse.com.tw/zh/trading/margin/mi-margn.html",
    "twse_sitemap": "https://www.twse.com.tw/zh/sitemap.html",
    "tpex_sitemap": "https://www.tpex.org.tw/zh-tw/sitemap.html",
    # 變更交易方法
    "twse_change_page": "https://www.twse.com.tw/zh/announcement/change/twtb7u.html",
}
for k, u in GET.items():
    try:
        r = S.get(u, timeout=40)
        t = r.content
        (OUT / f"{k}.txt").write_bytes(t[:3_000_000])
        summary[k] = {"status": r.status_code, "len": len(t), "head": t[:300].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        summary[k] = {"err": str(e)}
    time.sleep(1.5)

# 櫃買處置：POST 版本
for k, (u, data) in {
    "tpex_disp_post": ("https://www.tpex.org.tw/www/zh-tw/bulletin/disposal", {"startDate": "2010/01/01", "endDate": "2010/03/31", "response": "json"}),
    "tpex_disp_post2": ("https://www.tpex.org.tw/www/zh-tw/announce/market/disposal", {"startDate": "2010/01/01", "endDate": "2010/03/31", "response": "json"}),
}.items():
    try:
        r = S.post(u, data=data, timeout=40)
        (OUT / f"{k}.txt").write_bytes(r.content[:3_000_000])
        summary[k] = {"status": r.status_code, "len": len(r.content), "head": r.content[:300].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        summary[k] = {"err": str(e)}
    time.sleep(1.5)

# 重大訊息歷史：能回到多早、含不含內文
for d in (date(2005, 3, 1), date(2009, 6, 3), date(2012, 5, 24), date(2013, 3, 13)):
    rows = sources.fetch_material_mops(d)
    key = f"mops_{d.isoformat()}"
    if rows is None:
        summary[key] = None
    else:
        hits = [r for r in rows if re.search(r"公開收購|變更交易|全額交割|普通交割|分盤", r["subject"] + r["body"])]
        summary[key] = {"n": len(rows), "hits": [{"code": r["code"], "subject": r["subject"], "body": r["body"][:500]} for r in hits[:8]]}
    time.sleep(6)

# 在下載的網頁裡找和標借、變更交易有關的連結
for f in OUT.glob("*.txt"):
    s = f.read_text("utf-8", "replace")
    links = sorted(set(re.findall(r'href="([^"]+)"[^>]*>\s*([^<]*(?:標借|變更交易|全額交割|公開收購|處置|注意)[^<]*)<', s)))
    if links:
        summary[f"links_{f.stem}"] = links[:80]
    if "swagger" in f.stem:
        try:
            js = json.loads(s)
            summary[f"paths_{f.stem}"] = [p for p in js.get("paths", {}) if re.search(r"sbl|lend|borrow|margin|warn|disposal|change|punish|tender|full", p, re.I)]
        except Exception:  # noqa: BLE001
            pass

(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
print(json.dumps(summary, ensure_ascii=False)[:3000])
