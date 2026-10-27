import json,time,re,requests
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36","Referer":"https://www.cnyes.com/"}
out={}
def g(k,u,**kw):
    try:
        r=requests.get(u,headers=H,timeout=30,**kw); out[k]={"code":r.status_code,"body":r.text[:600]}; return r
    except Exception as e: out[k]={"err":str(e)[:150]}
for u in ["https://invest.cnyes.com/indices/major","https://www.cnyes.com/global/IndexImmediateQuotedPrice/","https://invest.cnyes.com/indices/major/asia"]:
    r=g(u,u)
    if r is not None and r.ok: out[u]["syms"]=sorted(set(re.findall(r'GI:[A-Z0-9_.]+:INDEX|[A-Z]{2,4}:[A-Z0-9_.]+:INDEX',r.text)))[:300]
now=int(time.time())
for s in ["GI:DJI:INDEX","GI:VNINDEX:INDEX","GI:VNI:INDEX","GI:SET:INDEX","GI:PCOMP:INDEX","GI:PSEI:INDEX","GI:SASEIDX:INDEX","GI:TASI:INDEX","GI:WIG20:INDEX","GI:WIG:INDEX","GI:IMOEX:INDEX","GI:RTSI:INDEX","GI:SHSZ300:INDEX","GI:CSI300:INDEX","GI:OBX:INDEX","GI:OSEBX:INDEX","TWS:OTC01:INDEX","TWG:OTC01:INDEX"]:
    r=g("cn:"+s,"https://ws.api.cnyes.com/ws/api/v1/charting/history",params={"resolution":"D","symbol":s,"from":now,"to":now-86400*365*40,"quote":1})
    try:
        d=r.json().get("data",{}); t=d.get("t") or []
        out["cn:"+s]={"code":r.status_code,"n":len(t),"first":time.strftime("%Y-%m-%d",time.gmtime(min(t))) if t else None,"last":time.strftime("%Y-%m-%d",time.gmtime(max(t))) if t else None,"c":(d.get("c") or [None])[:2],"body":r.text[:200] if not t else ""}
    except Exception as e: pass
    time.sleep(0.5)
for k,u in [("tpex_inxh","https://www.tpex.org.tw/www/zh-tw/indexInfo/inxh?date=2026/09/01&response=json"),
            ("tpex_inx","https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date=2026/10/22&response=json"),
            ("tpex_legacy","https://www.tpex.org.tw/web/stock/iNdex_info/inxh/Inx_result.php?l=zh-tw&d=115/09"),
            ("tpex_old2000","https://www.tpex.org.tw/www/zh-tw/indexInfo/inxh?date=2000/01/01&response=json")]:
    g(k,u)
json.dump(out,open("probe/cnyes.json","w"),indent=0,ensure_ascii=False)
