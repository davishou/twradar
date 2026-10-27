"""鄭大訊號：不同持有週期＋條件分組（探索用，回應使用者 2026-10-27 的補充）

python -m research.cb_signals_horizon [cache_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research import cb_signals as cs

HZ = (1, 5, 10, 20, 60)


def load(cache: Path) -> pd.DataFrame:
    p = cache / "panel.pkl"
    if p.exists():
        return pd.read_pickle(p)
    cs.H = HZ
    q = cs.panel()
    q = q[q["date"] >= q.loc[q["conv"].notna(), "date"].min()].copy()
    q.to_pickle(p)
    return q


def dedupe(q, mask, gap=20):
    """同一檔 gap 個交易日內只算第一次"""
    sub = q[mask.fillna(False).astype(bool)]
    k = q.groupby("code").cumcount()
    keep, last = [], {}
    for i, c in zip(sub.index, sub["code"]):
        if c in last and k[i] - last[c] < gap:
            continue
        last[c] = k[i]
        keep.append(i)
    return q.loc[keep]


def row(e, label):
    r = {"組": label, "次數": len(e)}
    for n in HZ:
        x = e[f"ex{n}"].dropna()
        r[f"股{n}"] = f"{x.mean():+.1%}/{(x > 0).mean():.0%}" if len(x) > 10 else "—"
    for n in (5, 20, 60):
        x = (e[f"cb{n}"] - e[f"cbbase{n}"]).dropna()
        r[f"CB{n}"] = f"{x.mean():+.1%}" if len(x) > 10 else "—"
    return r


def show(title, groups):
    print(f"\n== {title} ==   股N＝標的股 N 日超額 平均/勝率（隔天收盤進場）；CBN＝CB 比全部 CB 多")
    print(pd.DataFrame([row(e, l) for l, e in groups]).to_string(index=False))


def main():
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("research/out")
    cache.mkdir(parents=True, exist_ok=True)
    q = load(cache)
    q["pos60"] = (q["stockpx"] - q["slo60"]) / (q["shi60"] - q["slo60"])   # 股價在前 60 日區間的位置 0~1
    g = q.groupby("code", sort=False)
    q["hi10"] = g["price"].transform(lambda s: s.shift(1).rolling(9, min_periods=9).max())
    q["shi10"] = q.groupby("scode", sort=False)["stockpx"].transform(lambda s: s.shift(1).rolling(9, min_periods=9).max())
    q["mret20"] = q.groupby("date")["sret20"].transform("mean")
    base = dedupe(q, q["ex20"].notna() & (q["date"].dt.dayofweek == 2), gap=1)   # 基準：每週三所有 CB 標的
    show("基準（所有發 CB 的股票，每週取一天）", [("全部", base)])

    # 1. CB 過高股未過高：短線
    px, st = q["price"], q["stockpx"]
    m = (px > q["hi60"]) & px.between(105, 150) & (st < q["shi60"] * 0.97)
    show("1. CB 過高股未過高（短線看股票）", [
        ("原規則（CB 60 日高、股低於高點 3%+）", dedupe(q, m)),
        ("股價離高點 3~10%", dedupe(q, m & (st >= q["shi60"] * 0.90))),
        ("股價離高點 >10%", dedupe(q, m & (st < q["shi60"] * 0.90))),
        ("CB 10 日新高、股未過 10 日高", dedupe(q, (px > q["hi10"]) & px.between(105, 150) & (st < q["shi10"]))),
        ("同上＋溢價 > 10%", dedupe(q, (px > q["hi10"]) & px.between(105, 150) & (st < q["shi10"]) & (px / q["conv"] > 1.10))),
    ])

    # 2. CB 爆量：低檔 vs 高檔，漲 vs 跌
    vol = (q["lots"] >= 100) & (q["lots"] >= 5 * q["v20"])
    up, dn = q["chg"] >= 0, q["chg"] < 0
    show("2. CB 爆量（量 ≥ 20 日均量 5 倍且 ≥ 100 張）", [
        ("全部", dedupe(q, vol)),
        ("CB ≤ 105", dedupe(q, vol & (px <= 105))),
        ("CB 105~115", dedupe(q, vol & px.between(105, 115, inclusive="right"))),
        ("CB 115~130", dedupe(q, vol & px.between(115, 130, inclusive="right"))),
        ("CB > 130（高檔）", dedupe(q, vol & (px > 130))),
        ("股價在 60 日區間下 1/3", dedupe(q, vol & (q["pos60"] <= 1 / 3))),
        ("股價在 60 日區間上 1/3", dedupe(q, vol & (q["pos60"] >= 2 / 3))),
        ("低檔（CB≤110 且股下 1/3）＋當天漲", dedupe(q, vol & (px <= 110) & (q["pos60"] <= 1 / 3) & up)),
        ("低檔（CB≤110 且股下 1/3）＋當天跌", dedupe(q, vol & (px <= 110) & (q["pos60"] <= 1 / 3) & dn)),
        ("高檔（CB>130 或股上 1/3）＋當天漲", dedupe(q, vol & ((px > 130) | (q["pos60"] >= 2 / 3)) & up)),
    ])

    # 3. 股崩 CB 撐：對照組＝股票一樣崩、但 CB 也跟跌
    crash = q["sret20"] <= -0.15
    hold, follow = crash & (q["cret20"] > -0.03), crash & (q["cret20"] <= -0.08)
    eh, ef = dedupe(q, hold), dedupe(q, follow)
    show("3. 股崩 CB 撐（股 20 日 −15% 以上）", [
        ("CB 撐住（20 日跌 < 3%）", eh), ("對照：CB 也跌 8% 以上", ef),
        ("CB 撐住＋CB ≤ 105（債底附近）", dedupe(q, hold & (px <= 105))),
        ("CB 撐住＋CB > 110（溢價撐）", dedupe(q, hold & (px > 110))),
        ("CB 撐住＋大盤也崩（全市場 20 日平均 < −8%）", dedupe(q, hold & (q["mret20"] < -0.08))),
    ])
    for lab, e in (("CB 撐住", eh), ("CB 也跌", ef)):
        c = e["cb20"].dropna()
        print(f"  {lab}：之後 20 日 CB 再跌 5% 以上的機率 {(c <= -0.05).mean():.0%}，股票 20 日內反彈（超額 > +5%）機率 {(e['ex20'].dropna() > 0.05).mean():.0%}")

    # 4. 上市第 6 天
    a6 = q["age"] == 6
    show("4. 上市第 6 天", [
        ("全部", dedupe(q, a6)),
        ("大盤偏弱（全市場 20 日平均 < 0）", dedupe(q, a6 & (q["mret20"] < 0))),
        ("大盤偏強", dedupe(q, a6 & (q["mret20"] >= 0))),
        ("CB ≥ 115（溢價高）", dedupe(q, a6 & (px >= 115))),
        ("CB < 108", dedupe(q, a6 & (px < 108))),
        ("2025/6 以後", dedupe(q, a6 & (q["date"] >= "2025-06-01"))),
    ])
    e6 = dedupe(q, a6)
    c = e6["cb20"].dropna()
    print(f"  上市第 6 天買 CB 持有 20 日：平均 {c.mean():+.2%}、勝率 {(c > 0).mean():.0%}（他的 XQ：68 次、勝率 56%、平均 +0.48%）")

    # 5. CB 先破底、跌破面額：看股票（他是放空股票）
    lowm = (px < q["lo60"]) & (px < 105) & (st > q["slo60"] * 1.05)
    b100 = (px < 98) & (q["lo60"] >= 98)
    groups = [("CB 先破底（原規則）", dedupe(q, lowm)), ("跌破面額（原規則）", dedupe(q, b100)),
              ("跌破面額＋股價在 60 日區間上半", dedupe(q, b100 & (q["pos60"] >= 0.5))),
              ("跌破面額＋轉換價值 ≥ 90（股價不低卻沒人要）", dedupe(q, b100 & (q["conv"] >= 90)))]
    show("5. 警訊（看股票之後會不會落後；放空看負的）", groups)
    for lab, e in groups:
        x = e["ex60"].dropna(); y = e["ex20"].dropna()
        print(f"  {lab}：股 20 日落後大盤 10% 以上機率 {(y <= -0.10).mean():.0%}，60 日 {(x <= -0.15).mean():.0%}（落後 15%+）")
    bx = base["ex20"].dropna(); by = base["ex60"].dropna()
    print(f"  基準：20 日落後 10%+ {(bx <= -0.10).mean():.0%}，60 日落後 15%+ {(by <= -0.15).mean():.0%}")


if __name__ == "__main__":
    main()
