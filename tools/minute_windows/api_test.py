"""永豐 API 測試（開通正式下單用）。不會下真的單。

用法（在 D:\\twradar 執行）：
    py -3.12 tools\\minute_windows\\api_test.py test     模擬模式登入＋下一張「模擬」股票單（產生測試報告）
    py -3.12 tools\\minute_windows\\api_test.py check    正式模式登入，只看 signed（是否開通），不下單

金鑰讀 D:\\twradar-minute\\trade.env（要勾「交易」權限的那把 Key，跟抓資料的分開）：
    SHIOAJI_API_KEY=...
    SHIOAJI_SECRET_KEY=...
測試時段：週一~五 08:00~20:00（18:00 後限台灣 IP）；要先在簽署中心簽完證券 API 同意書再測。
"""
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
ENV = Path(os.environ.get("TRADE_ENV", r"D:\twradar-minute\trade.env"))


def keys():
    if not ENV.exists():
        sys.exit(f"找不到 {ENV}，請先建立並填入有「交易」權限的 API Key")
    kv = {}
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip().strip('"')
    return kv["SHIOAJI_API_KEY"], kv["SHIOAJI_SECRET_KEY"]


def stock(api, code):
    try:
        return api.contracts.get(code)
    except Exception:
        return api.Contracts.Stocks[code]


def main(mode):
    import shioaji as sj
    print("shioaji 版本", sj.__version__)
    key, secret = keys()
    if mode == "test":
        api = sj.Shioaji(simulation=True)            # 模擬模式：不會動到真的錢
        accounts = api.login(api_key=key, secret_key=secret)
        print("登入成功（模擬）：", accounts)
        c = stock(api, "2890")
        px = getattr(c, "reference", 0) or 28
        order = sj.StockOrder(action=sj.Action.Buy, price=px, quantity=1,
                              price_type=sj.StockPriceType.LMT, order_type=sj.OrderType.ROD,
                              order_lot=sj.StockOrderLot.Common, order_cond=sj.StockOrderCond.Cash,
                              account=api.stock_account)
        time.sleep(1.5)
        trade = api.place_order(c, order)
        print("模擬下單結果：", trade.status.status if hasattr(trade, "status") else trade)
        time.sleep(1.5)
        api.logout()
        print("\n完成。等 5 分鐘以上，再執行：py -3.12 tools\\minute_windows\\api_test.py check")
    elif mode == "check":
        api = sj.Shioaji()                           # 正式模式，只登入看狀態
        accounts = api.login(api_key=key, secret_key=secret)
        for a in accounts:
            kind = type(a).__name__
            print(f"{kind}: signed = {getattr(a, 'signed', '?')}")
        api.logout()
        print("\n證券帳戶 signed = True 就是開通了，可以進行下一步。")
    else:
        sys.exit("用法：api_test.py test 或 api_test.py check")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
