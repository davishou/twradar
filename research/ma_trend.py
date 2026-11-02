"""均線多頭排列策略回測（2026-11-02）

訊號（都用收盤後才知道的資料，隔一個交易日收盤買）：
  short   短期多頭排列「剛成形」：5 日 > 10 日 > 20 日 > 60 日均線，前一天還不是
  short60 同上，再加 60 日均線向上（比 20 天前高）
  long    長期多頭排列「剛成形」：5 > 10 > 20 > 60 > 120 > 240 日均線，前一天還不是
出場：固定持有 20／60 日，或「跌破 20 日均線就隔天賣」（最多 120 日）
選股：20 日均成交 ≥ 1 億、排除營建金融；同一天訊號太多時隨機挑／挑最接近一年高點
成本：手續費＋稅＋每邊滑價 0.3%
另外看：營收年增加速＋進場時正處於多頭排列

python -m research.ma_trend
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import fin_signals as fs
from research import portfolio as pf
from research.robust_check import excl_mask, lookup

SLIP = 0.003
START = "2005-03-01"


def build():
    q = bt.load_quotes()[["date", "code", "adj", "value"]]
    adj = q.pivot(index="date", columns="code", values="adj")
    adj = adj[[c for c in adj.columns if len(c) == 4 and c.isdigit()]]
    ma = {n: adj.rolling(n, min_periods=n).mean() for n in (5, 10, 20, 60, 120, 240)}
    s = (ma[5] > ma[10]) & (ma[10] > ma[20]) & (ma[20] > ma[60])
    lg = s & (ma[60] > ma[120]) & (ma[120] > ma[240])
    up60 = ma[60] > ma[60].shift(20)
    near = adj / adj.rolling(250, min_periods=200).max()
    liq = q.pivot(index="date", columns="code", values="value").rolling(20, min_periods=15).mean().reindex(columns=adj.columns)
    below20 = adj < ma[20]
    return adj, {"short": s, "short60": s & up60, "long": lg}, near, liq, below20


def events(state: pd.DataFrame, near, liq, below20) -> pd.DataFrame:
    """剛成形那天（d0）→ 隔一個交易日收盤進場；score/liq 用 d0 的資料"""
    new = state & ~state.shift(1, fill_value=False)
    st = new.stack()
    st = st[st]
    d0 = st.index.get_level_values(0)
    code = st.index.get_level_values(1)
    days = state.index
    i0 = days.get_indexer(d0)
    ok = i0 + 1 < len(days)
    e = pd.DataFrame({"code": code[ok], "d0": d0[ok], "date": days[i0[ok] + 1]})
    e["score"] = [near.at[d, c] for d, c in zip(e["d0"], e["code"])]
    e["liq"] = [liq.at[d, c] for d, c in zip(e["d0"], e["code"])]
    # 跌破 20 日均線出場：進場後第一個收盤 < 20MA 的日子，隔天收盤賣（最多 120 日）
    b = below20.to_numpy()
    cols = {c: k for k, c in enumerate(below20.columns)}
    hold = []
    for c, i in zip(e["code"], i0[ok] + 1):
        seg = b[i + 1:i + 120, cols[c]]
        k = np.argmax(seg) if seg.any() else None
        hold.append(min(k + 2, 120) if k is not None else 120)
    e["hold_ma"] = hold
    return e[e["date"] >= START]


def show(e, lab, start=START):
    split = "2015-12-31"
    for hold in (20, 60, "ma"):
        x = e[["code", "date", "score"]]
        h = 60
        if hold == "ma":
            x = x.assign(hold=e["hold_ma"])
        else:
            h = hold
        for sl, pick in ((20, "挑最接近高點"), (20, "隨機")):
            xx = x if pick != "隨機" else x.drop(columns="score")
            res = pf.simulate(xx, h, sl, start=start, slip=SLIP)
            a = pf.simulate(xx, h, sl, start=start, end=split, slip=SLIP)["curve"]
            b = pf.simulate(xx, h, sl, start="2016-01-01", slip=SLIP)["curve"]
            hl = "跌破20MA出場" if hold == "ma" else f"持有{hold}日"
            print(pf.fmt(res, f"  {lab} {hl} {pick}").replace(f"{pick} 持有{h}日 ", f"{pick} ")
                  + f"｜前段05~15 {a['cagr']:+.1%}/{a['mdd']:+.0%}｜後段16~26 {b['cagr']:+.1%}/{b['mdd']:+.0%}")
            if hold == "ma" and pick == "挑最接近高點":
                print("     每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))


def main():
    adj, states, near, liq, below20 = build()
    names = {"short": "短期多頭排列 5>10>20>60", "short60": "短期多頭排列＋60MA 向上", "long": "長期多頭排列 5>10>20>60>120>240"}
    for k, st in states.items():
        e = events(st, near, liq, below20)
        e = e[(e["liq"].fillna(0) >= 1e8)]
        e = e[~excl_mask(e)].assign(score=lambda x: x["score"].fillna(-1))
        print(f"\n===== {names[k]}（剛成形；成交 ≥1 億、排除營建金融；{len(e)} 次，每月約 {len(e) / 260:.0f} 次） =====")
        show(e, names[k][:6])
    # 營收年增加速 ＋ 進場前一天處在多頭排列（2013 起）
    r, rs = fs.revenue()
    nr = near.shift(1)
    lq = liq.shift(1)
    e0 = pf.events_at_next_close(r.loc[rs["rev_accel"].fillna(False), ["code", "deadline"]])
    e0 = e0[e0["date"] >= "2013-02-01"].copy()
    e0["score"], e0["liq"] = lookup(nr, e0), lookup(lq, e0)
    e0 = e0[(e0["liq"].fillna(0) >= 1e8)]
    e0 = e0[~excl_mask(e0)].assign(score=lambda x: x["score"].fillna(-1))
    for k in ("short", "long"):
        inst = lookup(states[k].shift(1, fill_value=False), e0)
        for flag, lab in ((True, "處於"), (False, "不處於")):
            x = e0[[bool(v) is flag for v in inst]][["code", "date", "score"]]
            res = pf.simulate(x, 60, 20, start="2013-02-01", slip=SLIP)
            print(pf.fmt(res, f"\n營收加速＋{lab}{names[k]}（{len(x)} 次）"))
    print("加權每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly_taiex"].items()))


if __name__ == "__main__":
    main()
