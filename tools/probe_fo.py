"""探測期交所期貨／選擇權每日行情下載與 Yahoo 盤中資料（結果寫到 probe/）"""
import json, os, time
import requests
os.makedirs("probe", exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
out = {}
def tf(kind, cid, a, b):
    url = f"https://www.taifex.com.tw/cht/3/{kind}DataDown"
    try:
        r = S.post(url, data={"down_type": "1", "commodity_id": cid, "commodity_id2": "", "queryStartDate": a, "queryEndDate": b}, timeout=60)
        raw = r.content
        try: txt = raw.decode("big5", "replace")
        except Exception: txt = raw.decode("utf-8", "replace")
        lines = txt.splitlines()
        return {"status": r.status_code, "bytes": len(raw), "ctype": r.headers.get("content-type"), "n_lines": len(lines), "head": lines[:6], "tail": lines[-2:]}
    except Exception as e:
        return {"err": repr(e)}
for kind, cid in (("fut", "TX"), ("opt", "TXO")):
    for a, b in (("2005/03/01", "2005/03/31"), ("2012/03/01", "2012/03/31"), ("2020/03/01", "2020/03/31"), ("2026/10/01", "2026/10/31"), ("2020/01/01", "2020/12/31")):
        out[f"{kind}_{cid}_{a}_{b}"] = tf(kind, cid, a, b); time.sleep(3)
def yh(sym, interval, rng):
    try:
        r = S.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"interval": interval, "range": rng}, timeout=60)
        j = r.json()["chart"]["result"][0]
        ts = j["timestamp"]; q = j["indicators"]["quote"][0]
        return {"n": len(ts), "first": ts[0], "last": ts[-1], "sample": [[ts[i], q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]] for i in list(range(8)) + list(range(len(ts) - 8, len(ts)))], "meta_tz": j["meta"].get("exchangeTimezoneName")}
    except Exception as e:
        return {"err": repr(e), "text": getattr(r, "text", "")[:200] if "r" in dir() else ""}
for sym in ("%5ETWII", "0050.TW"):
    for interval, rng in (("60m", "730d"), ("30m", "60d"), ("5m", "60d"), ("1h", "2y")):
        out[f"yh_{sym}_{interval}_{rng}"] = yh(sym, interval, rng); time.sleep(1)
json.dump(out, open("probe/fo.json", "w"), ensure_ascii=False, indent=1)
