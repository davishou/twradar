"""飆股反推（第二版，2026-11-10）：起漲前一天看得到什麼？每個特徵讓飆股機率提高幾倍？

和第一版（multibagger.py，半年內最高價翻倍）的差別：
  - 用 2005 起完整資料、每 5 個交易日取樣一次；只看買得到的（20 日均成交 ≥ 3,000 萬）。
  - 飆股＝之後 60 個交易日內「收盤」最高曾 ≥ +50%（不用盤中最高價）。
  - 同時算壞的一面：60 日內收盤最低曾 ≤ −25%（重摔）、以及 60 日後的實際報酬（平均、中位、贏全市場幾點）。
    只會提高「飆」也提高「摔」的特徵＝只是波動大，沒有用。
  - 加入月營收（當天已公布的最新一期）與收縮特徵（布林寬度、振幅收縮、量縮、帶量突破）。
  - 分三段（2005~12、2013~19、2020~26）看提升倍數穩不穩。
下市／停牌：之後的價格用最後一個收盤價補（最多 60 日），不丟掉。
注意：這是「機率分布」，不是買進訊號；真正的買賣回測在 vcp_bt.py。

python -m research.multibagger2
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from research import portfolio as pf
from research import squeeze as sq

FWD, UP, DN, STEP, MINLIQ = 60, 0.5, -0.25, 5, 3e7


def panel() -> pd.DataFrame:
    f = sq.feats()
    px = f["px"]
    pf_ = px.ffill(limit=FWD)
    rev = lambda m: m[::-1]  # noqa: E731
    fmax = rev(rev(pf_).rolling(FWD, min_periods=FWD).max()).shift(-1)
    fmin = rev(rev(pf_).rolling(FWD, min_periods=FWD).min()).shift(-1)
    fwd = pf_.shift(-FWD) / px - 1
    ew = f["ew"]
    mk = ew.shift(-FWD) / ew - 1
    mk60 = ew / ew.shift(60) - 1
    R = sq.revenue_state(px.index, px.columns)
    days = px.index[250:len(px.index) - FWD:STEP]
    cols = {"near": f["near"], "ret20": f["ret20"], "ret60": f["ret60"], "ret120": f["ret120"], "val20": f["val20"],
            "bbw_pct": f["bbw_pct"], "rng": f["rng"], "vdry": f["vdry"], "vx": f["vx"], "volat": f["volat"], "lu20": f["lu20"],
            "hi20": f["hi20"].astype("float32"), "hi60": f["hi60"].astype("float32"),
            "yoy": R["yoy"], "accel": R["accel"], "high": R["high"],
            "up": (fmax / px - 1), "dn": (fmin / px - 1), "fwd": fwd}
    parts = []
    for k, m in cols.items():
        s = m.loc[days].stack(future_stack=True)
        s.name = k
        parts.append(s)
    p = pd.concat(parts, axis=1).reset_index()
    p.columns = ["date", "code"] + list(cols)
    p = p[p["fwd"].notna() & (p["val20"] >= MINLIQ) & p["near"].notna()].copy()
    p["mk"] = p["date"].map(mk)
    p["mk60"] = p["date"].map(mk60)
    p["xs"] = p["fwd"] - p["mk"]
    p["boom"] = p["up"] >= UP
    p["bust"] = p["dn"] <= DN
    p["era"] = pd.cut(p["date"].dt.year, [0, 2012, 2019, 2100], labels=["05~12", "13~19", "20~26"])
    return p


def row(s, base, name):
    b = s["boom"].mean()
    era = "／".join(f"{(g['boom'].mean() / base_e if base_e else np.nan):.1f}" for (e, g), base_e in zip(s.groupby("era", observed=False), base["era"]))
    return {"分組": name, "樣本": len(s), "飆股機率": f"{b:.1%}", "提升": f"{b / base['boom']:.1f}x", "三段提升": era,
            "重摔機率": f"{s['bust'].mean():.1%}", "摔÷飆": f"{s['bust'].mean() / b:.1f}" if b else "—",
            "60日平均": f"{s['fwd'].mean():+.1%}", "中位": f"{s['fwd'].median():+.1%}", "贏全市場": f"{s['xs'].mean():+.1%}",
            "賺錢": f"{(s['fwd'] > 0).mean():.0%}"}


def table(p, base, col, bins, labels):
    bk = pd.cut(p[col], bins=bins, labels=labels, right=False)
    return pd.DataFrame([row(s, base, b) for b, s in p.groupby(bk, observed=True)]).to_string(index=False)


def main(argv):
    p = panel()
    base = {"boom": p["boom"].mean(), "era": [g["boom"].mean() for _, g in p.groupby("era", observed=False)]}
    out = []
    P = lambda s="": (print(s), out.append(s))  # noqa: E731
    P(f"樣本：{p['date'].min().date()} ~ {p['date'].max().date()}，每 {STEP} 個交易日取樣，20 日均成交 ≥ {MINLIQ/1e8:g} 億，共 {len(p):,} 筆")
    P(f"基準：之後 {FWD} 日內收盤曾漲 ≥{UP:.0%}（飆股）{base['boom']:.2%}｜曾跌 ≤{DN:.0%}（重摔）{p['bust'].mean():.2%}｜"
      f"{FWD} 日後平均 {p['fwd'].mean():+.1%}、中位 {p['fwd'].median():+.1%}、賺錢 {(p['fwd'] > 0).mean():.0%}")
    P("三段基準飆股機率：" + "　".join(f"{e} {g['boom'].mean():.2%}" for e, g in p.groupby("era", observed=False)))
    P("各年飆股機率：" + "　".join(f"{y}:{v:.1%}" for y, v in p.groupby(p["date"].dt.year)["boom"].mean().items()))
    P()
    inf = np.inf
    specs = [
        ("near", "離一年高點（收盤÷250日最高）", [0, 0.5, 0.7, 0.85, 0.95, 0.9999, inf], ["跌>50%", "跌30~50%", "跌15~30%", "跌5~15%", "跌<5%", "創新高"]),
        ("ret20", "前 20 日漲幅", [-inf, -0.15, -0.05, 0.05, 0.15, 0.3, inf], ["<-15%", "-15~-5%", "±5%", "5~15%", "15~30%", "≥30%"]),
        ("ret120", "前 120 日漲幅", [-inf, -0.3, 0, 0.3, 0.6, 1, inf], ["<-30%", "-30~0%", "0~30%", "30~60%", "60~100%", "≥100%"]),
        ("val20", "20 日均成交金額", [0, 1e8, 3e8, 1e9, 3e9, inf], ["0.3~1億", "1~3億", "3~10億", "10~30億", "≥30億"]),
        ("volat", "60 日波動度（年化）", [0, 0.25, 0.4, 0.55, 0.75, inf], ["<25%", "25~40%", "40~55%", "55~75%", "≥75%"]),
        ("lu20", "前 20 日漲停次數", [0, 1, 2, 4, inf], ["0", "1", "2~3", "≥4"]),
        ("bbw_pct", "布林寬度在自己一年內的排名（越小越收縮）", [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.01], ["最窄10%", "10~25%", "25~50%", "50~75%", "75~90%", "最寬10%"]),
        ("rng", "振幅收縮（近10日÷近60日）", [0, 0.6, 0.8, 1, 1.3, inf], ["<0.6", "0.6~0.8", "0.8~1", "1~1.3", "≥1.3"]),
        ("vdry", "量縮（近10日均量÷近60日）", [0, 0.5, 0.75, 1, 1.5, 2.5, inf], ["<0.5", "0.5~0.75", "0.75~1", "1~1.5", "1.5~2.5", "≥2.5"]),
        ("vx", "當天量÷前20日均量", [0, 0.5, 1, 2, 3, 5, inf], ["<0.5", "0.5~1", "1~2", "2~3", "3~5", "≥5"]),
        ("yoy", "已公布的最新單月營收年增 %", [-inf, -20, 0, 15, 30, 60, 100, inf], ["<-20", "-20~0", "0~15", "15~30", "30~60", "60~100", "≥100"]),
        ("mk60", "全市場（等權）前 60 日漲跌", [-inf, -0.15, -0.05, 0.05, 0.15, inf], ["<-15%", "-15~-5%", "±5%", "5~15%", "≥15%"]),
    ]
    for col, name, bins, labels in specs:
        P(f"=== {name} ===")
        P(table(p, base, col, bins, labels))
        P()
    # ---- 組合
    hasrev = p["yoy"].notna()
    up_tr = (p["ret120"] >= 0.3) & (p["near"] >= 0.85)
    sqz = (p["rng"] < 0.8) & (p["vdry"] < 0.75)
    tight = p["bbw_pct"] < 0.25
    brk = (p["hi60"] > 0) & (p["vx"] >= 2)
    combos = [
        ("全部（有營收資料的 2013 起）", hasrev),
        ("營收年增 ≥30%", p["yoy"] >= 30),
        ("營收年增加速（主力策略的訊號）", p["accel"] > 0),
        ("營收創 24 月新高＋年增 ≥30%", p["high"] > 0),
        ("離高點 <5%", p["near"] >= 0.95),
        ("營收加速＋離高點 <5%", (p["accel"] > 0) & (p["near"] >= 0.95)),
        ("營收加速＋離高點 >30%", (p["accel"] > 0) & (p["near"] < 0.7)),
        ("帶量突破（創60日新高＋量≥2倍）", brk),
        ("帶量突破＋之前布林最窄25%（看 5 天前）", None),      # 下面另外算
        ("收縮中（振幅<0.8、量縮<0.75）", sqz),
        ("VCP 候選：前120日漲≥30%、離高點<15%、收縮中", up_tr & sqz),
        ("VCP 候選＋營收年增 ≥30%", up_tr & sqz & (p["yoy"] >= 30)),
        ("布林最窄25%＋離高點<15%", tight & (p["near"] >= 0.85)),
        ("布林最窄25%＋離高點<15%＋營收年增≥30%", tight & (p["near"] >= 0.85) & (p["yoy"] >= 30)),
        ("帶量突破＋營收年增 ≥30%", brk & (p["yoy"] >= 30)),
        ("帶量突破＋營收加速", brk & (p["accel"] > 0)),
        ("帶量突破＋營收年增 <0", brk & (p["yoy"] < 0)),
        ("前20日漲停≥2次＋營收年增≥30%", (p["lu20"] >= 2) & (p["yoy"] >= 30)),
        ("前20日漲停≥2次＋營收年增<0", (p["lu20"] >= 2) & (p["yoy"] < 0)),
        ("大盤前60日跌>15%＋營收年增≥30%", (p["mk60"] < -0.15) & (p["yoy"] >= 30)),
    ]
    # 突破前的收縮：用 5 個交易日前的布林排名
    f = sq.feats()
    prev = f["bbw_pct"].shift(5)
    p["bbw_prev"] = [prev.at[d, c] for d, c in zip(p["date"], p["code"])]
    prng = f["rng"].shift(3)
    p["rng_prev"] = [prng.at[d, c] for d, c in zip(p["date"], p["code"])]
    rows = []
    for name, m in combos:
        if m is None:
            m = brk & (p["bbw_prev"] < 0.25)
        s = p[m]
        if len(s) >= 50:
            rows.append(row(s, base, name))
    for name, m in (("帶量突破＋突破前振幅收縮<0.8", brk & (p["rng_prev"] < 0.8)),
                    ("帶量突破＋突破前收縮＋營收年增≥30%", brk & (p["bbw_prev"] < 0.25) & (p["yoy"] >= 30)),
                    ("帶量突破＋突破前收縮＋離高點<5%", brk & (p["bbw_prev"] < 0.25) & (p["near"] >= 0.95))):
        s = p[m]
        if len(s) >= 50:
            rows.append(row(s, base, name))
    P("=== 組合 ===")
    P(pd.DataFrame(rows).to_string(index=False))
    P()
    # ---- 反過來看：飆股起漲前長什麼樣（占比）
    b = p[p["boom"] & hasrev]
    a = p[hasrev]
    P("=== 反過來看：2013 起的飆股，起漲前有這個特徵的比例（括號＝全部股票的比例） ===")
    for name, m in (("營收年增 ≥30%", a["yoy"] >= 30), ("營收年增 <0", a["yoy"] < 0), ("離高點 <15%", a["near"] >= 0.85),
                    ("離高點 >30%", a["near"] < 0.7), ("前120日已漲 ≥30%", a["ret120"] >= 0.3), ("前120日下跌", a["ret120"] < 0),
                    ("布林最窄25%", a["bbw_pct"] < 0.25), ("收縮中", (a["rng"] < 0.8) & (a["vdry"] < 0.75)),
                    ("成交 <3 億", a["val20"] < 3e8), ("波動度 ≥55%", a["volat"] >= 0.55), ("前20日有漲停", a["lu20"] >= 1)):
        P(f"  {name}：{m[b.index].mean():.0%}（{m.mean():.0%}）")
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / "multibagger2.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
