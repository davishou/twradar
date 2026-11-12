"""價量特徵矩陣（日期×代號），給飆股反推（multibagger2）與收縮後突破回測（vcp_bt）共用。

全部只用當天收盤（含）以前的資料；要當「前一天資料」用時呼叫端自己 shift(1)。

  near    收盤 ÷ 近 250 日最高收盤（1＝創一年新高）
  ret20／ret60／ret120  前 N 日漲幅（還原）
  val20   20 日均成交金額（元）
  bbw     布林通道寬度＝4×20 日標準差 ÷ 20 日均價
  bbw_pct 今天的布林寬度在自己過去 250 日裡排第幾（0＝一年來最窄）
  rng     振幅收縮＝近 10 日平均（最高−最低）÷收盤 ÷ 近 60 日平均；<1 代表最近變安靜
  vdry    量縮＝近 10 日均量 ÷ 近 60 日均量
  vx      當天量 ÷ 前 20 日均量（不含當天）
  hi20／hi60  當天收盤創 20／60 日新高（不含當天的前高）
  volat   60 日報酬標準差（年化）
  lu20    前 20 日漲停次數
  locked  一字漲停；hc／lc／oc 高、低、開 ÷ 收盤；vol 成交量
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import portfolio as pf

_F = None


def feats() -> dict:
    global _F
    if _F is not None:
        return _F
    px, r, tx, ew = pf.prices()
    q = bt.load_quotes()[["date", "code", "open", "high", "low", "close", "volume", "value", "is_lu"]]

    def piv(c):
        return q.pivot(index="date", columns="code", values=c).reindex(index=px.index, columns=px.columns).astype("float32")
    H, L, C, VO, VA, O = piv("high"), piv("low"), piv("close"), piv("volume"), piv("value"), piv("open")
    LU = q.pivot(index="date", columns="code", values="is_lu").reindex(index=px.index, columns=px.columns).fillna(False).astype("float32")
    del q
    import gc
    gc.collect()
    px = px.astype("float32")
    f = {"px": px, "r": r, "tx": tx, "ew": ew}
    f["near"] = px / px.rolling(250, min_periods=200).max()
    for n in (20, 60, 120):
        f[f"ret{n}"] = px / px.shift(n) - 1
    f["val20"] = VA.rolling(20, min_periods=15).mean()
    ma20 = px.rolling(20, min_periods=15).mean()
    f["bbw"] = 4 * px.rolling(20, min_periods=15).std() / ma20
    f["bbw_pct"] = f["bbw"].rolling(250, min_periods=120).rank(pct=True)
    hl = ((H - L) / C).where(C > 0)
    f["rng"] = hl.rolling(10, min_periods=7).mean() / hl.rolling(60, min_periods=40).mean()
    f["vdry"] = VO.rolling(10, min_periods=7).mean() / VO.rolling(60, min_periods=40).mean()
    f["vx"] = VO / VO.rolling(20, min_periods=15).mean().shift(1)
    f["hi20"] = px >= px.rolling(20, min_periods=15).max().shift(1)
    f["hi60"] = px >= px.rolling(60, min_periods=40).max().shift(1)
    f["volat"] = r.rolling(60, min_periods=40).std() * np.sqrt(250)
    f["lu20"] = LU.rolling(20, min_periods=1).sum()
    f["is_lu"] = LU > 0
    f["locked"] = f["is_lu"] & (H <= L + 1e-9)          # 一字漲停（買不到）
    f["hc"], f["lc"], f["oc"], f["vol"] = H / C, L / C, O / C, VO   # 高／低／開 對收盤的比值（乘還原價就是還原高低開）、成交量
    for k, v in list(f.items()):
        if isinstance(v, pd.DataFrame) and v.dtypes.iloc[0] == "float64":
            f[k] = v.astype("float32")
    del H, L, C, VA, LU, hl, O
    _F = f
    return f


def revenue_state(index: pd.DatetimeIndex, columns) -> dict:
    """每天『已經公布（過了次月 10 日期限）的最新一期月營收』狀態矩陣：
    yoy（單月年增 %）、accel（年增 ≥30 且連 3 個月一個比一個高）、high（創 24 個月新高且年增 ≥30）、
    age（距離那次期限過了幾個交易日）。期限當天還不算已知（隔一個交易日才生效）。"""
    from research import fin_signals as fs
    rv, sig = fs.revenue()
    rv = rv.assign(accel=sig["rev_accel"].fillna(False), high=sig["rev_high"].fillna(False))
    pos = index.searchsorted(rv["deadline"].values, side="right")      # 期限之後第一個交易日
    rv = rv[pos < len(index)].assign(eff=index[pos[pos < len(index)]])
    out = {}
    for c in ("yoy", "accel", "high"):
        m = rv.pivot_table(index="eff", columns="code", values=c, aggfunc="last").astype("float32")
        out[c] = m.reindex(index=index).ffill(limit=45).reindex(columns=columns)
    eff = pd.Series(np.arange(len(index)), index=index)
    last_eff = pd.Series(np.where(index.isin(rv["eff"].unique()), np.arange(len(index)), np.nan), index=index).ffill()
    out["age"] = (eff - last_eff)                                      # 每天距離最近一次營收生效日幾個交易日（全市場同一天）
    return out
