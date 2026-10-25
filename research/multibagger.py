"""飆股研究：之後半年內漲 2 倍以上的股票，起漲前和一般股票差在哪？

做法：
  1. 每月最後一個交易日當「觀察日」t，對每檔股票算之後 120 個交易日（約半年）內的最高價 ÷ t 收盤（還原價）。
     ≥2 倍＝翻倍股，≥5 倍＝大飆股。
  2. 比較 t 當下就知道的特徵：規模（成交金額）、股價、前期漲跌、離一年高點多遠、量能變化、
     法人買賣、融資、前 20 日漲停次數、產業。
  3. 看每個特徵分組後「之後翻倍的機率」，對照全體的基準機率（提升倍數 lift）。
注意：這是「哪些條件下比較常出現飆股」，不是買進訊號；翻倍是用期間最高價算的，賣在最高點不現實。

python -m research.multibagger
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline import backtest as bt

FWD = 120


def panel():
    q = bt.load_quotes()
    q = q.sort_values(["code", "date"]).reset_index(drop=True)
    g = q.groupby("code", sort=False)
    q["adj_high"] = q["high"] / q["cumf"]
    # 之後 120 日最高（不含當天）
    q["fwd_max"] = g["adj_high"].transform(lambda s: s[::-1].rolling(FWD, min_periods=FWD).max()[::-1].shift(-1))
    q["mult"] = q["fwd_max"] / q["adj"]
    q["val20"] = g["value"].transform(lambda s: s.rolling(20, min_periods=15).mean()) / 1e8      # 日均成交金額（億）
    q["ret20"] = g["adj"].transform(lambda s: s / s.shift(20) - 1)
    q["ret120"] = g["adj"].transform(lambda s: s / s.shift(120) - 1)
    q["off250"] = q["adj"] / g["adj"].transform(lambda s: s.rolling(250, min_periods=120).max()) - 1
    q["vol_trend"] = g["volume"].transform(lambda s: s.rolling(20, min_periods=15).mean() / s.rolling(120, min_periods=60).mean())
    q["volat"] = g["adj"].transform(lambda s: s.pct_change().rolling(60, min_periods=40).std() * np.sqrt(250))
    q["lu20"] = g["is_lu"].transform(lambda s: s.astype(int).rolling(20, min_periods=1).sum())
    inst = bt.load_inst()
    for c in ("foreign", "trust"):
        inst[c] = pd.to_numeric(inst[c], errors="coerce")
    q = q.merge(inst[["date", "code", "foreign", "trust"]], on=["date", "code"], how="left")
    g = q.groupby("code", sort=False)
    lots20 = g["volume"].transform(lambda s: s.rolling(20, min_periods=15).sum()) / 1000
    for c, k in (("foreign", "f20"), ("trust", "t20")):
        q[k] = g[c].transform(lambda s: s.fillna(0).rolling(20, min_periods=15).sum()) / lots20 * 100
    # 月底取樣
    q["ym"] = q["date"].dt.to_period("M")
    last = q.groupby("ym")["date"].transform("max")
    p = q[(q["date"] == last) & q["mult"].notna() & (q["volume"] > 0)].copy()
    comp = bt.companies()
    p["industry"] = p["code"].map(lambda c: (comp.get(c) or {}).get("industry", "") or "其他")
    p["y2"] = p["mult"] >= 2
    p["y5"] = p["mult"] >= 5
    return p


def lift_table(p, col, bins, labels, y="y2"):
    base = p[y].mean()
    bk = pd.cut(p[col], bins=bins, labels=labels, right=False)
    rows = []
    for b, s in p.groupby(bk, observed=True):
        rows.append({"分組": b, "樣本": len(s), "翻倍機率": f"{s[y].mean():.1%}", "提升": f"{s[y].mean() / base:.1f}x",
                     "占全部翻倍股": f"{s[y].sum() / p[y].sum():.0%}"})
    return pd.DataFrame(rows).to_string(index=False)


def main():
    p = panel()
    out = [f"樣本：{p['date'].min().date()} ~ {p['date'].max().date()} 每月底，共 {len(p):,} 筆（股票×月）",
           f"之後半年內最高曾翻倍（≥2 倍）：{p['y2'].mean():.1%}；≥5 倍：{p['y5'].mean():.2%}", ""]
    specs = [
        ("val20", "日均成交金額（億）", [0, 0.1, 0.3, 1, 3, 10, np.inf], ["<0.1", "0.1-0.3", "0.3-1", "1-3", "3-10", "≥10"]),
        ("adj", "股價（還原）", [0, 15, 30, 60, 120, np.inf], ["<15", "15-30", "30-60", "60-120", "≥120"]),
        ("ret20", "前 20 日漲幅", [-np.inf, -0.1, 0, 0.1, 0.3, np.inf], ["<-10%", "-10~0%", "0~10%", "10~30%", "≥30%"]),
        ("ret120", "前 120 日漲幅", [-np.inf, -0.3, 0, 0.3, 1, np.inf], ["<-30%", "-30~0%", "0~30%", "30~100%", "≥100%"]),
        ("off250", "離一年高點", [-np.inf, -0.6, -0.3, -0.1, -0.0001, np.inf], ["跌>60%", "跌30~60%", "跌10~30%", "跌<10%", "創一年新高"]),
        ("vol_trend", "近20日量÷近120日量", [0, 0.7, 1, 1.5, 3, np.inf], ["<0.7", "0.7-1", "1-1.5", "1.5-3", "≥3"]),
        ("volat", "波動度（年化）", [0, 0.3, 0.45, 0.6, 0.9, np.inf], ["<30%", "30-45%", "45-60%", "60-90%", "≥90%"]),
        ("lu20", "前20日漲停次數", [0, 1, 2, 4, np.inf], ["0", "1", "2-3", "≥4"]),
        ("f20", "外資20日買超占量%", [-np.inf, -5, -1, 1, 5, np.inf], ["賣>5%", "賣1~5%", "±1%", "買1~5%", "買>5%"]),
        ("t20", "投信20日買超占量%", [-np.inf, -0.5, 0.5, 3, np.inf], ["賣", "≈0", "買0.5~3%", "買>3%"]),
    ]
    for col, name, bins, labels in specs:
        out += [f"=== {name} ===", lift_table(p, col, bins, labels), ""]
    ind = p.groupby("industry").agg(樣本=("y2", "size"), 翻倍機率=("y2", "mean"), 翻倍數=("y2", "sum")).query("樣本>=300")
    ind["提升"] = ind["翻倍機率"] / p["y2"].mean()
    out += ["=== 產業（翻倍機率前 12） ===",
            ind.sort_values("翻倍機率", ascending=False).head(12).assign(翻倍機率=lambda d: d["翻倍機率"].map("{:.1%}".format),
                                                                   提升=lambda d: d["提升"].map("{:.1f}x".format)).to_string()]
    # 組合：小型＋量增＋接近新高
    m = (p["val20"] < 1) & (p["vol_trend"] >= 1.5) & (p["off250"] > -0.1)
    out += ["", f"組合（日均成交<1億、量能放大≥1.5倍、離一年高點<10%）：樣本 {m.sum():,}，翻倍機率 {p.loc[m, 'y2'].mean():.1%}"
            f"（{p.loc[m, 'y2'].mean() / p['y2'].mean():.1f}x），≥5 倍 {p.loc[m, 'y5'].mean():.2%}"]
    yr = p.groupby(p["date"].dt.year)["y2"].mean()
    out += ["各年翻倍機率：" + "　".join(f"{y}: {v:.1%}" for y, v in yr.items())]
    print("\n".join(out))
    return p


if __name__ == "__main__":
    main()
