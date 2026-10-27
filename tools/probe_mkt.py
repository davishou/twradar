import json,time,requests
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36","Referer":"https://www.cnyes.com/"}
out={}
def hist(sym):
    frm=int(time.time()); allt=[]; pages=0
    while pages<12:
        r=requests.get("https://ws.api.cnyes.com/ws/api/v1/charting/history",params={"resolution":"D","symbol":sym,"from":frm,"to":0},headers=H,timeout=30)
        t=(r.json().get("data") or {}).get("t") or []
        pages+=1
        if not t: break
        allt+=t; frm=min(t)-1
        time.sleep(0.4)
    return {"pages":pages,"n":len(allt),"first":time.strftime("%Y-%m-%d",time.gmtime(min(allt))) if allt else None,"last":time.strftime("%Y-%m-%d",time.gmtime(max(allt))) if allt else None}
for s in ["GI:SET:INDEX","GI:PCOMP:INDEX","GI:WIG:INDEX","GI:CSI300:INDEX","TWS:OTC01:INDEX","GI:RTSI:INDEX","GI:VNI:INDEX","GI:VN30:INDEX","GI:HNX:INDEX","GI:TASI:INDEX","GI:OSEBX:INDEX","GI:OBXP:INDEX","GI:WIG20:INDEX","GI:MOEX:INDEX","GI:IMOEX:INDEX","GI:SASE:INDEX"]:
    try: out[s]=hist(s)
    except Exception as e: out[s]=str(e)[:100]
for d in ["1995/01/05","2000/01/05","2010/06/01"]:
    try:
        r=requests.get(f"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date={d}&response=json",headers=H,timeout=30); out["tpex "+d]=r.text[:300]
    except Exception as e: out["tpex "+d]=str(e)[:100]
json.dump(out,open("probe/cnyes2.json","w"),indent=0,ensure_ascii=False)
