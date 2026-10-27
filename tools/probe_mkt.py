import json,time,requests
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36","Accept":"application/json, text/plain, */*"}
out={}
now=int(time.time())
def g(k,u,**kw):
    try:
        r=requests.get(u,headers={**H,**kw.pop("hd",{})},timeout=40,**kw); out[k]={"code":r.status_code,"len":len(r.text),"body":r.text[:500]}
    except Exception as e: out[k]={"err":str(e)[:200]}
# Russia MOEX ISS
g("moex_imoex","https://iss.moex.com/iss/history/engines/stock/markets/index/securities/IMOEX.json?from=1997-01-01&iss.meta=off&history.columns=TRADEDATE,CLOSE")
g("moex_rtsi","https://iss.moex.com/iss/history/engines/stock/markets/index/securities/RTSI.json?from=1995-01-01&iss.meta=off&history.columns=TRADEDATE,CLOSE")
g("moex_imoex_last","https://iss.moex.com/iss/history/engines/stock/markets/index/securities/IMOEX.json?from=2026-10-01&iss.meta=off&history.columns=TRADEDATE,CLOSE")
# Vietnam
g("vn_entrade",f"https://services.entrade.com.vn/chart-api/v2/ohlcs/index?from=0&to={now}&symbol=VNINDEX&resolution=1D")
g("vn_vndirect",f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol=VNINDEX&from=946684800&to={now}")
g("vn_ssi",f"https://iboard-api.ssi.com.vn/statistics/charts/history?resolution=1D&symbol=VNINDEX&from=946684800&to={now}")
g("vn_vps",f"https://histdatafeed.vps.com.vn/tradingview/history?symbol=VNINDEX&resolution=D&from=946684800&to={now}")
# Norway Euronext
g("nor_euronext_max","https://live.euronext.com/intraday_chart/getChartData/NO0007035327-XOSL/max")
g("nor_euronext_hist","https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax/NO0007035327-XOSL?format=csv&decimal_separator=.&date_form=d/m/Y&op=&adjusted=Y&base100=&startdate=2000-01-01&enddate=2026-10-27")
# Saudi
g("ksa_yahoo_TASI",f"https://query1.finance.yahoo.com/v8/finance/chart/%5ETASI?range=max&interval=1d")
g("ksa_tadawul","https://www.saudiexchange.sa/tadawul.eportal.theme.helper/TickerServlet")
g("ksa_argaam","https://www.argaam.com/en/company/companies-prices-chart/3/1")
g("ksa_etf_yahoo",f"https://query1.finance.yahoo.com/v8/finance/chart/KSA?range=5d&interval=1d")
for k,v in out.items():
    if v.get("body") and len(v["body"])>=500: v["body"]=v["body"][:500]
json.dump(out,open("probe/src4.json","w"),indent=0,ensure_ascii=False)
