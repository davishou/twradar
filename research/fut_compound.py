"""期貨獲利滾入保證金（複利加碼）模擬：50 萬 → 1000 萬（20 倍）（2026-11-10）

python -m research.fut_compound <btdata 資料夾>

資料：台指期近月每日行情 2005~2026（含 2017/5 起的夜盤高低點）。只做多。口數用微台（1 點 10 元）算，才能細分。
做法：
  固定口數   一開始照槓桿買，之後不加不減（沒有複利，對照用）
  固定槓桿   每天收盤看淨值，口數調回「淨值×槓桿÷契約價值」——賺了加、賠了減（這就是『獲利滾入保證金』的標準做法）
  只加不減   賺了加口數，賠了不減（最常聽到的『滾倉』；回檔時實際槓桿會自己變大）
  ＋趨勢濾網 收盤跌破 N 日線全部出場、站回再進（60／200 日線）
保證金：原始 8.5%、維持 6.5%（契約價值的比例，近似）。盤中最低點（含夜盤）若淨值低於維持保證金 → 在那個價位被砍到剩「淨值÷原始保證金」能撐的口數；
        淨值 ≤0 視為賠光（實際上還會倒欠）。成本：每口每次進出 1.5 點＋期交稅，每月換倉每口 2 點。
統計：從 2005 起每 20 個交易日當一個起點，各跑一次，看 5 年／10 年內到 20 倍的比例、曾經賠掉 8 成（剩 <10 萬）的比例。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from research import fo_bt as fb

PT, START, TARGET = 10.0, 500_000.0, 20.0
IM, MM = 0.085, 0.065


def series(folder):
    f = fb.load_fut(folder)
    t = fb.day_night(f)
    n = f[f["session"] == "盤後"].set_index(["date", "contract"])["low"]
    t["n_low"] = [n.get((d, c), np.nan) for d, c in zip(t.index, t["contract"])]
    t["lo"] = t[["low", "n_low"]].min(axis=1)
    t = t.dropna(subset=["prev_close"])
    t["roll"] = t["contract"] != t["contract"].shift(1)
    return t


def simulate(t, i0, L, mode, ma, horizon):
    """回傳（每日淨值倍數陣列, 是否被強制砍倉次數）"""
    c, pc, lo, roll = t["close"].to_numpy(), t["prev_close"].to_numpy(), t["lo"].to_numpy(), t["roll"].to_numpy()
    above = t[f"ma{ma}"].to_numpy() if ma else None
    eq = START
    lots = 0
    out = np.empty(min(horizon, len(c) - i0))
    forced = 0
    want_in = True
    for k in range(len(out)):
        i = i0 + k
        if lots:
            if roll[i]:
                eq -= lots * 2 * PT
            worst = eq + lots * (lo[i] - pc[i]) * PT                       # 盤中最低點的淨值
            if worst < MM * lots * lo[i] * PT:
                forced += 1
                if worst <= 0:
                    out[k:] = 0.0
                    return out, forced
                keep = int(worst / (IM * lo[i] * PT))
                eq = worst - (lots - keep) * 1.5 * PT
                eq += keep * (c[i] - lo[i]) * PT
                lots = keep
            else:
                eq += lots * (c[i] - pc[i]) * PT
        if eq <= 0:
            out[k:] = 0.0
            return out, forced
        # 收盤後調整口數
        on = True if above is None else bool(above[i])
        if not on:
            tgt = 0
        else:
            full = int(eq * L / (c[i] * PT))
            if lots == 0:
                tgt = full
            elif mode == "fixed":
                tgt = lots
            elif mode == "addonly":
                tgt = max(lots, full)
            else:
                tgt = full
        tgt = min(tgt, int(eq / (IM * c[i] * PT)))                         # 不能超過保證金上限
        if tgt != lots:
            eq -= abs(tgt - lots) * (1.5 * PT + 0.00002 * c[i] * PT)
            lots = tgt
        out[k] = eq / START
    return out, forced


def main(argv):
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    t = series(argv[0])
    for n in (60, 200):
        t[f"ma{n}"] = t["close"] > t["close"].rolling(n).mean()
    t = t.iloc[200:]
    r = t["close"] / t["prev_close"] - 1
    yrs = (t.index[-1] - t.index[0]).days / 365.25
    P(f"台指期近月 {t.index[0].date()} ~ {t.index[-1].date()}（{len(t)} 天）。不開槓桿一直抱：年化 {(1 + r).prod() ** (1 / yrs) - 1:+.1%}；日報酬平均 {r.mean() * 1e4:.1f}bp、標準差 {r.std():.2%}")
    P(f"單日最大跌幅（收盤）{r.min():.1%}；含盤中／夜盤最低點的單日最大跌幅 {(t['lo'] / t['prev_close'] - 1).min():.1%}（{(t['lo'] / t['prev_close'] - 1).idxmin().date()}）")
    dd = (1 + r).cumprod()
    P(f"不開槓桿的最大回落 {(dd / dd.cummax() - 1).min():.0%}；理論上讓長期成長最快的槓桿（凱利）≈ {r.mean() / r.var():.1f} 倍，實務常用一半 ≈ {r.mean() / r.var() / 2:.1f} 倍")
    P("\n一、整段 2005~2026 從頭抱到尾（50 萬起步，淨值倍數）")
    P(f"{'做法':<26}{'槓桿':>5}{'最後倍數':>10}{'年化':>8}{'最大回落':>8}{'被砍倉':>6}{'到 20 倍花幾年':>12}")
    cfgs = []
    for mode, ma, lab in (("fixed", 0, "固定口數（不滾）"), ("const", 0, "固定槓桿（賺加賠減）"), ("addonly", 0, "只加不減"),
                          ("const", 200, "固定槓桿＋200日線濾網"), ("const", 60, "固定槓桿＋60日線濾網"), ("addonly", 200, "只加不減＋200日線濾網")):
        for L in (1, 2, 3, 4, 6, 8, 10):
            cfgs.append((mode, ma, lab, L))
    for mode, ma, lab, L in cfgs:
        e, fc = simulate(t, 0, L, mode, ma, len(t))
        cagr = e[-1] ** (1 / yrs) - 1 if e[-1] > 0 else -1
        mdd = (e / np.maximum.accumulate(e) - 1).min()
        hit = np.argmax(e >= TARGET) if (e >= TARGET).any() else -1
        P(f"{lab:<24}{L:>5}x{e[-1]:>11.1f}x{cagr:>+8.0%}{mdd:>+8.0%}{fc:>6}{(f'{hit / 248:.1f} 年' if hit >= 0 else '沒到'):>12}")
    P("\n二、換不同起點（每 20 個交易日一個起點）：5 年內／10 年內到 20 倍（1000 萬）的機率，與途中曾剩不到 10 萬（賠 8 成）的機率")
    P(f"{'做法':<26}{'槓桿':>5}{'5年內到20倍':>10}{'10年內到20倍':>11}{'10年後中位':>10}{'10年後最差10%':>12}{'曾賠8成以上':>10}{'賠光':>6}{'5年後中位':>9}")
    starts5 = list(range(0, len(t) - 248 * 5, 20))
    starts10 = list(range(0, len(t) - 248 * 10, 20))
    for mode, ma, lab, L in cfgs:
        if mode == "fixed":
            continue
        h5 = h10 = bust = zero = 0
        f10, f5 = [], []
        for i0 in starts5:
            e, _ = simulate(t, i0, L, mode, ma, 248 * 10)
            e5 = e[:248 * 5]
            first = np.argmax(e5 >= TARGET) if (e5 >= TARGET).any() else len(e5)
            lowbefore = e5[:first + 1].min()
            h5 += first < len(e5)
            f5.append(e5[-1])
            if i0 in starts10:
                first10 = np.argmax(e >= TARGET) if (e >= TARGET).any() else len(e)
                h10 += first10 < len(e)
                f10.append(e[-1])
                bust += e[:first10 + 1].min() < 0.2
                zero += e.min() <= 0.02
        P(f"{lab:<24}{L:>5}x{h5 / len(starts5):>11.0%}{h10 / len(starts10):>12.0%}{np.median(f10):>10.1f}x{np.percentile(f10, 10):>12.2f}x{bust / len(starts10):>11.0%}{zero / len(starts10):>7.0%}{np.median(f5):>9.1f}x")
    P(f"（5 年起點 {len(starts5)} 個、10 年起點 {len(starts10)} 個；起點互相重疊，不是獨立樣本。2005~2026 整體是大多頭，指數從 6 千到 4 萬多）")
    P("\n三、如果起點落在最不利的時候（固定槓桿，賺加賠減）：2007/10 高點前、2020/2 疫情前、2022/1 高點、2025/3 關稅前")
    for d in ("2007-10-01", "2011-07-01", "2020-02-01", "2022-01-03", "2025-03-03"):
        i0 = int(t.index.searchsorted(pd.Timestamp(d)))
        row = []
        for L in (1, 2, 3, 4, 6):
            e, fc = simulate(t, i0, L, "const", 0, 248 * 3)
            row.append(f"{L}x：最低剩 {e.min():.2f}、3 年後 {e[-1]:.2f}")
        P(f"  {d} 起：" + "｜".join(row))
    from research import portfolio as pf
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / "fut_compound.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
