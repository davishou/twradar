"""「帳戶只放保證金、加倉到最滿、場外留一筆錢應付追繳」vs「照總資金固定 3 倍槓桿」（2026-11-12）

python -m research.reserve_vs_rebalance <btdata 資料夾>
台指期近月、微台（1 點 10 元）。原始保證金 8.5%、維持 6.5%（近似）。
追繳規則（照台灣期貨商）：盤中權益數 < 原始保證金 25% → 盤中強制平倉；收盤權益數 < 維持保證金 → 追繳，要補到原始保證金，
  場外預備金夠就轉入，不夠就減口數到帳上的錢付得起原始保證金。
A  固定 3 倍：總資金（帳戶＋場外）×3 ÷ 契約價值，每 20 個交易日調一次（就是先前的做法，錢放帳戶或場外結果一樣）
B  滿倉：帳戶只放剛好的原始保證金，每天收盤只要帳上多出來的錢夠一口原始保證金就加一口（加到最滿）；場外預備金只用來補追繳
C  滿倉但加倉時把預備金算進去：口數上限＝總資金×3 ÷ 契約價值（等於 A，只是錢放場外）
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from research import fut_compound as fc

PT, IM, MM = 10.0, fc.IM, fc.MM


def run(t, i0, mode, acct0, reserve0, L=3.0, horizon=None, log=None, fast=False):
    c, pc, lo, roll = t["close"].to_numpy(), t["prev_close"].to_numpy(), t["lo"].to_numpy(), t["roll"].to_numpy()
    n = len(c) - i0 if horizon is None else min(horizon, len(c) - i0)
    a, R = acct0, reserve0
    lots = 0
    tops = 0
    forced = 0
    out = np.empty(n)
    for k in range(n):
        i = i0 + k
        note = ""
        if lots:
            if roll[i]:
                a -= lots * 2 * PT
            worst = a + lots * (lo[i] - pc[i]) * PT
            if fast and worst < MM * lots * lo[i] * PT and R > 0:          # 盤中一跌破維持就立刻從場外轉錢（理想：隨時盯盤、轉帳即時到）
                mv = min(R, IM * lots * lo[i] * PT - worst)
                R -= mv
                a += mv
                worst += mv
                tops += 1
                note = f"盤中低於維持，立刻從場外轉入 {mv:,.0f}"
            if worst < 0.25 * IM * lots * lo[i] * PT:                      # 盤中風險指標 <25%：強制平倉
                forced += 1
                a = worst - lots * 1.5 * PT
                note = f"盤中風險指標<25%，{lots} 口全部被砍"
                lots = 0
            else:
                a += lots * (c[i] - pc[i]) * PT
        if lots and a < MM * lots * c[i] * PT:                             # 收盤低於維持：追繳
            need = IM * lots * c[i] * PT - a
            if R >= need:
                R -= need
                a += need
                tops += 1
                note = f"追繳，從場外轉入 {need:,.0f}"
            else:
                a += R
                R = 0
                keep = int(a / (IM * c[i] * PT))
                note = f"追繳，場外錢不夠（轉入剩下的全部），砍到 {keep} 口"
                a -= (lots - keep) * 1.5 * PT
                lots = keep
                forced += 1
        tot = a + R
        if tot <= 0:
            out[k:] = 0
            if log is not None:
                log.append((t.index[i], c[i], lots, a, R, "賠光"))
            return out, tops, forced
        if mode == "B":
            mx = int(max(a, 0) / (IM * c[i] * PT))
            if lots == 0 and (k == 0 or tot > 0):                           # 一開始、或被砍光後：用場外的錢重新放進剛好的保證金
                tgt = int(tot * L / (c[i] * PT)) if k else 6
                tgt = min(tgt, int(tot / (IM * c[i] * PT)))
                need = IM * tgt * c[i] * PT - a
                mv = min(R, max(need, 0))
                R -= mv
                a += mv
            else:
                tgt = max(lots, mx)
        else:
            if k % 20 == 0 or lots == 0:
                tgt = int(tot * L / (c[i] * PT))
                if mode == "A":
                    a, R = tot, 0.0                                        # 全部放帳上
            else:
                tgt = lots
            tgt = min(tgt, int((a + R) / (IM * c[i] * PT)))
            if mode == "C" and tgt * IM * c[i] * PT > a:                   # 錢放場外，加倉時把需要的保證金轉進去
                mv = min(R, tgt * IM * c[i] * PT - a)
                R -= mv
                a += mv
        if tgt != lots:
            a -= abs(tgt - lots) * (1.5 * PT + 0.00002 * c[i] * PT)
            if log is not None and not note:
                note = f"{'加' if tgt > lots else '減'} {abs(tgt - lots)} 口"
            lots = tgt
        out[k] = (a + R)
        if log is not None and (note or k % 60 == 0 or k == n - 1):
            log.append((t.index[i], c[i], lots, a, R, note))
    return out, tops, forced


def main(argv):
    t = fc.series(argv[0])
    t = t.iloc[200:]
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    i0 = int(t.index.searchsorted(pd.Timestamp("2024-08-01")))
    m0 = IM * 6 * t["close"].iloc[i0] * PT
    P(f"===== 2024-08-01 起（指數 {t['close'].iloc[i0]:,.0f}，6 口微台的原始保證金 {m0:,.0f}） =====")
    for lab, mode, a0, r0, fast in (("A 50 萬全放帳上、固定 3 倍（之前的做法）", "A", 500000, 0, False),
                                    ("B 帳上只放保證金、加倉到最滿、場外另有 50 萬（共 61.6 萬）；盤中來不及轉錢", "B", m0, 500000, False),
                                    ("B 同上，但盤中一跌破維持就立刻轉錢（理想盯盤）", "B", m0, 500000, True),
                                    ("A' 61.6 萬全放帳上、固定 3 倍（和 B 一樣多的錢）", "A", m0 + 500000, 0, False)):
        log = []
        e, tops, forced = run(t, i0, mode, a0, r0, log=log, fast=fast)
        P(f"\n--- {lab}：最後 {e[-1]:,.0f}、最高 {e.max():,.0f}、追繳 {tops} 次、被砍 {forced} 次 ---")
        for d, cc, lots, a, R, note in log:
            if note or d == log[-1][0]:
                P(f"  {d.date()} 指數 {cc:>7,.0f}  {lots:>4} 口  帳上 {a:>11,.0f}  場外 {R:>9,.0f}  合計 {a + R:>11,.0f}  實際槓桿 {lots * cc * PT / max(a + R, 1):>5.1f}x  {note}")
    P("\n===== 換起點（2006 起每 20 個交易日一個，跑 5 年；總資金都是 50 萬） =====")
    P(f"{'做法':<40}{'5 年後中位':>10}{'最好10%':>10}{'最差10%':>10}{'5 年內賠光（剩<5萬）':>14}{'曾經翻 5 倍':>10}")
    starts = list(range(0, len(t) - 248 * 5, 20))
    for lab, mode, split, fast in (("A 固定 3 倍（錢全放帳上）", "A", False, False),
                                   ("B 滿倉、加到最滿；盤中來不及轉錢", "B", True, False),
                                   ("B 滿倉、加到最滿；理想盯盤即時轉錢", "B", True, True),
                                   ("C 錢放場外、照總資金 3 倍；來不及轉錢", "C", True, False),
                                   ("C 錢放場外、照總資金 3 倍；即時轉錢", "C", True, True)):
        fin, bust, x5 = [], 0, 0
        for s0 in starts:
            px0 = t["close"].iloc[s0]
            m = IM * int(500000 * 3 / (px0 * PT)) * px0 * PT
            e, _, _ = run(t, s0, mode, m if split else 500000, (500000 - m) if split else 0, horizon=248 * 5, fast=fast)
            fin.append(e[-1] / 500000)
            bust += e.min() < 50000
            x5 += e.max() >= 2_500_000
        P(f"{lab:<36}{np.median(fin):>10.2f}x{np.percentile(fin, 90):>9.2f}x{np.percentile(fin, 10):>9.2f}x{bust / len(starts):>14.0%}{x5 / len(starts):>11.0%}")
    P(f"（{len(starts)} 個起點，互相重疊）")
    from research import portfolio as pf
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / "reserve_vs_rebalance.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
