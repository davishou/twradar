"""檢查：營收訊號＋挑最接近一年高點，是營收的功勞，還是單純「強勢股」的功勞？
python -m research.fin_momo
"""
from __future__ import annotations

import numpy as np

from pipeline import backtest as bt
from research import fin_signals as fs
from research import portfolio as pf


def main():
    q = bt.load_quotes()[["date", "code", "adj"]]
    adj = q.pivot(index="date", columns="code", values="adj")
    near = adj / adj.rolling(250, min_periods=120).max()
    r, rs = fs.revenue()
    cases = {"營收年增加速": rs["rev_accel"], "營收創兩年新高＋年增30%": rs["rev_high"],
             "對照：每月所有公司（不看營收）": r["yoy"].notna()}
    for name, m in cases.items():
        e = pf.events_at_next_close(r.loc[m.fillna(False), ["code", "deadline"]])
        e = e[e["date"] >= "2013-02-01"]
        e["score"] = [near.at[d, c] if c in near.columns else np.nan for d, c in zip(e["date"], e["code"])]
        e["score"] = e["score"].fillna(-1)
        print(f"\n== {name}（{len(e)} 次），資金 20 份、挑最接近一年高點、持有 60 日 ==")
        for lab, (s, t) in {"全期 2013~2026": ("2013-02-01", None), "前段 2013~2019": ("2013-02-01", "2019-12-31"),
                           "後段 2020~2026": ("2020-01-01", None)}.items():
            print(pf.fmt(pf.simulate(e, 60, 20, start=s, end=t), "  " + lab))
        res = pf.simulate(e, 60, 20, start="2013-02-01")
        print("   每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
        print("   加權：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly_taiex"].items()))
        # 只挑最接近高點的前 20% 訊號、全部買（不受份數影響）
        top = e[e["score"] >= e.groupby("date")["score"].transform(lambda s: s.quantile(0.8))]
        print(pf.fmt(pf.simulate(top[["code", "date"]], 60, None, start="2013-02-01"), "  最接近高點前 20%、全買"))


if __name__ == "__main__":
    main()
