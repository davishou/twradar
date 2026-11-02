"""鄭詩翰 CB 訊號的「實際買 CB」資金曲線（2026-11-02）

訊號定義同 pipeline/cbsig.py（網站每日標記用同一份），事件表來自 research/cb_signals.panel()/events()。
做法：訊號隔天收盤買 CB、持有 20／60 日；CB 中途下市（贖回、轉換完、到期、賣回）用最後價出場。
成本：照股票算（手續費 0.1425%×2＋0.3% 稅，CB 實際免證交稅，偏保守）＋每邊滑價 0.5%（CB 成交量小）。
資金 10 份；同天太多訊號隨機挑。對照：每月第一個交易日隨機買 10 檔 CB（價格 ≤ 120）。

python -m research.cb_portfolio
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline import cbsig
from research import cb_signals as cs
from research import portfolio as pf

SLIP = 0.005


def cb_mats(q):
    px = q.pivot(index="date", columns="code", values="price").sort_index()
    raw = q.pivot(index="date", columns="code", values="close").sort_index()
    # 只在 CB 還在市場上的期間保留價格（ffill 的 price 已只到最後一列）
    r = px.pct_change(fill_method=None).clip(-0.11, 0.11)
    pxc = (1 + r.fillna(0)).cumprod().where(px.notna())
    del raw
    return pxc, r


def main():
    q = cs.panel()
    ev = cs.events(q)
    mats = cb_mats(q)
    days = mats[0].index
    i = days.searchsorted(ev["date"].values, side="right")
    ok = i < len(days)
    ev = ev[ok].assign(date=days[i[ok]])           # 隔天收盤買
    start = str(ev["date"].min().date())
    print(f"CB 事件 {start} ~ {ev['date'].max().date()}")
    # 對照：每月第一個交易日、價格 ≤ 120 的 CB 隨機買
    d = days[days >= start]
    first = pd.Series(d).groupby([d.year, d.month]).first().values
    base = q[q["date"].isin(first) & (q["price"] <= 120)][["code", "date"]]
    base = base.assign(date=days[days.searchsorted(base["date"].values, side="right").clip(max=len(days) - 1)])
    rows = [("對照：每月隨機買 CB(≤120)", base)] + [(f"{n}（{kind}）", ev[ev["sig"] == k][["code", "date"]]) for k, n, kind, *_ in cbsig.SIGNALS]
    for lab, e in rows:
        for hold in (20, 60):
            res = pf.simulate(e, hold, 10, slip=SLIP, mats=mats, start=start)
            a = pf.simulate(e, hold, 10, slip=SLIP, mats=mats, start=start, end="2022-06-30")["curve"]
            b = pf.simulate(e, hold, 10, slip=SLIP, mats=mats, start="2022-07-01")["curve"]
            print(pf.fmt(res, lab).split("（加權")[0] + f"｜前段 {a['cagr']:+.1%}/{a['mdd']:+.0%}｜後段 {b['cagr']:+.1%}/{b['mdd']:+.0%}")
            if hold == 60:
                print("     每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
    # 合併兩個通過的訊號（站上轉換價、快到期條件）
    both = ev[ev["sig"].isin(["convup", "expiry"])][["code", "date"]]
    for sl in (5, 10):
        res = pf.simulate(both, 60, sl, slip=SLIP, mats=mats, start=start)
        print(pf.fmt(res, f"站上轉換價＋快到期 合併 {sl}份").split("（加權")[0])
        print("     每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
    print("     加權：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly_taiex"].items()))


if __name__ == "__main__":
    main()
