"""事件型交易回測（可開盤／收盤進出、可放空），給短天期事件策略共用

和 portfolio.simulate 的差別：
  - 每筆交易自己指定進場（日期＋開盤或收盤）與出場（日期＋開盤或收盤），可以是隔天開盤賣這種。
  - side=-1 代表放空（融券）：賣出時付手續費＋證交稅＋融券手續費 0.08%，買回付手續費；不計借券利息（短天期影響很小）。
  - 價格用還原價（adj／adj_open），所以除權息的股息會算進報酬（未扣個人股利所得稅與二代健保）。
資金：分 K 份，每筆用一份；份數用完新訊號跳過（同一天有 score 挑分數高的）。
每天以收盤價計算持股市值（進場當天從進場價算到收盤；出場那天從前一天收盤算到出場價）。
"""
from __future__ import annotations

import heapq

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import portfolio as pf

import os
FEE, TAX, SHORT_FEE = 0.001425 * float(os.getenv("FEE_DISC", "1")), 0.003, 0.0008   # FEE_DISC＝手續費折數
_M = None


def mats():
    """(還原收盤矩陣, 還原開盤矩陣, 原始收盤, 原始開盤, 漲停價, 參考價, 成交值)"""
    global _M
    if _M is None:
        q = bt.load_quotes()
        piv = lambda c: q.pivot(index="date", columns="code", values=c).sort_index()  # noqa: E731
        _M = {k: piv(c) for k, c in [("adj", "adj"), ("adj_open", "adj_open"), ("close", "close"), ("open", "open"),
                                      ("high", "high"), ("low", "low"), ("ref", "ref"), ("lu", "lu"), ("value", "value"),
                                      ("volume", "volume")]}
    return _M


def run(tr: pd.DataFrame, slots: int | None = 10, slip: float = 0.003, start=None, end=None, label: str = "") -> dict:
    """tr 欄位：code、d0（進場日）、f0（'open'/'close'）、d1（出場日）、f1、side（1 做多／-1 放空），可選 score。
    slots=None：每筆都做、資金平均分。"""
    M = mats()
    C, O = M["adj"], M["adj_open"]
    days = C.index
    if start is not None:
        days = days[days >= pd.Timestamp(start)]
    if end is not None:
        days = days[days <= pd.Timestamp(end)]
    di = {d: i for i, d in enumerate(days)}
    col = {c: i for i, c in enumerate(C.columns)}
    Ca, Oa = C.loc[days].to_numpy(), O.loc[days].to_numpy()
    if "hedge" not in tr:
        tr = tr.assign(hedge=0.0)
    t = tr[tr["code"].isin(col) & tr["d0"].isin(di) & tr["d1"].isin(di)].copy()
    if "score" in t:
        t = t.sort_values(["d0", "score"], ascending=[True, False], kind="stable")
    else:
        t = t.sample(frac=1, random_state=0).sort_values("d0", kind="stable")
    n = len(days)
    contrib = np.zeros(n)          # 每天 Σ(該筆當天報酬)
    held = np.zeros(n)
    busy: list[int] = []
    trades = []
    for row in t.itertuples(index=False):
        i, k, j = di[row.d0], di[row.d1], col[row.code]
        if k < i or (k == i and row.f0 == row.f1):
            continue
        p0 = Oa[i, j] if row.f0 == "open" else Ca[i, j]
        p1 = Oa[k, j] if row.f1 == "open" else Ca[k, j]
        if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0):
            continue
        while busy and busy[0] < i:
            heapq.heappop(busy)
        if slots is not None and len(busy) >= slots:
            continue
        s = row.side
        buy_c, sell_c = FEE + slip, FEE + TAX + slip + (SHORT_FEE if s < 0 else 0)
        # 每日價格路徑
        if row.f0 == "close":
            path = [p0] + [Ca[x, j] for x in range(i + 1, k)] + [p1]
            idx = list(range(i + 1, k + 1))
        else:
            idx = list(range(i, k + 1))
            path = [p0] + [Ca[x, j] for x in range(i, k)] + [p1]
        path = pd.Series(path, dtype=float).ffill().to_numpy()
        rets = np.clip(path[1:] / path[:-1] - 1, -0.11, 0.11)   # 停牌復牌、減資等跳動截掉（漲跌幅上限 10%／2015 前 7%）
        if len(idx) != len(rets):
            continue
        for x, rr in zip(idx, rets):
            contrib[x] += s * rr
        h = getattr(row, "hedge", 0.0)
        h = 0.0 if not np.isfinite(h) else h
        contrib[k] += h
        contrib[i] -= buy_c if s > 0 else sell_c
        contrib[k] -= sell_c if s > 0 else buy_c
        for x in range(i, k + 1):
            held[x] += 1
        heapq.heappush(busy, k)
        g = float(np.prod(1 + rets))
        trades.append((((g * (1 - sell_c)) / (1 + buy_c) - 1) if s > 0 else ((1 - sell_c) - g * (1 + buy_c))) + h)
    trn = np.array(trades)
    if slots is None:
        w = np.where(held > 0, held, 1)
        dr = contrib / w
        inv = (held > 0).mean()
    else:
        dr = contrib / slots
        inv = (np.minimum(held, slots) / slots).mean()
    eq = pd.Series(np.cumprod(1 + dr), index=days)
    yrs = (days[-1] - days[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1
    mdd = (eq / eq.cummax() - 1).min()
    yearly = eq.groupby(eq.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    mid = days[0] + (days[-1] - days[0]) / 2

    def seg(a, b):
        s = eq[(eq.index >= a) & (eq.index <= b)]
        if len(s) < 50:
            return None
        y = (s.index[-1] - s.index[0]).days / 365.25
        return float((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1)
    res = {"label": label, "n": int(len(t)), "trades": int(len(trn)),
           "mean": float(trn.mean()) if len(trn) else None, "med": float(np.median(trn)) if len(trn) else None,
           "win": float((trn > 0).mean()) if len(trn) else None,
           "payoff": float(trn[trn > 0].mean() / -trn[trn <= 0].mean()) if (trn > 0).any() and (trn <= 0).any() else None,
           "cagr": float(cagr), "mdd": float(mdd), "inv": float(inv),
           "early": seg(days[0], mid), "late": seg(mid, days[-1]),
           "range": f"{days[0].year}~{days[-1].year}", "yearly": {int(y): float(v) for y, v in yearly.items()}}
    return res


def fmt(r: dict) -> str:
    if not r["trades"]:
        return f"{r['label']}｜沒有交易"
    f = lambda x: "—" if x is None else f"{x:+.1%}"  # noqa: E731
    yy = "  ".join(f"{str(y)[2:]} {v:+.0%}" for y, v in r["yearly"].items())
    return (f"{r['label']}｜{r['range']} 交易 {r['trades']}/{r['n']}：每筆平均 {f(r['mean'])} 中位 {f(r['med'])} "
            f"賺錢 {r['win']:.0%} 盈虧比 {r['payoff'] and round(r['payoff'], 2)}｜年化 {f(r['cagr'])} 回落 {f(r['mdd'])} "
            f"前段 {f(r['early'])} 後段 {f(r['late'])} 持股 {r['inv']:.0%}\n     每年：{yy}")


def taiex():
    px, r, tx, ew = pf.prices()
    t = pd.concat([pd.read_csv(p, parse_dates=["date"]) for p in sorted((bt.ARCHIVE / "mkt" / "taiex").glob("*.csv"))])
    return t.drop_duplicates("date").set_index("date").sort_index()


def nxt(days: pd.DatetimeIndex, d, k: int = 1):
    """d 之後第 k 個交易日（d 本身不算）；沒有回傳 None"""
    i = days.searchsorted(pd.Timestamp(d), side="right") + k - 1
    return days[i] if 0 <= i < len(days) else None
