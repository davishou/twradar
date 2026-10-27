import json,time,requests
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
C="""^GSPTSE ^BVSP ^MXX ^MERV ^IPSA ^SPCOSLCP ^AXJO ^NZ50 ^STI ^KLSE ^JKSE ^SET.BK PSEI.PS ^VNINDEX.VN VNINDEX ^NSEI 399001.SZ 000300.SS ^TWOII ^HSCE
^AEX ^IBEX FTSEMIB.MI ^SSMI ^OMX ^OSEAX OBX.OL ^BFX ^ATX PSI20.LS ^ISEQ WIG20.WA ^WIG20 IMOEX.ME XU100.IS ^TA125.TA TA35.TA ^CASE30 ^J203.JO ^JN0U.JO ^TASI.SR ^DFMGI ^KSE ^XU100 ^PX ^BUX.BD ^OMXC25 ^OMXH25 ^RUT ^NYA
HRC=F CT=F CC=F SB=F LE=F HE=F RB=F HO=F UX=F LBR=F LBS=F ZO=F ZR=F OJ=F ZL=F ZM=F KE=F GF=F MGC=F SIL=F ETH-USD
KRW=X HKD=X SGD=X AUDUSD=X GBPUSD=X INR=X CHF=X CAD=X BRL=X MXN=X ZAR=X TRY=X RUB=X VND=X THB=X IDR=X MYR=X PHP=X NZDUSD=X EURJPY=X
^FVX ^TYX ^IRX ^GVZ ^OVX""".split()
out={}
for s in C:
    try:
        r=requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}",params={"period1":-2208988800,"period2":int(time.time()),"interval":"1d"},headers=H,timeout=30)
        res=(r.json().get("chart") or {}).get("result") if r.status_code==200 else None
        if not res: out[s]={"code":r.status_code}; continue
        m=res[0].get("meta",{}); ts=res[0].get("timestamp") or []
        cl=[x for x in ((res[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or [] if x is not None]
        out[s]={"n":len(ts),"first":time.strftime("%Y-%m-%d",time.gmtime(ts[0])) if ts else None,"last":time.strftime("%Y-%m-%d",time.gmtime(ts[-1])) if ts else None,
                "px":m.get("regularMarketPrice"),"cur":m.get("currency"),"name":m.get("longName") or m.get("shortName"),"nclose":len(cl)}
    except Exception as e: out[s]={"err":str(e)[:80]}
    time.sleep(0.5)
json.dump(out,open("probe/sym.json","w"),indent=0,ensure_ascii=False)
