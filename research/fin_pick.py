"""財報訊號：資金有限（10／20 份）時，同一天訊號太多要怎麼挑？

比較：隨機挑（10 次取中位數）、挑成交金額最大的（大型股）、挑營收年增最高的、挑股價離一年高點最近的（強勢）
python -m research.fin_pick
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import fin_signals as fs
from research import portfolio as pf


def main():
    q = bt.load_quotes()[["date", "code", "value", "adj"]]
    v20 = q.pivot(index="date", columns="code", values="value").rolling(20, min_periods=10).mean()
    adj = q.pivot(index="date", columns="code", values="adj")
    hi250 = adj.rolling(250, min_periods=120).max()
    near = adj / hi250
    r, rs = fs.revenue()
    f, fsig = fs.fin()
    sets = {"rev_high": (r, rs["rev_high"], "yoy"), "rev_accel": (r, rs["rev_accel"], "yoy"),
            "gm_jump": (f, fsig["gm_jump"], None), "turn_prof": (f, fsig["turn_prof"], None)}
    for k, (df, m, ycol) in sets.items():
        e = df.loc[m.fillna(False), ["code", "deadline"] + ([ycol] if ycol else [])]
        e = pf.events_at_next_close(e[e["deadline"] >= "2013-01-01"])
        look = lambda mat: [mat.at[d, c] if c in mat.columns and d in mat.index else np.nan for d, c in zip(e["date"], e["code"])]  # noqa: E731
        e["liq"], e["near"] = look(v20), look(near)
        print(f"\n== {fs.NAMES[k]}（{len(e)} 次） ==")
        for hold in (60, 120):
            a = pf.simulate(e[["code", "date"]], hold, None, start="2013-02-01")
            print(pf.fmt(a, "  全買"))
            for sl in (10, 20):
                rnd = [pf.simulate(e[["code", "date"]], hold, sl, start="2013-02-01", seed=s)["curve"] for s in range(10)]
                cg = sorted(x["cagr"] for x in rnd)
                md = sorted(x["mdd"] for x in rnd)
                print(f"  {sl}份 隨機挑 持有{hold}日：年化 中位 {np.median(cg):+.1%}（最差 {cg[0]:+.1%}～最好 {cg[-1]:+.1%}），最大回落 中位 {np.median(md):+.1%}")
                for lab, col in (("成交金額最大", "liq"), ("最接近一年高點", "near")) + ((("營收年增最高", ycol),) if ycol else ()):
                    x = e[["code", "date"]].assign(score=e[col].fillna(-1e18))
                    print(pf.fmt(pf.simulate(x, hold, sl, start="2013-02-01"), f"  {sl}份 挑{lab}"))


if __name__ == "__main__":
    main()
