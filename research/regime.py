"""大盤風控：最佳策略（營收年增加速＋挑強勢＋停損 20%）能不能把回落壓到 −25% 以內？（2026-11-03）

三種做法
  A 只管新進場：大盤（加權指數）前一天收在 N 日均線之下，就不買新的；手上的照原規則
  B 減碼：大盤在均線下，整體部位降到一半（或全部出清），回到均線上再加回；換部位要付成本
  C 急跌減碼：大盤 20 日跌超過 8%／10% 時降到一半，直到回到 20 日前價位
  D 閒置資金放大盤：沒用到的份數買加權指數（價格指數、不含息，偏保守），看能多賺多少
均線 N＝60（季線）、120（半年線）、240（年線）；跌破要多跌 2% 才算（避免來回洗）的版本也試。
共同：成交 ≥1 億、排除營建金融、20 份、扣成本＋滑價 0.3%、同一檔持有中不重複買，2013/2 起。

python -m research.regime
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research import exit_rules as er
from research import fin_signals as fs
from research import portfolio as pf
from research.robust_check import strength

START = er.START
OUT = Path(__file__).parent / "results" / "regime.json"
COST = 0.001425 * 2 + 0.003 + 0.003 * 2      # 部位調整一來一回的成本（手續費、稅、滑價）


def show(lab, eq, out, extra=""):
    c = er.curve(eq)
    yy = eq.groupby(eq.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    print(f"{lab:<40} 年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（前 {c['early']:+.1%}／後 {c['late']:+.1%}）{extra}", flush=True)
    out[lab] = {**c, "yearly": {str(k): float(v) for k, v in yy.items()}}
    return c


def overlay(base_dr: pd.Series, w: pd.Series) -> pd.Series:
    """部位權重 w（前一天決定）乘上策略每日報酬；權重變動付成本"""
    w = w.reindex(base_dr.index).ffill().fillna(1.0)
    turn = w.diff().abs().fillna(0)
    return (1 + base_dr * w - turn * COST / 2).cumprod()


def main():
    near, liq = strength()
    r, rs = fs.revenue()
    X = er.Exits(r)
    e = er.events(near, liq, r, rs, 10)
    e = e.assign(hold=X.holds(e, er.stop(0.20, 60)))
    px, ret, tx, ew = pf.prices()
    tx = tx[tx.index >= "2012-01-01"]
    out = {}
    base = pf.simulate(e, 60, 20, start=START, slip=er.SLIP, skip_held=True)
    beq = base["_eq"]
    dr = beq.pct_change().fillna(0)
    days = beq.index
    txr = tx.reindex(days).pct_change().fillna(0)
    show("基準：停損 20%（無風控）", beq, out, f"｜持股 {base['invested']:.0%}")
    show("對照：加權指數（不含息）", tx.reindex(days) / tx.reindex(days).iloc[0], out)
    yy = beq.groupby(beq.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    print("     基準每年：" + "  ".join(f"{y % 100:02d} {v:+.0%}" for y, v in yy.items()))

    print("\n== A 大盤在均線下就不買新的 ==")
    for n in (60, 120, 240):
        for buf in (0, 0.02):
            ma = tx.rolling(n).mean()
            bad = (tx < ma * (1 - buf)).shift(1, fill_value=False).astype(bool)        # 前一天收盤判斷
            ok = ~bad.reindex(e["date"]).fillna(False).astype(bool).to_numpy()
            res = pf.simulate(e[ok], 60, 20, start=START, slip=er.SLIP, skip_held=True)
            show(f"A {n} 日線{'（多跌 2% 才算）' if buf else ''}", res["_eq"], out, f"｜跳過 {(~ok).mean():.0%} 訊號｜持股 {res['invested']:.0%}")

    print("\n== B 大盤在均線下整體減碼 ==")
    for n in (60, 120, 240):
        for buf in (0, 0.02):
            ma = tx.rolling(n).mean()
            below = (tx < ma * (1 - buf))
            for wlow in (0.5, 0.0):
                w = pd.Series(np.where(below, wlow, 1.0), index=tx.index).shift(1)
                eq = overlay(dr, w)
                show(f"B {n} 日線{'（多跌 2%）' if buf else ''} 降到 {wlow:.0%}", eq, out,
                     f"｜在均線下的日子 {below.reindex(days).mean():.0%}")

    print("\n== C 大盤 20 日急跌就減碼一半，回到 20 日前價位才加回 ==")
    for drop in (0.08, 0.10):
        r20 = tx / tx.shift(20) - 1
        st, w = 1.0, []
        ref = None
        for d, v in r20.items():
            if st == 1.0 and v <= -drop:
                st, ref = 0.5, tx.shift(20)[d]
            elif st == 0.5 and tx[d] >= ref:
                st = 1.0
            w.append(st)
        w = pd.Series(w, index=tx.index).shift(1)
        show(f"C 20 日跌 {drop:.0%} 減碼一半", overlay(dr, w), out, f"｜減碼日子 {(w.reindex(days) < 1).mean():.0%}")

    print("\n== D 閒置資金放大盤 ==")
    inv = base["_inv"].reindex(days).shift(1).fillna(0)
    eqD = (1 + dr + (1 - inv) * txr).cumprod()
    show("D 基準＋閒置資金買加權指數", eqD, out)
    ma = tx.rolling(240).mean()
    w = pd.Series(np.where(tx < ma, 0.5, 1.0), index=tx.index).shift(1).reindex(days).fillna(1)
    up = (tx >= ma).shift(1).reindex(days).fillna(True)
    eqDB = (1 + dr * w + ((1 - inv) * txr).where(up, 0) - w.diff().abs().fillna(0) * COST / 2).cumprod()
    show("D＋B 年線下減碼一半、閒置資金只在年線上放大盤", eqDB, out)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
