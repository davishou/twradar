"""最終候選：營收年增加速＋最接近一年高點（前一天資料、排除冷門股）的穩定度
python -m research.combo_check
"""
from __future__ import annotations

import numpy as np

from pipeline import backtest as bt
from research import fin_signals as fs
from research import portfolio as pf


def main():
    q = bt.load_quotes()[["date", "code", "adj", "value"]]
    adj = q.pivot(index="date", columns="code", values="adj")
    near = (adj / adj.rolling(250, min_periods=200).max()).shift(1)
    liq = q.pivot(index="date", columns="code", values="value").rolling(20, min_periods=15).mean().shift(1)
    r, rs = fs.revenue()
    for key in ("rev_accel", "rev_high", "rev_turn"):
        e0 = pf.events_at_next_close(r.loc[rs[key].fillna(False), ["code", "deadline"]])
        e0 = e0[e0["date"] >= "2013-02-01"]
        e0["score"] = [near.at[d, c] if c in near.columns else np.nan for d, c in zip(e0["date"], e0["code"])]
        e0["liq"] = [liq.at[d, c] if c in liq.columns else np.nan for d, c in zip(e0["date"], e0["code"])]
        for minliq, lab in ((2e7, "≥2千萬"), (1e8, "≥1億")):
            e = e0[e0["liq"].fillna(0) >= minliq].assign(score=lambda x: x["score"].fillna(-1))[["code", "date", "score"]]
            for sl in (10, 20):
                for hold in (20, 60):
                    a = pf.simulate(e, hold, sl, start="2013-02-01", end="2019-12-31")["curve"]
                    b = pf.simulate(e, hold, sl, start="2020-01-01")["curve"]
                    res = pf.simulate(e, hold, sl, start="2013-02-01")
                    print(pf.fmt(res, f"{fs.NAMES[key]} {lab}") + f"｜前段13~19 {a['cagr']:+.1%}/{a['mdd']:+.0%}｜後段20~26 {b['cagr']:+.1%}/{b['mdd']:+.0%}")
            res = pf.simulate(e, 60, 20, start="2013-02-01")
            print("   20份持有60日 每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
    print("   加權每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly_taiex"].items()))


if __name__ == "__main__":
    main()
