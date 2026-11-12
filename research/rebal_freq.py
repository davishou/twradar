"""槓桿多久調一次？每月、每週、每天、只在偏離太多時調（2026-11-12）

python -m research.rebal_freq <btdata 資料夾>
台指期近月、微台（1 點 10 元）、只做多、目標槓桿 L。原始保證金 8.5%、維持 6.5%；盤中最低點（含夜盤）跌破維持就在那個價位被砍到原始保證金撐得住的口數。
調整方式（都在收盤調；日資料做不到盤中調）：
  每月  每 20 個交易日照淨值調回 L
  每週  每 5 個交易日
  每天  每天收盤
  區間  每天看，實際槓桿超出 [L−0.5, L+0.5] 才調回 L（漲了加、跌了減，平常不動）
  只減  區間的下跌那一半：槓桿 > L+0.5 時減回 L；上漲時每月才加
成本：每口每次 1.5 點滑價＋期交稅，換倉每口 2 點。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from research import fut_compound as fc

PT, IM, MM = 10.0, fc.IM, fc.MM


def sim(t, i0, L, how, horizon):
    c, pc, lo, roll = t["close"].to_numpy(), t["prev_close"].to_numpy(), t["lo"].to_numpy(), t["roll"].to_numpy()
    n = min(horizon, len(c) - i0)
    eq, lots, out, trades, forced = 500_000.0, 0, np.empty(n), 0, 0
    maxlev = 0.0
    for k in range(n):
        i = i0 + k
        if lots:
            if roll[i]:
                eq -= lots * 2 * PT
            worst = eq + lots * (lo[i] - pc[i]) * PT
            maxlev = max(maxlev, lots * lo[i] * PT / worst if worst > 0 else 99)
            if worst < MM * lots * lo[i] * PT:
                forced += 1
                if worst <= 0:
                    out[k:] = 0
                    return out, trades, forced, maxlev
                keep = int(worst / (IM * lo[i] * PT))
                eq = worst - (lots - keep) * 1.5 * PT + keep * (c[i] - lo[i]) * PT
                lots = keep
            else:
                eq += lots * (c[i] - pc[i]) * PT
        if eq <= 0:
            out[k:] = 0
            return out, trades, forced, maxlev
        lev = lots * c[i] * PT / eq
        full = int(eq * L / (c[i] * PT))
        if lots == 0 and k == 0:
            tgt = full
        elif how == "month":
            tgt = full if k % 20 == 0 else lots
        elif how == "week":
            tgt = full if k % 5 == 0 else lots
        elif how == "day":
            tgt = full
        elif how == "band":
            tgt = full if (lev > L + 0.5 or lev < L - 0.5) else lots
        elif how == "cut":
            tgt = full if (lev > L + 0.5 or (k % 20 == 0 and full > lots)) else lots
        else:
            tgt = lots
        tgt = min(tgt, int(eq / (IM * c[i] * PT)))
        if tgt != lots:
            eq -= abs(tgt - lots) * (1.5 * PT + 0.00002 * c[i] * PT)
            trades += 1
            lots = tgt
        out[k] = eq / 500_000
    return out, trades, forced, maxlev


def main(argv):
    t = fc.series(argv[0]).iloc[200:]
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    r = t["close"] / t["prev_close"] - 1
    ac = [r.autocorr(k) for k in (1, 2, 5)]
    r5 = t["close"].pct_change(5)
    r20 = t["close"].pct_change(20)
    P(f"台指期日報酬的自我相關：隔 1 天 {ac[0]:+.3f}、2 天 {ac[1]:+.3f}、5 天 {ac[2]:+.3f}；週報酬隔週 {r5[::5].autocorr():+.3f}；月報酬隔月 {r20[::20].autocorr():+.3f}")
    P("（正＝漲了容易再漲，常調比較好；負＝漲了容易拉回，常調反而吃虧）")
    hows = (("month", "每月調"), ("week", "每週調"), ("day", "每天調"), ("band", "偏離 ±0.5 倍才調"), ("cut", "超過 +0.5 倍立刻減、加碼每月"), ("none", "口數永遠不動"))
    for L in (2, 3, 4):
        P(f"\n===== 目標 {L} 倍：2005~2026 從頭抱到尾，與換起點跑 5 年（197 個起點） =====")
        P(f"{'做法':<26}{'整段年化':>8}{'整段回落':>8}{'每年調幾次':>9}｜{'5年中位':>8}{'最差10%':>8}{'最好10%':>8}{'5年回落中位':>10}{'賠8成以上':>8}{'被砍倉':>6}{'最高槓桿中位':>10}")
        for how, lab in hows:
            e, tr, fcount, _ = sim(t, 0, L, how, len(t))
            yrs = len(e) / 248
            cagr = e[-1] ** (1 / yrs) - 1 if e[-1] > 0 else -1
            mdd = (e / np.maximum.accumulate(e) - 1).min()
            fin, dds, b8, fz, ml = [], [], 0, 0, []
            for s0 in range(0, len(t) - 248 * 5, 20):
                x, _, fc_, mx = sim(t, s0, L, how, 248 * 5)
                fin.append(x[-1])
                dds.append((x / np.maximum.accumulate(x) - 1).min())
                b8 += x.min() < 0.2
                fz += fc_ > 0
                ml.append(mx)
            n = len(fin)
            P(f"{lab:<24}{cagr:>+8.1%}{mdd:>+8.0%}{tr / yrs:>9.1f}｜{np.median(fin):>7.2f}x{np.percentile(fin, 10):>7.2f}x{np.percentile(fin, 90):>7.2f}x{np.median(dds):>+10.0%}{b8 / n:>8.0%}{fz / n:>6.0%}{np.median(ml):>10.1f}x")
    P("\n===== 幾次大跌時，每月調 vs 偏離 ±0.5 倍才調（3 倍；從大跌前一個月的月初開始） =====")
    for d0, d1, lab in (("2008-05-01", "2009-03-31", "2008 金融海嘯"), ("2015-04-01", "2015-09-30", "2015 股災"), ("2020-02-03", "2020-06-30", "2020 疫情"),
                        ("2022-01-03", "2022-10-31", "2022 空頭"), ("2024-07-01", "2024-09-30", "2024/8 日圓套利平倉"), ("2025-03-03", "2025-05-30", "2025/4 關稅"),
                        ("2026-10-01", "2026-11-09", "2026/11 最近這次")):
        i0 = int(t.index.searchsorted(pd.Timestamp(d0)))
        h = int(t.index.searchsorted(pd.Timestamp(d1))) - i0 + 1
        row = []
        for how, nm in (("month", "每月"), ("band", "偏離才調"), ("day", "每天"), ("none", "不動")):
            e, tr, fcount, mx = sim(t, i0, 3, how, h)
            row.append(f"{nm} 最低 {e.min():.2f}／最後 {e[-1]:.2f}（最高槓桿 {mx:.1f}x{'，被砍' if fcount else ''}）")
        P(f"  {lab}（指數 {t['close'].iloc[i0]:,.0f} → 最低 {t['lo'].iloc[i0:i0 + h].min():,.0f} → {t['close'].iloc[i0 + h - 1]:,.0f}）：" + "｜".join(row))
    from research import portfolio as pf
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / "rebal_freq.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
