"""探測歷史發行股數來源（證交所外資持股統計 MI_QFIIS、櫃買外資持股）→ probe/shares.json"""
import json, os, time, requests
os.makedirs("probe", exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"
out = {}
def rec(k, r):
    out[k] = {"status": r.status_code, "len": len(r.content), "head": r.content.decode("utf-8", "replace")[:1500]}
for d in ("20050301", "20100301", "20200302", "20261102"):
    for u in ("https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS", "https://www.twse.com.tw/fund/MI_QFIIS"):
        try: rec(f"twse {u[-25:]} {d}", S.get(u, params={"date": d, "selectType": "ALLBUT0999", "response": "json"}, timeout=60))
        except Exception as e: out[f"twse {u} {d}"] = repr(e)
        time.sleep(3)
for d in ("094/03/01", "099/03/01", "109/03/02", "115/11/02"):
    for u, kw in (("https://www.tpex.org.tw/web/stock/3insti/qfii/qfii_result.php", {"l": "zh-tw", "d": d}),
                  ("https://www.tpex.org.tw/www/zh-tw/insti/qfii", {"date": d, "response": "json"})):
        for m in ("get", "post"):
            try:
                r = S.get(u, params=kw, timeout=60) if m == "get" else S.post(u, data=kw, timeout=60)
                rec(f"tpex {m} {u[-30:]} {d}", r)
            except Exception as e: out[f"tpex {m} {u} {d}"] = repr(e)
            time.sleep(2)
json.dump(out, open("probe/shares.json", "w"), ensure_ascii=False, indent=1)
