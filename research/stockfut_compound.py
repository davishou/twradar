"""獲利滾入保證金的實際例子（2026-11-12）：python -m research.stockfut_compound <btdata 資料夾>

一、台指期逐年流水帳：50 萬、微台、固定槓桿 3 倍（每 20 個交易日照淨值調口數，賺加賠減），三個起點（好、普通、最差）。
二、個股期貨：10 檔大家熟悉的股票，各用 2 倍／3 倍，「賺加賠減」和「只加不減」各跑近 10 年。
    個股期貨的損益≈還原股價（除息會調整），所以用還原日線模擬；原始保證金 13.5%、維持 10.35%，盤中最低點低於維持就砍倉。
    成本：每次調整的金額 0.1%，每月換倉 0.05%。不考慮口數不能整除（小型個股期貨一口 100 股）。
三、營收選股策略（營收加速＋挑最接近一年高點、20 檔、持有 60 日）加槓桿：1／1.5／2／2.5／3 倍，每天調回目標槓桿，資金成本年 3%。
    注意：不是每檔選到的股票都有個股期貨；沒有的要用融資（上限 2.5 倍、利率約 6.5%）。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from research import fut_compound as fc

START = 500_000.0


def tx_ledger(t, d0, L, years, P):
    c, pc, lo, roll = t["close"].to_numpy(), t["prev_close"].to_numpy(), t["lo"].to_numpy(), t["roll"].to_numpy()
    i0 = int(t.index.searchsorted(pd.Timestamp(d0)))
    eq, lots, PT, IM, MM = START, 0, 10.0, fc.IM, fc.MM
    P(f"\n  起點 {t.index[i0].date()}（指數 {c[i0]:,.0f}）、{L} 倍：")
    P(f"  {'日期':<12}{'指數':>8}{'口數(微台)':>9}{'契約總值':>12}{'淨值':>12}{'倍數':>7}  說明")
    peak, last_note = START, ""
    n = min(len(c) - i0, int(248 * years) + 1)
    for k in range(n):
        i = i0 + k
        note = ""
        if lots:
            if roll[i]:
                eq -= lots * 2 * PT
            worst = eq + lots * (lo[i] - pc[i]) * PT
            if worst < MM * lots * lo[i] * PT:
                keep = max(int(worst / (IM * lo[i] * PT)), 0)
                eq = worst - (lots - keep) * 1.5 * PT + keep * (c[i] - lo[i]) * PT
                note = f"盤中保證金不足，被砍到 {keep} 口"
                lots = keep
            else:
                eq += lots * (c[i] - pc[i]) * PT
        if eq <= 0:
            P(f"  {str(t.index[i].date()):<12}{c[i]:>8,.0f}{0:>9}{0:>12,.0f}{0:>12,.0f}{0:>6.2f}x  賠光")
            return
        if k % 20 == 0 or lots == 0:
            tgt = min(int(eq * L / (c[i] * PT)), int(eq / (IM * c[i] * PT)))
            if tgt != lots:
                eq -= abs(tgt - lots) * (1.5 * PT + 0.00002 * c[i] * PT)
                lots = tgt
        peak = max(peak, eq)
        if k % 124 == 0 or k == n - 1 or note:
            if not note:
                note = "新高" if eq >= peak * 0.999 and k else (f"離高點 {eq / peak - 1:+.0%}" if k else "進場")
            P(f"  {str(t.index[i].date()):<12}{c[i]:>8,.0f}{lots:>9}{lots * c[i] * PT:>12,.0f}{eq:>12,.0f}{eq / START:>6.2f}x  {note}")


def stock_sim(px, lowr, L, mode, IM=0.135, MM=0.1035):
    """px：還原收盤；lowr：當天最低÷收盤。回傳（最後倍數, 最低倍數, 最大回落, 被砍次數, 到 20 倍的日數或 -1）"""
    p = px.to_numpy()
    lr = lowr.to_numpy()
    eq, N, forced, mn, peak, mdd, hit = 1.0, 0.0, 0, 1.0, 1.0, 0.0, -1
    for i in range(1, len(p)):
        if not np.isfinite(p[i]) or not np.isfinite(p[i - 1]):
            continue
        if N > 0:
            low = p[i] * (lr[i] if np.isfinite(lr[i]) else 1.0)
            worst = eq + N * (low / p[i - 1] - 1)
            Nl = N * low / p[i - 1]
            if worst < MM * Nl:
                forced += 1
                if worst <= 0:
                    return 0.0, 0.0, -1.0, forced, hit
                keep = min(worst / IM, Nl)
                eq = worst - (Nl - keep) * 0.001
                eq += keep * (p[i] / low - 1)
                N = keep * p[i] / low
            else:
                eq += N * (p[i] / p[i - 1] - 1)
                N *= p[i] / p[i - 1]
        if eq <= 0:
            return 0.0, 0.0, -1.0, forced, hit
        if i % 20 == 1 or N == 0:
            tgt = eq * L
            if mode == "addonly" and N > 0:
                tgt = max(N, tgt)
            tgt = min(tgt, eq / IM)
            eq -= abs(tgt - N) * 0.001 + tgt * 0.0005
            N = tgt
        mn = min(mn, eq)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        if hit < 0 and eq >= 20:
            hit = i
    return eq, mn, mdd, forced, hit


def main(argv):
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    t = fc.series(argv[0])
    P("===== 一、台指期逐年流水帳：50 萬、微台（1 點 10 元）、每 20 個交易日照淨值把口數調回 3 倍槓桿（賺加賠減） =====")
    for d0, yrs in (("2019-01-02", 8), ("2022-01-03", 5), ("2007-10-01", 8)):
        tx_ledger(t, d0, 3, yrs, P)
    P("\n  對照：同樣 2019-01-02 起、2 倍槓桿")
    tx_ledger(t, "2019-01-02", 2, 8, P)

    from research import squeeze as sq
    f = sq.feats()
    px, lc = f["px"], f["lc"]
    names = {"2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2382": "廣達", "2603": "長榮", "2881": "富邦金", "1301": "台塑", "3008": "大立光", "2409": "友達", "2498": "宏達電"}
    for start, lab in (("2016-11-01", "近 10 年（2016/11 起）"), ("2021-07-01", "近 5 年多（2021/7 起，航運高點附近）")):
        P(f"\n===== 二、個股期貨：{lab}，各放 50 萬（表內是倍數；1.00＝50 萬） =====")
        P(f"{'股票':<12}{'股價漲幅':>8}｜{'2倍 賺加賠減':>12}{'最低':>6}{'回落':>6}｜{'3倍 賺加賠減':>12}{'最低':>6}{'回落':>6}｜{'3倍 只加不減':>12}{'最低':>6}{'被砍':>4}｜到 1000 萬（20 倍）")
        for code, nm in names.items():
            if code not in px.columns:
                continue
            s = px[code][px.index >= start]
            lr = lc[code][px.index >= start]
            if s.notna().sum() < 500:
                continue
            a = stock_sim(s, lr, 2, "const")
            b = stock_sim(s, lr, 3, "const")
            c_ = stock_sim(s, lr, 3, "addonly")
            hits = "、".join(f"{lb} {h / 248:.1f} 年" for lb, h in (("2倍", a[4]), ("3倍", b[4]), ("3倍只加不減", c_[4])) if h > 0) or "都沒到"
            tot = s.dropna().iloc[-1] / s.dropna().iloc[0] - 1
            P(f"{code} {nm:<6}{tot:>+9.0%}｜{a[0]:>11.2f}x{a[1]:>6.2f}{a[2]:>+6.0%}｜{b[0]:>11.2f}x{b[1]:>6.2f}{b[2]:>+6.0%}｜{c_[0]:>11.2f}x{c_[1]:>6.2f}{c_[3]:>4}｜{hits}")

    P("\n===== 三、營收選股策略加槓桿（2013/2 起；20 檔分散、每天調回目標槓桿、資金成本年 3%） =====")
    from research import exit_rules as ex
    from research import fin_signals as fs
    from research import portfolio as pf
    r, rs = fs.revenue()
    X = ex.Exits(r)
    base = ex.events(f["near"].shift(1), f["val20"].shift(1), r, rs, 10)
    for lab, rule in (("持有 60 日（不停損）", ex.fixed(60)), ("停損 20%（最多 60 日）", ex.stop(0.20, 60))):
        res = pf.simulate(base.assign(hold=X.holds(base, rule)), 60, 20, start="2013-02-01", slip=0.003, skip_held=True)
        eq = res["_eq"]
        dr = eq.pct_change().dropna()
        yrs = (dr.index[-1] - dr.index[0]).days / 365.25
        P(f"\n  {lab}（單日最大跌幅 {dr.min():.1%}）")
        P(f"  {'槓桿':>5}{'年化':>8}{'最大回落':>8}{'50 萬變成':>14}{'到 1000 萬':>10}{'最差的一年':>12}{'最差時 50 萬剩':>12}")
        for L in (1, 1.5, 2, 2.5, 3):
            g = 1 + L * dr - (L - 1) * 0.03 / 250
            g = g.clip(lower=0)
            e = g.cumprod()
            cagr = e.iloc[-1] ** (1 / yrs) - 1
            mdd = (e / e.cummax() - 1).min()
            hit = e[e >= 20]
            yr = e.groupby(e.index.year).last() / e.groupby(e.index.year).first() - 1
            P(f"  {L:>4}x{cagr:>+8.0%}{mdd:>+8.0%}{e.iloc[-1] * START / 1e4:>12,.0f} 萬{(f'{(hit.index[0] - dr.index[0]).days / 365.25:.1f} 年' if len(hit) else '沒到'):>10}{f'{yr.idxmin()} {yr.min():+.0%}':>12}{e.min() * START / 1e4:>10,.0f} 萬")
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / "stockfut_compound.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
