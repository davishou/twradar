"""PSG／PEG：營收（獲利）成長了、股價還沒反應的股票有沒有超額報酬？（2026-11-26）

python -m research.psg_bt <btdata 資料夾>      （資料夾裡要有 shares_YYYY.csv：tools/backfill_bt.py shares）

定義（每個月營收公布期限＝次月 10 日之後第一個交易日收盤進場，用前一天的收盤）：
  市值      ＝ 前一天收盤（實際股價）× 發行股數（最近一次月初快照）
  近 12 月營收 ＝ 最近 12 個月營收加總；去年同期＝同 12 個月的去年營收加總
  PS        ＝ 市值 ÷ 近 12 月營收（股價營收比，越低越便宜）
  營收成長   g12＝近 12 月營收年增；g3＝近 3 月營收年增；g1＝單月年增
  PSG       ＝ PS ÷ (成長率 × 100)，只算成長 >0 的（例：PS 2、成長 40% → 0.05）
  PEG       ＝ 本益比 ÷ (近四季 EPS 年增率 × 100)，只算本益比 >0、EPS 成長 >0 的；EPS 用財報公布期限後才算知道
  「股價還沒反應」＝前 120 日漲幅（ret120）低／離一年高點遠
營收資料 2013 起 → PSG 從 2014 起、PEG 從 2015 起。共同：前一天 20 日均成交 ≥1 億、排除營建金融、普通股。
報酬：進場日收盤 → 20／60 個交易日後收盤（還原），贏全市場＝減同期全市場等權。
資金曲線：20 份、持有 60 日、每邊滑價 0.3%、手續費 FEE_DISC；同一檔在手上不重複買。
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import exit_rules as ex
from research import fin_signals as fs
from research import portfolio as pf
from research.robust_check import excl_mask, lookup

ERAS = (("14~19", "2014", "2019-12-31"), ("20~26", "2020", "2030"))


def shares_mat(folder, index, columns):
    s = pd.concat([pd.read_csv(p, dtype={"code": str}) for p in sorted(glob.glob(f"{folder}/shares_*.csv"))], ignore_index=True)
    s["date"] = pd.to_datetime(s["date"])
    s["shares"] = pd.to_numeric(s["shares"], errors="coerce")
    m = s.pivot_table(index="date", columns="code", values="shares", aggfunc="last")
    return m.reindex(index=index.union(m.index)).ffill(limit=80).reindex(index=index, columns=columns)


def monthly_table(folder):
    px, r, tx, ew = pf.prices()
    q = bt.load_quotes()[["date", "code", "close", "value"]]
    raw = q.pivot(index="date", columns="code", values="close").reindex(index=px.index, columns=px.columns)
    liq = q.pivot(index="date", columns="code", values="value").reindex(index=px.index, columns=px.columns).rolling(20, min_periods=15).mean()
    sh = shares_mat(folder, px.index, px.columns)
    mcap = (raw * sh).shift(1)
    near = (px / px.rolling(250, min_periods=200).max()).shift(1)
    ret120 = (px / px.shift(120) - 1).shift(1)
    ret20 = (px / px.shift(20) - 1).shift(1)
    rv, rs = fs.revenue()
    rv = rv.sort_values(["code", "ym"]).copy()
    rv["accel"] = rs["rev_accel"].reindex(rv.index).fillna(False)
    g = rv.groupby("code")
    # 連續 12 個月才算（ym 差 11 個月）
    rv["mi"] = rv["ym"].dt.year * 12 + rv["ym"].dt.month
    ok12 = g["mi"].diff(11) == 11
    rv["r12"] = g["rev"].transform(lambda s: s.rolling(12).sum()).where(ok12)
    rv["r12_ly"] = g["rev_ly"].transform(lambda s: s.rolling(12).sum()).where(ok12)
    rv["g12"] = rv["r12"] / rv["r12_ly"] - 1
    rv["g3"] = rv["yoy3"]
    rv["g1"] = rv["yoy"] / 100
    rv["deadline"] = (rv["ym"] + 1).dt.to_timestamp() + pd.Timedelta(days=9)
    e = pf.events_at_next_close(rv[["code", "ym", "deadline", "r12", "g12", "g3", "g1", "accel", "yoy", "yoy_1", "yoy_2"]])
    e = e[e["date"] >= "2014-01-01"].copy()
    for nm, m in (("mcap", mcap), ("liq", liq.shift(1)), ("near", near), ("ret120", ret120), ("ret20", ret20)):
        e[nm] = lookup(m, e)
    e = e[(e["liq"] >= 1e8)]
    e = e[~excl_mask(e)].copy()
    e["ps"] = e["mcap"] / (e["r12"] * 1000)
    for k in ("g12", "g3", "g1"):
        e[f"psg_{k}"] = np.where(e[k] > 0, e["ps"] / (e[k] * 100), np.nan)
    # ---- PEG：本益比（交易所每日）÷ 近四季 EPS 年增
    val = fs._read("val")
    val["date"] = pd.to_datetime(val["period"])
    pe = val.pivot_table(index="date", columns="code", values="pe", aggfunc="last").apply(pd.to_numeric, errors="coerce")
    pe = pe.reindex(index=px.index.union(pe.index)).ffill(limit=5).reindex(index=px.index).shift(1)
    e["pe"] = lookup(pe, e)
    f, _ = fs.fin()
    f = f.sort_values(["code", "y", "q"]).copy()
    prev = f.groupby(["code", "y"])["eps"].shift(1)
    f["eps_q"] = np.where(f["q"] == 1, f["eps"], f["eps"] - prev)
    f["t"] = f["y"] * 4 + f["q"]
    gf = f.groupby("code")
    ok4 = gf["t"].diff(3) == 3
    f["ttm"] = gf["eps_q"].transform(lambda s: s.rolling(4).sum()).where(ok4)
    ok8 = gf["t"].diff(4) == 4
    f["ttm_ly"] = gf["ttm"].shift(4).where(ok8)
    f["eg"] = np.where((f["ttm"] > 0) & (f["ttm_ly"] > 0), f["ttm"] / f["ttm_ly"] - 1, np.nan)
    fe = pf.events_at_next_close(f[["code", "deadline", "eg"]].dropna())
    egm = fe.pivot_table(index="date", columns="code", values="eg", aggfunc="last").reindex(index=px.index).ffill(limit=140)
    e["eg"] = lookup(egm, e)
    e["peg"] = np.where((e["pe"] > 0) & (e["eg"] > 0), e["pe"] / (e["eg"] * 100), np.nan)
    # ---- 之後的報酬
    pfw = px.ffill(limit=60)
    a, w = pfw.to_numpy(), ew.to_numpy()
    col = {c: k for k, c in enumerate(px.columns)}
    di = {d: k for k, d in enumerate(px.index)}
    n = len(px.index)
    for h in (20, 60):
        rr, xx = [], []
        for d, c in zip(e["date"], e["code"]):
            i, j = di[d], col.get(c)
            if j is None or i + h >= n or not np.isfinite(a[i, j]):
                rr.append(np.nan), xx.append(np.nan)
                continue
            v = a[i + h, j] / a[i, j] - 1
            rr.append(v), xx.append(v - (w[i + h] / w[i] - 1))
        e[f"r{h}"], e[f"x{h}"] = rr, xx
    return e.reset_index(drop=True)


def grp_line(s, name):
    x, r = s["x60"].dropna(), s["r60"].dropna()
    if len(x) < 30:
        return f"  {name:<26} n={len(x)}"
    t = x.mean() / (x.std() / np.sqrt(len(x) / 3))                    # 每月一批、持有 60 日 → 重疊約 3 倍
    eras = "／".join(f"{s[(s['date'] >= a) & (s['date'] <= b)]['x60'].mean():+.1%}" for _, a, b in ERAS)
    return (f"  {name:<26} n={len(x):>6,} 60日平均 {r.mean():+5.1%} 中位 {r.median():+5.1%} 贏全市場 {x.mean():+5.1%}（t={t:4.1f}；14~19／20~26 {eras}）"
            f" 贏的比例 {(x > 0).mean():.0%}｜20日贏 {s['x20'].mean():+.1%}")


def quint(e, col, P, title, n=5, asc_label=("最低", "最高")):
    s = e.dropna(subset=[col, "x60"]).copy()
    s["q"] = s.groupby("date")[col].rank(pct=True)
    s["b"] = np.minimum((s["q"] * n).astype(int), n - 1)
    P(f"\n--- {title}（每個月把符合的股票依 {col} 分 {n} 組；第 1 組＝{asc_label[0]}） ---")
    for b, g in s.groupby("b"):
        P(grp_line(g, f"第 {b + 1} 組（{g[col].median():.3g}）"))


def sim(e, score, label, P, start="2014-02-01"):
    x = e.dropna(subset=["score"]) if score is None else e.assign(score=score).dropna(subset=["score"])
    x = x[x["date"] >= start]
    if len(x) < 50:
        P(f"  {label:<44} 訊號 {len(x)}（太少）")
        return None
    res = pf.simulate(x[["code", "date", "score"]], 60, 20, start=start, slip=0.003, skip_held=True)
    eq = res["_eq"]

    def seg(a, b):
        s = eq[(eq.index >= a) & (eq.index <= b)]
        y = (s.index[-1] - s.index[0]).days / 365.25
        return float((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1)
    t = res["trade"]
    P(f"  {label:<44} 年化 {res['curve']['cagr']:+6.1%} 回落 {res['curve']['mdd']:+.0%}（14~19 {seg('2014', '2019-12-31'):+.0%}／20~26 {seg('2020', '2030'):+.0%}）"
      f"｜交易 {res['n_trades']} 每筆 {t['mean']:+.1%} 中位 {t['med']:+.1%} 賺錢 {t['win']:.0%} 持股 {res['invested']:.0%}")
    return res


def main(argv):
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    e = monthly_table(argv[0])
    P(f"樣本：{e['date'].min().date()} ~ {e['date'].max().date()}，每月營收公布後的股票×月 {len(e):,} 筆（成交 ≥1 億、排除營建金融）；"
      f"有市值 {e['mcap'].notna().mean():.0%}、有 PSG(g12) {e['psg_g12'].notna().mean():.0%}、有 PEG {e['peg'].notna().mean():.0%}")
    P(f"全部：{grp_line(e, '全部').strip()}")
    P("中位數：PS {:.2f}、近 12 月營收年增 {:.0%}、PSG(g12) {:.3f}、本益比 {:.1f}、PEG {:.2f}".format(
        e['ps'].median(), e['g12'].median(), e['psg_g12'].median(), e['pe'].median(), e['peg'].median()))
    P("\n===== 一、單一指標分組（全部成交 ≥1 億的股票） =====")
    quint(e, "ps", P, "PS 股價營收比")
    quint(e, "g12", P, "近 12 月營收年增", asc_label=("成長最低", "最高"))
    quint(e, "g3", P, "近 3 月營收年增", asc_label=("成長最低", "最高"))
    quint(e, "psg_g12", P, "PSG（PS ÷ 近 12 月營收成長）")
    quint(e, "psg_g3", P, "PSG（PS ÷ 近 3 月營收成長）")
    quint(e, "pe", P, "本益比（>0）")
    quint(e[e["pe"] > 0], "peg", P, "PEG（本益比 ÷ EPS 成長）")
    P("\n--- 常見門檻 ---")
    for name, m in (("PSG(g12) < 0.05", e["psg_g12"] < 0.05), ("PSG(g12) < 0.1", e["psg_g12"] < 0.1), ("PSG(g3) < 0.05", e["psg_g3"] < 0.05),
                    ("PEG < 0.5", e["peg"] < 0.5), ("PEG < 1", e["peg"] < 1), ("PEG 1~2", (e["peg"] >= 1) & (e["peg"] < 2)), ("PEG ≥ 2", e["peg"] >= 2),
                    ("PS < 1", e["ps"] < 1), ("PS > 5", e["ps"] > 5)):
        P(grp_line(e[m], name))

    P("\n===== 二、營收先反應、股價還沒反應？（近 3 月營收年增 ≥30% 的股票） =====")
    hg = e[e["g3"] >= 0.3]
    P(grp_line(hg, "全部（近 3 月營收年增 ≥30%）"))
    quint(hg, "ret120", P, "依『前 120 日漲幅』分組（股價反應了多少）", asc_label=("漲最少", "漲最多"))
    quint(hg, "near", P, "依『離一年高點』分組", asc_label=("離高點最遠", "最近"))
    quint(hg, "ps", P, "依 PS 分組（同樣高成長，誰比較便宜）")
    quint(hg, "psg_g3", P, "依 PSG 分組")
    P("\n--- 典型的『還沒反應』條件 ---")
    for name, m in (("前 120 日漲幅 ≤0", hg["ret120"] <= 0), ("前 120 日漲幅 ≤10% 且離高點 >20%", (hg["ret120"] <= 0.1) & (hg["near"] < 0.8)),
                    ("PSG 最低 20% 且前 120 日 ≤10%", (hg["psg_g3"] <= hg.groupby("date")["psg_g3"].transform(lambda s: s.quantile(0.2))) & (hg["ret120"] <= 0.1)),
                    ("前 120 日漲幅 ≥50%（已反應，對照）", hg["ret120"] >= 0.5), ("離高點 <5%（已反應，對照）", hg["near"] >= 0.95)):
        P(grp_line(hg[m], name))
    acc = e[e["accel"]]
    P(grp_line(acc, "營收加速（主力策略訊號）"))
    quint(acc, "psg_g3", P, "營收加速裡依 PSG 分組")
    quint(acc, "near", P, "營收加速裡依離一年高點分組（主力策略用的排序）", asc_label=("離高點最遠", "最近"))

    P("\n===== 三、資金曲線（2014/2 起；20 份、持有 60 日、滑價 0.3%；分數高的先買） =====")
    P(f"手續費折數 {pf.FEE_DISC:g}")
    rk = lambda s: e.groupby("date")[s].rank(pct=True)  # noqa: E731
    A = e["accel"]
    sim(e[A], e.loc[A, "near"], "營收加速＋挑最接近一年高點（主力策略）", P)
    sim(e[A], -e.loc[A, "psg_g3"], "營收加速＋挑 PSG 最低", P)
    sim(e[A], -e.loc[A, "ps"], "營收加速＋挑 PS 最低", P)
    sim(e[A], -e.loc[A, "near"], "營收加速＋挑離高點最遠（還沒反應）", P)
    sim(e[A], (rk("near") - rk("psg_g3"))[A], "營收加速＋近高點與低 PSG 各半", P)
    m = A & (e["ret120"] <= 0.1)
    sim(e[m], -e.loc[m, "psg_g3"], "營收加速＋前 120 日 ≤10%＋挑 PSG 最低", P)
    m = (e["g3"] >= 0.3) & (e["ret120"] <= 0.1)
    sim(e[m], -e.loc[m, "psg_g3"], "近 3 月營收 ≥30%＋前 120 日 ≤10%＋PSG 最低", P)
    m = e["g3"] >= 0.2
    sim(e[m], -e.loc[m, "psg_g3"], "近 3 月營收 ≥20%、每月買 PSG 最低", P)
    m = e["g12"] >= 0.2
    sim(e[m], -e.loc[m, "psg_g12"], "近 12 月營收 ≥20%、每月買 PSG(g12) 最低", P)
    m = (e["g3"] >= 0.2)
    sim(e[m], e.loc[m, "near"] - 0 * e.loc[m, "psg_g3"], "近 3 月營收 ≥20%、挑最接近高點（對照）", P)
    m = e["peg"].notna()
    sim(e[m], -e.loc[m, "peg"], "每月買 PEG 最低（PEG>0）", P, start="2015-06-01")
    m = (e["peg"] < 1) & (e["g3"] > 0)
    sim(e[m], e.loc[m, "near"], "PEG <1＋營收成長＋挑最接近高點", P, start="2015-06-01")
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / "psg_bt.txt").write_text("\n".join(out))
    e.to_pickle(pf.OUT / "psg_table.pkl")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
