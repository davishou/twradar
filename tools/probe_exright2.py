import json, os, time, requests
os.makedirs("probe", exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
out = {}
U = "https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php"
for d, ed in (("94/07/01", "94/07/31"), ("094/07/01", "094/07/31"), ("99/07/01", "99/07/31"), ("100/07/01", "100/07/31"), ("94/07/01", "94/07/15")):
    for extra in ({}, {"o": "json"}):
        r = S.get(U, params={"l": "zh-tw", "d": d, "ed": ed, **extra}, timeout=60)
        out[f"{d}~{ed} {extra}"] = r.text[:600]
        time.sleep(2)
for u in ("https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ.php?l=zh-tw",):
    r = S.get(u, timeout=60); out["page"] = r.text[:4000]
json.dump(out, open("probe/exright2.json", "w"), ensure_ascii=False, indent=1)
