"""籌碼事件回測（2026-11-03）：投信、外資、融資融券

一、單獨當策略（事件出現當天收盤後才知道 → 隔天收盤買；同一檔 20 日內只算第一次）
   投信首買     投信買超 ≥ 20 日均量 2%，而且前 60 個交易日投信完全沒買過
   投信連買     投信連 5 天買超
   投信大買     投信近 20 日買超合計 ≥ 同期成交量 5%
   外資連買     外資連 10 天買超
   外資大買     外資近 20 日買超合計 ≥ 同期成交量 10%
   土洋同買     投信、外資近 20 日都買超，合計 ≥ 成交量 8%
   籌碼沉澱     融資餘額 20 日減少 ≥ 10%，股價 20 日漲 ≥ 5%
   軋空         券資比 ≥ 30%，股價在一年高點 5% 以內
   同一天太多就挑最接近一年高點；20 份、停損 20%（最多 60 日）；也看持有 60 日不停損。
二、加在營收策略上（營收年增加速＋挑強勢＋停損 20%，+30.2%）：進場前 20 日的籌碼當條件或排序
共同：成交 ≥1 億、排除營建金融、滑價 0.3%；法人資料 2012/5 起，所以從 2012/8 起算（營收策略從 2013/2）。
沒有測：庫藏股（只有近半年資料）、董監持股增減（沒有資料）。

python -m research.chips
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import exit_rules as er
from research import fin_signals as fs
from research import portfolio as pf
from research.robust_check import excl_mask, lookup, strength

OUT = Path(__file__).parent / "results" / "chips.json"
START = "2012-08-01"


def mats():
    px, *_ = pf.prices()
    days, cols = px.index, px.columns
    q = bt.load_quotes()[["date", "code", "volume", "adj"]]
    vol = q.pivot(index="date", columns="code", values="volume").reindex(index=days, columns=cols) / 1000   # 張
    adj = q.pivot(index="date", columns="code", values="adj").reindex(index=days, columns=cols)
    ins = bt.load_inst()
    tr = ins.pivot_table(index="date", columns="code", values="trust", aggfunc="last").reindex(index=days, columns=cols)
    fo = ins.pivot_table(index="date", columns="code", values="foreign", aggfunc="last").reindex(index=days, columns=cols)
    mg = bt.load_margin()
    fin = mg.pivot_table(index="date", columns="code", values="fin_bal", aggfunc="last").reindex(index=days, columns=cols)
    sht = mg.pivot_table(index="date", columns="code", values="short_bal", aggfunc="last").reindex(index=days, columns=cols)
    inst_ok = pd.Series(days >= pd.Timestamp("2012-05-02"), index=days)
    tr = tr.where(inst_ok, np.nan).where(tr.notna() | ~inst_ok.to_numpy()[:, None], 0)   # 有法人資料的日子，沒列＝0
    fo = fo.where(inst_ok, np.nan).where(fo.notna() | ~inst_ok.to_numpy()[:, None], 0)
    return days, vol, adj, tr, fo, fin, sht


def first_in(cond: pd.DataFrame, n=20) -> pd.DataFrame:
    c = cond.fillna(False).astype(bool)
    prev = c.shift(1, fill_value=False).astype(int).rolling(n, min_periods=1).max().astype(bool)
    return c & ~prev


def features():
    days, vol, adj, tr, fo, fin, sht = mats()
    v20 = vol.rolling(20, min_periods=15).mean()
    vs20 = vol.rolling(20, min_periods=15).sum()
    t20, f20 = tr.rolling(20, min_periods=15).sum(), fo.rolling(20, min_periods=15).sum()
    r20 = adj / adj.shift(20) - 1
    near = adj / adj.rolling(250, min_periods=200).max()
    sig = {
        "投信首買": (tr >= 0.02 * v20) & (tr > 0) & ((tr > 0).astype(int).shift(1).rolling(60, min_periods=60).sum() == 0),
        "投信連買": (tr > 0).astype(int).rolling(5).sum() == 5,
        "投信大買": t20 >= 0.05 * vs20,
        "外資連買": (fo > 0).astype(int).rolling(10).sum() == 10,
        "外資大買": f20 >= 0.10 * vs20,
        "土洋同買": (t20 > 0) & (f20 > 0) & (t20 + f20 >= 0.08 * vs20),
        "籌碼沉澱": (fin / fin.shift(20) - 1 <= -0.10) & (fin.shift(20) >= 500) & (r20 >= 0.05),
        "軋空": (sht / fin >= 0.30) & (fin >= 500) & (near >= 0.95),
    }
    feats = {"t20r": t20 / vs20, "f20r": f20 / vs20, "fin20": fin / fin.shift(20) - 1, "ss": sht / fin}
    return days, {k: first_in(v) for k, v in sig.items()}, feats


def to_events(flag: pd.DataFrame, days, start=START):
    st = flag.stack()
    st = st[st]
    d0 = st.index.get_level_values(0)
    i = days.get_indexer(d0) + 1
    ok = i < len(days)
    e = pd.DataFrame({"code": st.index.get_level_values(1)[ok], "date": days[i[ok]]})
    return e[e["date"] >= start]


def run(e, X, label, out, stop=True, start=START):
    x = e.assign(hold=X.holds(e, er.stop(0.20, 60))) if stop else e
    res = pf.simulate(x, 60, 20, start=start, slip=er.SLIP, skip_held=True)
    c = er.curve(res["_eq"])
    t = res["trade"]
    print(f"  {label:<30} 年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（前 {c['early']:+.1%}／後 {c['late']:+.1%}）"
          f"｜交易 {res['n_trades']} 每筆 {t['mean']:+.1%} 賺錢 {t['win']:.0%}｜持股 {res['invested']:.0%}", flush=True)
    out[label] = {**c, "n": res["n_trades"], "trade": t, "invested": res["invested"], "yearly": res["yearly"]}
    return res


def main():
    near, liq = strength()
    r, rs = fs.revenue()
    X = er.Exits(r)
    days, sigs, feats = features()
    out = {"alone": {}, "addon": {}}
    print("== 一、籌碼事件單獨當策略（2012/8 起；成交 ≥1 億、排除營建金融、挑最接近一年高點、20 份） ==")
    tx = pf.prices()[2]
    t0 = tx[tx.index >= START]
    print(f"  對照：加權指數（不含息）同期 年化 {(t0.iloc[-1] / t0.iloc[0]) ** (365.25 / (t0.index[-1] - t0.index[0]).days) - 1:+.1%}")
    # 對照：每月第一個交易日純挑強勢（同條件）
    dd = days[days >= START]
    first = pd.Series(dd).groupby([dd.year, dd.month]).first().values
    rows = [pd.DataFrame({"code": near.columns, "date": d, "score": near.loc[d].values, "liq": liq.loc[d].values}) for d in first]
    m = pd.concat(rows).dropna(subset=["score"])
    m = m[(m["liq"].fillna(0) >= 1e8)]
    m = m[~excl_mask(m)][["code", "date", "score"]]
    run(m, X, "對照：每月純挑強勢", out["alone"])
    for k, flag in sigs.items():
        e = to_events(flag, days)
        e["score"], e["liq"] = lookup(near, e), lookup(liq, e)
        e = e[e["liq"].fillna(0) >= 1e8]
        e = e[~excl_mask(e)].assign(score=lambda x: x["score"].fillna(-1))[["code", "date", "score"]]
        print(f" [{k}] {len(e)} 次（每月約 {len(e) / 170:.0f} 次）")
        run(e, X, f"{k} 停損 20%", out["alone"])
        run(e, X, f"{k} 持有 60 日", out["alone"], stop=False)

    print("\n== 二、加在營收策略上（營收年增加速＋挑強勢＋停損 20%） ==")
    e = er.events(near, liq, r, rs, 10)
    for f, mat in feats.items():
        e[f] = lookup(mat.shift(1), e)          # 進場前一天為止的 20 日
    run(e, X, "基準", out["addon"], start=er.START)
    cases = {
        "投信近 20 日有買超": e[e["t20r"] > 0],
        "投信近 20 日沒有賣超": e[~(e["t20r"] < 0)],
        "投信近 20 日買超 ≥1% 量": e[e["t20r"] >= 0.01],
        "外資近 20 日有買超": e[e["f20r"] > 0],
        "外資近 20 日賣超（反向）": e[e["f20r"] < 0],
        "融資 20 日減少": e[e["fin20"] < 0],
        "融資 20 日增加 >20%（散戶追）排除": e[~(e["fin20"] > 0.2)],
        "排序：投信買超比例高的優先": e.assign(score=e["score"] + e["t20r"].fillna(0).clip(-0.1, 0.1)),
        "排序：法人（投信＋外資）買超比例高的優先": e.assign(score=e["score"] + (e["t20r"].fillna(0) + e["f20r"].fillna(0)).clip(-0.2, 0.2) / 2),
    }
    for lab, x in cases.items():
        run(x[["code", "date", "score"]], X, lab, out["addon"], start=er.START)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
