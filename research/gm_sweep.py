"""毛利率年增策略的參數掃描（2026-11-03）：門檻幾個百分點、要連續幾季，哪個最好？是不是只是運氣？

  A 毛利率比去年同季高 ≥ x 個百分點（x = 1, 2, 3, 4, 5, 7）
  B 連續 n 季「毛利率比去年同季高 ≥ x」（n = 2, 3, 4；x = 0, 1, 2, 3）
  C 毛利率比上一季高，連 n 季（n = 2, 3, 4）
共同：季報期限隔天收盤買、成交 ≥1 億、排除營建金融、每邊滑價 0.3%、20 份挑最接近一年高點、持有 60／120 日。
看全期與前段（2013~19）、後段（2020~26）；兩段都好、而且附近的參數也差不多好，才比較可信。

python -m research.gm_sweep
"""
from __future__ import annotations

import pandas as pd

from research import fin_signals as fs
from research import portfolio as pf
from research.robust_check import excl_mask, lookup, strength

SLIP = 0.003


def main():
    near, liq = strength()
    f, _ = fs.fin()
    big = f["rev_q"] > 1e5
    g = f.groupby("code")
    yoy = (f["gm"] - f["gm_4"]).where(f["gap4"])
    qoq = (f["gm"] - f["gm_1"]).where(g["t"].diff(1) == 1)
    cases = {}
    for x in (1, 2, 3, 4, 5, 7):
        cases[f"A 年增≥{x}pt"] = big & (yoy >= x)
    for n in (2, 3, 4):
        for x in (0, 1, 2, 3):
            ok = yoy >= x if x else yoy > 0
            streak = ok.astype(float)
            for k in range(1, n):
                streak = streak * (g["t"].diff(k) == k).astype(float) * ok.groupby(f["code"]).shift(k).fillna(False).astype(float)
            cases[f"B 連{n}季 年增{'>0' if not x else f'≥{x}pt'}"] = big & (streak > 0)
    for n in (2, 3, 4):
        ok = qoq > 0
        streak = ok.astype(float)
        for k in range(1, n):
            streak = streak * ok.groupby(f["code"]).shift(k).fillna(False).astype(float)
        cases[f"C 季增連{n}季"] = big & (streak > 0) & (yoy > 0)
    rows = []
    for name, m in cases.items():
        e = pf.events_at_next_close(f.loc[m.fillna(False), ["code", "deadline"]])
        e = e[e["date"] >= "2013-02-01"].copy()
        e["score"], e["liq"] = lookup(near, e), lookup(liq, e)
        e = e[(e["liq"].fillna(0) >= 1e8)]
        e = e[~excl_mask(e)].assign(score=lambda x: x["score"].fillna(-1))[["code", "date", "score"]]
        row = {"條件": name, "每季檔數": round(len(e) / 52)}
        for hold in (60, 120):
            res = pf.simulate(e, hold, 20, start="2013-02-01", slip=SLIP)
            a = pf.simulate(e, hold, 20, start="2013-02-01", end="2019-12-31", slip=SLIP)["curve"]
            b = pf.simulate(e, hold, 20, start="2020-01-01", slip=SLIP)["curve"]
            row[f"{hold}日 年化"] = f"{res['curve']['cagr']:+.1%}"
            row[f"{hold}日 回落"] = f"{res['curve']['mdd']:+.0%}"
            row[f"{hold}日 前段/後段"] = f"{a['cagr']:+.1%} / {b['cagr']:+.1%}"
        rows.append(row)
        print(row, flush=True)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
