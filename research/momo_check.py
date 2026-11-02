"""強勢股（最接近一年高點）保守檢查：用前一天資料選股、排除冷門股、不同份數與持有天數
python -m research.momo_check
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import fin_signals as fs
from research import portfolio as pf


def main():
    q = bt.load_quotes()[["date", "code", "adj", "value"]]
    adj = q.pivot(index="date", columns="code", values="adj")
    near = (adj / adj.rolling(250, min_periods=200).max()).shift(1)           # 前一天收盤就知道
    liq = q.pivot(index="date", columns="code", values="value").rolling(20, min_periods=15).mean().shift(1)
    # 每月第一個交易日換股（和營收無關的純強勢股），也看營收版本
    days = adj.index[adj.index >= "2005-03-01"]
    first = pd.Series(days).groupby([days.year, days.month]).first().values
    rows = []
    for d in first:
        s = near.loc[d].dropna()
        lq = liq.loc[d].reindex(s.index)
        rows.append(pd.DataFrame({"code": s.index, "date": d, "near": s.values, "liq": lq.values}))
    ev = pd.concat(rows)
    print(f"每月換股 {len(first)} 次，2005/3 ~ 2026")
    for minliq, lab in ((0, "不限成交金額"), (2e7, "20 日均成交 ≥ 2 千萬"), (1e8, "≥ 1 億")):
        e = ev[ev["liq"].fillna(0) >= minliq].assign(score=lambda x: x["near"])
        for sl in (10, 20):
            for hold in (20, 60):
                res = pf.simulate(e[["code", "date", "score"]], hold, sl, start="2005-03-01")
                a = pf.simulate(e[["code", "date", "score"]], hold, sl, start="2005-03-01", end="2015-12-31")["curve"]
                b = pf.simulate(e[["code", "date", "score"]], hold, sl, start="2016-01-01")["curve"]
                print(pf.fmt(res, f"{lab} {sl}份") + f"｜前段05~15 年化 {a['cagr']:+.1%} 回落 {a['mdd']:+.1%}｜後段16~26 年化 {b['cagr']:+.1%} 回落 {b['mdd']:+.1%}")
        res = pf.simulate(e[["code", "date", "score"]], 20, 20, start="2005-03-01")
        print("   20份持有20日 每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
    print("   加權每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly_taiex"].items()))
    # 營收加速＋強勢（前一天資料、≥2千萬）
    r, rs = fs.revenue()
    e = pf.events_at_next_close(r.loc[rs["rev_accel"].fillna(False), ["code", "deadline"]])
    e = e[e["date"] >= "2013-02-01"]
    e["score"] = [near.at[d, c] if c in near.columns else np.nan for d, c in zip(e["date"], e["code"])]
    e["liq"] = [liq.at[d, c] if c in liq.columns else np.nan for d, c in zip(e["date"], e["code"])]
    e = e[e["liq"].fillna(0) >= 2e7].assign(score=lambda x: x["score"].fillna(-1))
    m = ev[(ev["date"] >= "2013-02-01") & (ev["liq"].fillna(0) >= 2e7)].assign(score=lambda x: x["near"])
    for hold in (20, 60):
        print(pf.fmt(pf.simulate(e[["code", "date", "score"]], hold, 20, start="2013-02-01"), "營收加速＋強勢（≥2千萬）20份"))
        print(pf.fmt(pf.simulate(m[["code", "date", "score"]], hold, 20, start="2013-02-01"), "純強勢 同期（≥2千萬）20份"))


if __name__ == "__main__":
    main()
