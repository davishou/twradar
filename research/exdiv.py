"""除權息策略回測：python -m research.exdiv

A. 除權息前一天收盤買、除權息當天開盤賣（股息含在還原價裡），可選放空等值台指（用加權指數開盤代替期貨）。
B. 除權息前 N 天收盤買、除權息前一天收盤賣（不參加除權息，賺「卡位」行情）。
事件：adjust.csv.gz 裡 factor < 1 的日子（除權息日；少數現金減資也會混進來，停牌復牌的跳過）。
條件：前 20 日均成交值 ≥ 門檻；殖利率＝1 − factor（含股票股利）。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import event_bt as eb


def events(min_val: float = 1e8):
    M = eb.mats()
    days = M["adj"].index
    adj = pd.read_csv(bt.ARCHIVE / "adjust.csv.gz", dtype={"code": str}, parse_dates=["date"])
    adj = adj[(adj["factor"] < 0.999) & (adj["factor"] > 0.5) & adj["code"].str.fullmatch(r"\d{4}")]
    val20 = M["value"].rolling(20, min_periods=10).mean().shift(1)
    C = M["close"]
    di = {d: i for i, d in enumerate(days)}
    rows = []
    for r in adj.itertuples(index=False):
        if r.date not in di or r.code not in C.columns:
            continue
        i = di[r.date]
        if i < 25 or not np.isfinite(C.iat[i - 1, C.columns.get_loc(r.code)]):
            continue                                   # 前一個交易日沒成交（停牌）→ 跳過
        v = val20.at[days[i - 1], r.code]
        if not (np.isfinite(v) and v >= min_val):
            continue
        rows.append({"code": r.code, "ex": r.date, "i": i, "y": 1 - r.factor, "val": v})
    return pd.DataFrame(rows), days


def main(argv):
    out = []
    p = lambda s: (print(s), out.append(s))  # noqa: E731
    tx = eb.taiex()
    for mv in (1e8, 3e7):
        ev, days = events(mv)
        p(f"\n===== 成交值門檻 {mv/1e8:g} 億：除權息事件 {len(ev)} 筆（{days[ev.i.min()].year}~） =====")
        txo = tx["open"].reindex(days)
        txc = tx["close"].reindex(days)
        # A：前一天收盤買、除權息日開盤賣
        a = pd.DataFrame({"code": ev.code, "d0": [days[i - 1] for i in ev.i], "f0": "close", "d1": ev.ex, "f1": "open",
                          "side": 1, "score": ev.y})
        hedge = -(txo.reindex(ev.ex).to_numpy() / txc.reindex(a.d0).to_numpy() - 1)
        for lo, hi in [(0, 1), (0, 0.02), (0.02, 0.04), (0.04, 0.06), (0.06, 1)]:
            m = (ev.y >= lo) & (ev.y < hi)
            for hg in (False, True):
                t = a[m.to_numpy()].copy()
                t["hedge"] = (hedge[m.to_numpy()] - 0.00005) if hg else 0.0   # 期貨成本約萬分之 0.5
                for slots in (10, None):
                    r = eb.run(t, slots=slots, slip=0.003, label=f"A 殖利率 {lo:.0%}~{hi if hi < 1 else 9:.0%} {'避險' if hg else '不避險'} {slots or '全做'}份")
                    p(eb.fmt(r))
        # 滑價敏感：開盤賣的滑價
        for sl in (0.0, 0.001, 0.005):
            t = a.copy()
            t["hedge"] = hedge - 0.00005
            p(eb.fmt(eb.run(t, slots=10, slip=sl, label=f"A 全部 避險 10份 滑價{sl:.1%}")))
        # B：前 N 天買、前一天賣
        for N in (3, 5, 10):
            b = pd.DataFrame({"code": ev.code, "d0": [days[i - 1 - N] for i in ev.i], "f0": "close",
                              "d1": [days[i - 1] for i in ev.i], "f1": "close", "side": 1, "score": ev.y})
            for lo in (0, 0.04, 0.06):
                m = (ev.y >= lo).to_numpy()
                for slots in (10, 20):
                    p(eb.fmt(eb.run(b[m], slots=slots, slip=0.003, label=f"B 前{N}天買 殖利率≥{lo:.0%} {slots}份")))
    (eb.pf.OUT).mkdir(exist_ok=True)
    (eb.pf.OUT / "exdiv.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
