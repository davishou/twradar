"""「河流」槓桿：股價在通道上緣用高槓桿、下緣用低槓桿（2026-11-12）

python -m research.river_lev [btdata 資料夾]
通道位置 p（0＝下緣、1＝上緣），收盤算：
  boll N k  布林通道：p＝(收盤−(均線−k×標準差)) ÷ (2k×標準差)
  don N     唐奇安：p＝(收盤−N日最低收盤) ÷ (N日最高−N日最低)
目標槓桿＝低 ＋ (高−低)×p（順勢：上緣高槓桿）；反向版：上緣低槓桿、下緣高槓桿。
調整：每天收盤看，實際槓桿和目標差超過 tol 倍才調（tol=0 就是每天調）。
個股期貨（小型 100 股／口）：原始保證金 13.5%、維持 10.35%（級距一，近似）；盤中最低點的權益數低於維持保證金＝被追繳一次，
  並在那個價位被砍到原始保證金撐得住的口數（『不被追繳』的條件＝次數 0）。槓桿上限＝1÷13.5%≈7.4 倍。
  損益用還原報酬（除息時期交所會調整契約），口數用實際股價。契約：起點股價 ≤125 元用標準（2,000 股），否則小型（100 股）。
  成本：每口每邊 1 檔（照股價級距：<10 元 0.01、<50 元 0.05、<100 元 0.1、<500 元 0.5、<1000 元 1、以上 5）＋手續費 30 元＋期交稅十萬分之二；
  每月換倉每口 1 檔＋2 次手續費。
台指期（微台）：原始 8.5%、維持 6.5%，成本每口每邊 1.5 點。
"""
from __future__ import annotations

import itertools
import sys

import numpy as np
import pandas as pd

from pipeline import backtest as bt

START = 500_000.0


def stock_series(code, a=None, b=None):
    q = bt.load_quotes()
    s = q[q.code == code].set_index("date")[["close", "low", "adj"]].sort_index()
    s["r"] = s["adj"].pct_change().clip(-0.11, 0.11).fillna(0)
    s["lowr"] = (s["low"] / s["close"]).clip(0.85, 1)
    return s


def bands(close: pd.Series) -> dict:
    out = {}
    for n in (20, 60, 120):
        ma, sd = close.rolling(n).mean(), close.rolling(n).std()
        for k in (1, 2):
            out[f"布林 {n}日 ±{k}σ"] = ((close - (ma - k * sd)) / (2 * k * sd)).clip(0, 1)
    for n in (20, 60, 120, 250):
        lo, hi = close.rolling(n).min(), close.rolling(n).max()
        out[f"唐奇安 {n}日"] = ((close - lo) / (hi - lo)).clip(0, 1)
    out["固定"] = pd.Series(1.0, index=close.index)
    vol = close.pct_change().rolling(20).std() * np.sqrt(250)
    for tv in (0.3, 0.45, 0.6):
        lev = (tv / vol).clip(1, 6)                                   # 目標波動：槓桿＝目標波動÷最近 20 日波動，限制在 1~6 倍
        out[f"波動目標 {tv:.0%}"] = ((lev - 1) / 5).clip(0, 1)       # 換成 p，配 下緣 1／上緣 6
    return out


def tick(px):
    return 0.01 if px < 10 else 0.05 if px < 50 else 0.1 if px < 100 else 0.5 if px < 500 else 1.0 if px < 1000 else 5.0


def sim(close, r, lowr, p, lmin, lmax, tol, mult=None, im=0.135, mm=0.1035, cost_lot=None, tax=0.00002,
        roll_mask=None, ledger=None, start=START, fee=30.0):
    """回傳（最後淨值, 最低淨值, 最大回落, 追繳次數, 最高實際槓桿, 調整次數）。cost_lot=None＝個股期貨（照股價級距算一檔）"""
    c, rr, lr, pp = close, r, lowr, p
    if mult is None:
        mult = 2000 if c[0] <= 125 else 100
    fixed_cost = cost_lot
    cl = lambda px: fixed_cost if fixed_cost is not None else tick(px) * mult + fee  # noqa: E731
    rc = lambda px: fixed_cost if fixed_cost is not None else tick(px) * mult + 2 * fee  # noqa: E731
    n = len(c)
    eq, lots, peak, mdd, mn, calls, maxlev, trades = start, 0, start, 0.0, start, 0, 0.0, 0
    for i in range(n):
        if lots:
            val0 = lots * mult * c[i - 1]
            if roll_mask is not None and roll_mask[i]:
                eq -= lots * rc(c[i - 1]) * (2 if fixed_cost is not None else 1)
            lowret = (1 + rr[i]) * lr[i] - 1
            worst = eq + val0 * lowret
            pos_low = val0 * (1 + lowret)
            maxlev = max(maxlev, pos_low / worst if worst > 0 else 99)
            if worst < mm * pos_low:
                calls += 1
                if ledger is not None:
                    ledger.append((i, "追繳", lots, worst, pos_low))
                if worst <= 0:
                    return 0.0, 0.0, -1.0, calls, maxlev, trades
                keep = int(worst / (im * mult * c[i - 1] * (1 + lowret)))
                eq = worst - (lots - keep) * cl(c[i - 1])
                eq += keep * mult * c[i - 1] * (1 + lowret) * ((1 + rr[i]) / (1 + lowret) - 1)
                lots = keep
            else:
                eq += val0 * rr[i]
        if eq <= 0:
            return 0.0, 0.0, -1.0, calls, maxlev, trades
        if not np.isfinite(pp[i]):
            tgt_lev = lmin
        else:
            tgt_lev = lmin + (lmax - lmin) * pp[i]
        lev = lots * mult * c[i] / eq
        if lots == 0 or abs(lev - tgt_lev) > tol:
            tgt = int(eq * tgt_lev / (mult * c[i]))
            tgt = min(tgt, int(eq / (im * mult * c[i])))
            if tgt != lots:
                eq -= abs(tgt - lots) * (cl(c[i]) + tax * mult * c[i])
                trades += 1
                if ledger is not None:
                    ledger.append((i, "調整", tgt, eq, tgt * mult * c[i]))
                lots = tgt
        peak = max(peak, eq)
        mn = min(mn, eq)
        mdd = min(mdd, eq / peak - 1)
    return eq, mn, mdd, calls, maxlev, trades


def grid():
    for name in ("布林 20日 ±1σ", "布林 20日 ±2σ", "布林 60日 ±1σ", "布林 60日 ±2σ", "布林 120日 ±1σ", "布林 120日 ±2σ",
                 "唐奇安 20日", "唐奇安 60日", "唐奇安 120日", "唐奇安 250日"):
        for direction in ("順勢", "反向"):
            for lmax, lmin in itertools.product((3, 4, 5, 6, 7), (0, 1, 2)):
                for tol in (0, 0.5, 1.0):
                    yield name, direction, lmin, lmax, tol
    for L in (1, 2, 3, 4, 5, 6, 7):
        for tol in (0, 0.5, 1.0):
            yield "固定", "—", L, L, tol


def run_cfg(s, B, cfg, a, b, **kw):
    name, direction, lmin, lmax, tol = cfg
    m = (s.index >= a) & (s.index <= b)
    p = B[name].to_numpy()
    if direction == "反向":
        p = 1 - p
    roll = pd.Series(s.index[m]).dt.month.diff().fillna(0).ne(0).to_numpy()
    return sim(s["close"].to_numpy()[m], s["r"].to_numpy()[m], s["lowr"].to_numpy()[m], p[m], lmin, lmax, tol, roll_mask=roll, **kw)


def label(cfg):
    name, direction, lmin, lmax, tol = cfg
    t = "每天調" if tol == 0 else f"偏離 {tol:g} 倍才調"
    if name == "固定":
        return f"固定 {lmax} 倍、{t}"
    if name.startswith("波動目標"):
        return f"{name}（1~6 倍）、{t}"
    return f"{name}、{direction}：上緣 {lmax if direction == '順勢' else lmin} 倍／下緣 {lmin if direction == '順勢' else lmax} 倍、{t}"


def main(argv):
    out = []
    P = lambda s_="": (print(s_, flush=True), out.append(s_))  # noqa: E731
    s = stock_series("2330")
    B = bands(s["close"])
    A, Bd = "2023-10-31", "2024-10-30"
    rows = []
    for cfg in grid():
        e, mn, mdd, calls, mx, tr = run_cfg(s, B, cfg, A, Bd)
        rows.append((cfg, e, mn, mdd, calls, mx, tr))
    R = pd.DataFrame(rows, columns=["cfg", "final", "min", "mdd", "calls", "maxlev", "trades"])
    P(f"===== 一、台積電小型股期貨 {A} ~ {Bd}（股價 529 → 1030），50 萬起步；{len(R)} 組參數 =====")
    P("\n--- 固定槓桿（對照） ---")
    for r in R[R.cfg.map(lambda c: c[0] == "固定")].itertuples():
        P(f"  {label(r.cfg):<34} 50 萬 → {r.final:>11,.0f}（{r.final / START:.2f} 倍）最低 {r.min:>9,.0f} 回落 {r.mdd:+.0%} 追繳 {r.calls} 次 最高槓桿 {r.maxlev:.1f} 倍 調 {r.trades} 次")
    ok = R[R.calls == 0].sort_values("final", ascending=False)
    P(f"\n--- 不被追繳的組合裡，最後淨值最高的 15 組（{len(ok)}／{len(R)} 組沒被追繳） ---")
    for r in ok.head(15).itertuples():
        P(f"  {label(r.cfg):<58} → {r.final:>11,.0f}（{r.final / START:.2f} 倍）最低 {r.min:>9,.0f} 回落 {r.mdd:+.0%} 最高槓桿 {r.maxlev:.1f} 倍 調 {r.trades} 次")
    bad = R[R.calls > 0].sort_values("final", ascending=False)
    P(f"\n--- 被追繳過的組合裡最後淨值最高的 5 組（{len(bad)} 組被追繳過） ---")
    for r in bad.head(5).itertuples():
        P(f"  {label(r.cfg):<58} → {r.final:>11,.0f} 追繳 {r.calls} 次 最高槓桿 {r.maxlev:.1f} 倍")
    P("\n--- 順勢 vs 反向、各種通道（同一組槓桿 上緣/下緣＝6/2、偏離 0.5 倍才調） ---")
    for name in B:
        if name == "固定" or name.startswith("波動目標"):
            continue
        for d in ("順勢", "反向"):
            r = R[R.cfg == (name, d, 2, 6, 0.5)].iloc[0]
            P(f"  {name:<14}{d}：{r.final:>11,.0f}（{r.final / START:.2f} 倍）追繳 {r.calls} 次 最高槓桿 {r.maxlev:.1f} 倍")

    # ---- 二、拿同樣的參數去別的時間、別的股票驗證
    P("\n--- 波動目標（槓桿＝目標波動÷最近 20 日波動，1~6 倍；不是看通道位置） ---")
    for tv in ("30%", "45%", "60%"):
        for tol in (0.5, 1.0):
            cfg = (f"波動目標 {tv}", "順勢", 1, 6, tol)
            e, mn, mdd, calls, mx, tr = run_cfg(s, B, cfg, A, Bd)
            P(f"  {label(cfg):<46} → {e:>11,.0f}（{e / START:.2f} 倍）最低 {mn:>9,.0f} 回落 {mdd:+.0%} 追繳 {calls} 次 最高槓桿 {mx:.1f} 倍 調 {tr} 次")
    best = list(ok.head(5).cfg)
    picks = best + [("布林 60日 ±2σ", "順勢", 2, 6, 0.5), ("唐奇安 250日", "順勢", 2, 6, 0.5), ("唐奇安 250日", "順勢", 2, 4, 0.5),
                    ("波動目標 30%", "順勢", 1, 6, 0.5), ("波動目標 45%", "順勢", 1, 6, 0.5), ("波動目標 60%", "順勢", 1, 6, 0.5),
                    ("固定", "—", 2, 2, 0.5), ("固定", "—", 3, 3, 0.5), ("固定", "—", 4, 4, 0.5)]
    picks = list(dict.fromkeys(picks))
    P("\n===== 二、同樣參數換時間：台積電 2008~2026，每個月開始一次、各跑 1 年（約 210 次） =====")
    P(f"{'參數':<58}{'1年後中位':>9}{'最差10%':>9}{'最好10%':>9}{'被追繳的比例':>10}{'賠一半以上':>9}")
    starts = s.index[(s.index >= "2008-01-01") & (s.index <= "2025-11-01")]
    starts = pd.Series(starts).groupby([starts.year, starts.month]).first().tolist()
    for cfg in picks:
        fin, called, half = [], 0, 0
        for d0 in starts:
            d1 = d0 + pd.Timedelta(days=365)
            e, mn, mdd, calls, mx, tr = run_cfg(s, B, cfg, d0, d1)
            fin.append(e / START)
            called += calls > 0
            half += mn < START / 2
        n = len(fin)
        P(f"{label(cfg):<58}{np.median(fin):>9.2f}x{np.percentile(fin, 10):>8.2f}x{np.percentile(fin, 90):>8.2f}x{called / n:>10.0%}{half / n:>9.0%}")
    P("\n===== 三、同樣參數換股票：近 10 年（2016/11 ~ 2026/11），各放 50 萬 =====")
    names = {"2330": "台積電", "2454": "聯發科", "2317": "鴻海", "2382": "廣達", "2308": "台達電", "2603": "長榮", "2881": "富邦金", "2303": "聯電", "3008": "大立光", "2409": "友達"}
    SS = {c: stock_series(c) for c in names}
    BB = {c: bands(v["close"]) for c, v in SS.items()}
    P(f"{'參數':<58}" + "".join(f"{v:>8}" for v in names.values()) + f"{'被追繳檔數':>8}")
    for cfg in picks:
        cells, nc = [], 0
        for c in names:
            e, mn, mdd, calls, mx, tr = run_cfg(SS[c], BB[c], cfg, "2016-11-01", "2026-11-12")
            cells.append(f"{e / START:>7.1f}x")
            nc += calls > 0
        P(f"{label(cfg):<58}" + "".join(cells) + f"{nc:>8}")
    if argv:
        from research import fut_compound as fc
        t = fc.series(argv[0]).iloc[250:]
        tb = bands(t["close"])
        r_ = (t["close"] / t["prev_close"] - 1).to_numpy()
        lr_ = (t["lo"] / t["close"]).to_numpy()
        P("\n===== 四、同樣參數換台指期（微台）：2006~2026，每 20 個交易日一個起點、各跑 5 年 =====")
        P(f"{'參數':<58}{'5年後中位':>9}{'最差10%':>9}{'最好10%':>9}{'被追繳的比例':>10}{'賠一半以上':>9}")
        for cfg in picks:
            name, direction, lmin, lmax, tol = cfg
            p = tb[name].to_numpy()
            if direction == "反向":
                p = 1 - p
            fin, called, half = [], 0, 0
            for i0 in range(0, len(t) - 248 * 5, 20):
                sl = slice(i0, i0 + 248 * 5)
                e, mn, mdd, calls, mx, tr = sim(t["close"].to_numpy()[sl], r_[sl], lr_[sl], p[sl], lmin, lmax, tol, mult=10, im=0.085, mm=0.065,
                                                cost_lot=15.0, roll_mask=t["roll"].to_numpy()[sl])
                fin.append(e / START)
                called += calls > 0
                half += mn < START / 2
            n = len(fin)
            P(f"{label(cfg):<58}{np.median(fin):>9.2f}x{np.percentile(fin, 10):>8.2f}x{np.percentile(fin, 90):>8.2f}x{called / n:>10.0%}{half / n:>9.0%}")
    from research import portfolio as pf
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / "river_lev.txt").write_text("\n".join(out))
    R.assign(cfg=R.cfg.map(label)).to_csv(pf.OUT / "river_lev_tsmc_grid.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
