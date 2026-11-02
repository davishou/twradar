"""絕對報酬回測：把訊號真的拿去買，模擬資金曲線（給研究腳本共用）

做法（一般人做得到的方式）
  - 資金分成 K 份（預設 10 份），每出現一個訊號就用一份買進；10 份都用完時，新的訊號跳過（不加碼、不融資）。
  - 訊號日的「進場日」收盤買（還原價），持有 N 個交易日後收盤賣；股票中途下市就以最後價格出場。
  - 交易成本：買 0.1425%、賣 0.1425% + 證交稅 0.3%（沒算手續費折扣，偏保守）。
  - 閒置的資金不計利息。
輸出：年化報酬、最大回落（資金曲線從高點最多跌幾成）、每年報酬、平均持股比例；
      每筆交易的絕對報酬（扣成本後）平均／中位數／賺錢機率／平均賺 ÷ 平均賠（盈虧比）。
對照：台股加權指數（價格指數，不含股息，約少算每年 3~4%）與全市場等權（含息）。
"""
from __future__ import annotations

import heapq
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import backtest as bt

BUY0, SELL0 = 0.001425, 0.001425 + 0.003
BUY, SELL = BUY0, SELL0
_PX = None


def prices():
    """（還原價矩陣 日期×代號、每日報酬矩陣、加權指數、等權指數）"""
    global _PX
    if _PX is None:
        q = bt.load_quotes()[["date", "code", "adj"]]
        px = q.pivot(index="date", columns="code", values="adj").sort_index()
        r = px.pct_change(fill_method=None).clip(-0.11, 0.11)       # 錯誤值截掉（漲跌幅上限 10%，2015 前 7%）
        tx = pd.concat([pd.read_csv(p, parse_dates=["date"]) for p in sorted((bt.ARCHIVE / "mkt" / "taiex").glob("*.csv"))])
        tx = tx.drop_duplicates("date").set_index("date")["close"].reindex(px.index).ffill()
        ew = (1 + r.mean(axis=1).fillna(0)).cumprod()
        # 用截過的每日報酬重組價格（代號換公司、長期停牌後復牌等跳動不會扭曲報酬）；沒有行情的日子維持空白
        pxc = (1 + r.fillna(0)).cumprod().where(px.notna())
        _PX = (pxc, r, tx, ew)
    return _PX


def simulate(ev: pd.DataFrame, hold: int, slots: int | None = 10, start=None, end=None, seed: int = 0,
             slip: float = 0.0, mats=None) -> dict:
    """ev 需要欄位 code、date（進場日＝這天收盤買）；可選 hold（每筆各自持有天數，覆蓋參數 hold）。slots=None 代表每個訊號都買、資金平均分（一定滿手）
    slip：每邊滑價（例如 0.003＝買貴 0.3%、賣便宜 0.3%），加在手續費稅之外。
    mats：自訂 (價格矩陣, 每日報酬矩陣)，例如可轉債；預設用股票還原價。"""
    px, r, tx, ew = prices()
    if mats is not None:
        px, r = mats
        px, r = px.reindex(tx.index), r.reindex(tx.index)
    BUY, SELL = BUY0 + slip, SELL0 + slip
    days = px.index
    if start is not None:
        days = days[days >= pd.Timestamp(start)]
    if end is not None:
        days = days[days <= pd.Timestamp(end)]
    sub_r = r.loc[days]
    col = {c: i for i, c in enumerate(px.columns)}
    di = {d: i for i, d in enumerate(days)}
    e = ev[ev["code"].isin(col) & ev["date"].isin(di)]
    # 同一天訊號太多、份數不夠時：有 score 就挑分數高的，沒有就隨機（固定種子，結果可重現）
    if "score" in e:
        e = e.sort_values(["date", "score"], ascending=[True, False])
    else:
        e = e.sample(frac=1, random_state=seed).sort_values("date", kind="stable")
    arr = px.loc[days].to_numpy()
    n, m = len(days), len(px.columns)
    cnt = np.zeros((n + 1, m), dtype=np.int32)
    cost = np.zeros(n + 1)
    busy: list[int] = []
    trades = []
    holds = e["hold"].to_numpy() if "hold" in e else np.full(len(e), hold)
    for d, c, h in zip(e["date"], e["code"], holds):
        i, j = di[d], col[c]
        if not np.isfinite(arr[i, j]):
            continue
        while busy and busy[0] <= i:
            heapq.heappop(busy)
        if slots is not None and len(busy) >= slots:
            continue
        k = min(i + int(h), n - 1)
        seg = arr[i:k + 1, j]
        ok = np.where(np.isfinite(seg))[0]
        k_exit = i + ok[-1]                     # 下市／停牌：用最後有價格那天出場
        if k_exit <= i:
            continue
        cnt[i + 1, j] += 1
        cnt[k_exit + 1, j] -= 1
        cost[i + 1] += BUY
        cost[k_exit] += SELL
        heapq.heappush(busy, k_exit)
        trades.append((arr[k_exit, j] / arr[i, j]) * (1 - BUY) * (1 - SELL) - 1)
    pos = np.cumsum(cnt[:n], axis=0)
    rr = np.nan_to_num(sub_r.to_numpy())
    held = pos.sum(axis=1)
    if slots is None:
        w = np.where(held > 0, held, 1)
        dr = (pos * rr).sum(axis=1) / w - cost[:n] / w
        invest = (held > 0).astype(float)
    else:
        dr = (pos * rr).sum(axis=1) / slots - cost[:n] / slots
        invest = held / slots
    eq = pd.Series(np.cumprod(1 + dr), index=days)
    tr = np.array(trades)
    yrs = (days[-1] - days[0]).days / 365.25

    def curve_stats(s):
        cagr = s.iloc[-1] ** (1 / yrs) - 1
        dd = (s / s.cummax() - 1).min()
        d = s.pct_change().dropna()
        return {"cagr": round(float(cagr), 4), "mdd": round(float(dd), 4),
                "sharpe": round(float(d.mean() / d.std() * np.sqrt(250)), 2) if d.std() > 0 else None,
                "total": round(float(s.iloc[-1] - 1), 3)}
    yearly = eq.groupby(eq.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    txs, ews = tx.loc[days], ew.loc[days]
    return {
        "range": [str(days[0].date()), str(days[-1].date())], "hold": hold, "slots": slots,
        "n_signals": int(len(e)), "n_trades": int(len(tr)),
        "trade": {"mean": round(float(tr.mean()), 4) if len(tr) else None, "med": round(float(np.median(tr)), 4) if len(tr) else None,
                  "win": round(float((tr > 0).mean()), 3) if len(tr) else None,
                  "payoff": round(float(tr[tr > 0].mean() / -tr[tr <= 0].mean()), 2) if (tr > 0).any() and (tr <= 0).any() else None,
                  "big": round(float((tr >= 0.3).mean()), 3) if len(tr) else None},
        "curve": curve_stats(eq), "invested": round(float(invest.mean()), 3),
        "taiex": curve_stats(txs / txs.iloc[0]), "ew": curve_stats(ews / ews.iloc[0]),
        "yearly": {str(y): round(float(v), 4) for y, v in yearly.items()},
        "yearly_taiex": {str(y): round(float(v), 4) for y, v in txs.groupby(txs.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1).items()},
    }


def fmt(res: dict, label: str = "") -> str:
    t, c, tx = res["trade"], res["curve"], res["taiex"]
    f = lambda x: "—" if x is None else f"{x:+.1%}"  # noqa: E731
    return (f"{label} 持有{res['hold']}日 {res['slots'] or '全買'}份｜交易 {res['n_trades']}/{res['n_signals']} 次："
            f"每筆平均 {f(t['mean'])} 中位 {f(t['med'])} 賺錢 {t['win']:.0%} 盈虧比 {t['payoff']}｜"
            f"資金曲線 年化 {f(c['cagr'])} 最大回落 {f(c['mdd'])}（加權指數 年化 {f(tx['cagr'])} 回落 {f(tx['mdd'])}）持股 {res['invested']:.0%}")


def events_at_next_close(ev: pd.DataFrame, when: str = "deadline") -> pd.DataFrame:
    """把『某天之後才知道』的事件換成進場日：該日之後的第一個交易日"""
    px, *_ = prices()
    days = px.index
    i = days.searchsorted(pd.to_datetime(ev[when]).values, side="right")
    ok = i < len(days)
    out = ev.loc[ok, [c for c in ev.columns if c != when]].copy()
    out["date"] = days[i[ok]]
    return out


OUT = Path(__file__).parent / "out"
