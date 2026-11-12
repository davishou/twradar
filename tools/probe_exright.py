"""探測證交所 TWT49U（除權除息計算結果表）與櫃買除權息結果的格式 → probe/exright.json"""
import json, os, time
import requests
os.makedirs("probe", exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
out = {}
def rec(k, r):
    try:
        txt = r.content.decode("utf-8")
    except Exception:
        txt = r.content.decode("big5", "replace")
    out[k] = {"status": r.status_code, "ctype": r.headers.get("content-type"), "len": len(r.content), "head": txt[:1800]}
for a, b in (("20240901", "20240930"), ("20050101", "20051231"), ("20240101", "20241231")):
    for url in ("https://www.twse.com.tw/rwd/zh/exRight/TWT49U", "https://www.twse.com.tw/exchangeReport/TWT49U"):
        try:
            rec(f"twse {url[-30:]} {a}-{b}", S.get(url, params={"startDate": a, "endDate": b, "response": "json", "strDate": a, "endDate": b}, timeout=60))
        except Exception as e:
            out[f"twse {url} {a}"] = repr(e)
        time.sleep(3)
for d, ed in (("113/09/01", "113/09/30"), ("094/01/01", "094/12/31")):
    for url, kw in (("https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php", {"l": "zh-tw", "d": d, "ed": ed}),
                    ("https://www.tpex.org.tw/www/zh-tw/exRight/dailyQuo", {"startDate": d, "endDate": ed, "response": "json"}),
                    ("https://www.tpex.org.tw/www/zh-tw/exRight/exDailyQ", {"startDate": d, "endDate": ed, "response": "json"})):
        for meth in ("get", "post"):
            try:
                r = S.get(url, params=kw, timeout=60) if meth == "get" else S.post(url, data=kw, timeout=60)
                rec(f"tpex {meth} {url[-40:]} {d}", r)
            except Exception as e:
                out[f"tpex {meth} {url} {d}"] = repr(e)
            time.sleep(2)
json.dump(out, open("probe/exright.json", "w"), ensure_ascii=False, indent=1)
