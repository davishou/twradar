import json,time,requests
out={}
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
for s in ["GC=F","^GSPC","TIO=F","^TWII","DX-Y.NYB"]:
    for host in ["query1","query2"]:
        try:
            r=requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{s}",params={"period1":0,"period2":int(time.time()),"interval":"1d","events":"div,split"},headers=H,timeout=30)
            j=r.json() if r.status_code==200 else None
            res=(j or {}).get("chart",{}).get("result") or [{}]
            ts=res[0].get("timestamp") or []
            out[f"{s}@{host}"]={"code":r.status_code,"n":len(ts),"first":ts[0] if ts else None,"last":ts[-1] if ts else None,"meta":{k:res[0].get("meta",{}).get(k) for k in ("currency","regularMarketPrice","exchangeName","firstTradeDate")},"body":r.text[:200] if r.status_code!=200 else ""}
        except Exception as e: out[f"{s}@{host}"]=str(e)
        time.sleep(1)
try:
    import subprocess;subprocess.run("pip install -q yfinance",shell=True)
    import yfinance as yf
    df=yf.download(["GC=F","^N225"],period="max",progress=False,auto_adjust=False)
    out["yf"]={"rows":len(df),"first":str(df.index[0]),"last":str(df.index[-1]),"ver":yf.__version__}
except Exception as e: out["yf"]=repr(e)
for u in ["https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&file_type=json","https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO"]:
    try:
        r=requests.get(u,headers=H,timeout=30);out[u]={"code":r.status_code,"body":r.text[:150]}
    except Exception as e: out[u]=str(e)
json.dump(out,open("probe/yahoo.json","w"),indent=1,ensure_ascii=False)
