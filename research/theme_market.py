"""族群動能，以及「大盤跌後」營收策略的表現（2026-11-03）

基準：營收年增加速＋挑最接近一年高點＋停損 20%（最多抱 60 日），成交 ≥1 億、排除營建金融、20 份、滑價 0.3%、2013/2 起。

一、大盤跌後：把基準實際做的每筆交易，依進場前一天的大盤狀況分組
   大盤＝加權指數；看前 20 日、前 60 日漲跌，離一年高點多遠，是否在年線下。
   報酬＝每筆扣成本後的絕對報酬，以及同期間加權指數漲跌（超額）。
   另測「只在大盤跌後才買」的資金曲線（其他時間空手）。
二、族群動能：族群用 themes.json（目前的分類，舊公司、已下市公司沒有族群；用現在的分類回頭套，略有偷看）
   同族群營收加速家數：同一個月有幾家同族群公司也是營收年增加速（不管成交量）
   族群創高比例：同族群股票裡，前一天收盤在一年高點 5% 以內的比例（族群至少 3 檔）
   變化：只買同族群 ≥2／≥3 家加速；只買族群創高比例 ≥30%／≥50%；排序優先同族群家數多的
   另測純族群策略（不看營收）：每月同一天挑創高比例最高的 5 個族群，各買最強 4 檔。

python -m research.theme_market
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import config
from research import exit_rules as er
from research import fin_signals as fs
from research import portfolio as pf
from research.robust_check import excl_mask, lookup, strength

START = er.START
OUT = Path(__file__).parent / "results" / "theme_market.json"


def themes() -> dict[str, str]:
    t = json.loads((config.ROOT / "themes.json").read_text())["themes"]
    return {c: k for k, v in t.items() for c in v.get("codes", [])}


def grp(df, col, bins, labels):
    df = df.assign(b=pd.cut(df[col], bins, labels=labels))
    rows = []
    for b, g in df.groupby("b", observed=True):
        rows.append({"組": str(b), "筆數": len(g), "每筆平均": g["ret"].mean(), "中位": g["ret"].median(), "賺錢": (g["ret"] > 0).mean(),
                     "同期大盤": g["mk"].mean(), "超額": (g["ret"] - g["mk"]).mean()})
    return rows


def prt(title, rows):
    print(f"\n{title}")
    for r in rows:
        print(f"  {r['組']:<14} {r['筆數']:>4} 筆｜每筆 {r['每筆平均']:+.1%}（中位 {r['中位']:+.1%}、賺錢 {r['賺錢']:.0%}）｜同期大盤 {r['同期大盤']:+.1%}｜超額 {r['超額']:+.1%}")


def main():
    near, liq = strength()
    r, rs = fs.revenue()
    X = er.Exits(r)
    e = er.events(near, liq, r, rs, 10)
    e = e.assign(hold=X.holds(e, er.stop(0.20, 60)))
    px, ret, tx, ew = pf.prices()
    days = px.index
    out = {}
    base = pf.simulate(e, 60, 20, start=START, slip=er.SLIP, skip_held=True)
    c0 = er.curve(base["_eq"])
    print(f"基準（停損 20%）：年化 {c0['cagr']:+.1%} 回落 {c0['mdd']:+.0%}（前 {c0['early']:+.1%}／後 {c0['late']:+.1%}）")

    # ---------- 一、大盤跌後 ----------
    t = base["_trades"].copy()
    txd = tx.reindex(days)
    i0 = days.get_indexer(t["date"])
    t["mk"] = txd.to_numpy()[np.minimum(i0 + t["days"].to_numpy(), len(days) - 1)] / txd.to_numpy()[i0] - 1
    prev = txd.shift(1)
    t["m20"] = (prev / txd.shift(21) - 1).to_numpy()[i0]
    t["m60"] = (prev / txd.shift(61) - 1).to_numpy()[i0]
    t["mdd1y"] = (prev / txd.rolling(250).max().shift(1) - 1).to_numpy()[i0]
    t["below"] = (prev < txd.rolling(240).mean().shift(1)).to_numpy()[i0]
    print(f"\n== 一、基準實際做的 {len(t)} 筆交易，依進場前大盤狀況分組 ==")
    out["by_m20"] = grp(t, "m20", [-1, -0.10, -0.05, 0, 0.05, 1], ["跌 >10%", "跌 5~10%", "跌 0~5%", "漲 0~5%", "漲 >5%"])
    prt("大盤前 20 日漲跌", out["by_m20"])
    out["by_m60"] = grp(t, "m60", [-1, -0.15, -0.05, 0, 0.10, 1], ["跌 >15%", "跌 5~15%", "跌 0~5%", "漲 0~10%", "漲 >10%"])
    prt("大盤前 60 日漲跌", out["by_m60"])
    out["by_dd"] = grp(t, "mdd1y", [-1, -0.20, -0.10, -0.05, 1], ["離高點 >20%", "10~20%", "5~10%", "<5%（接近高點）"])
    prt("大盤離一年高點多遠", out["by_dd"])
    out["by_below"] = grp(t.assign(bl=t["below"].astype(float)), "bl", [-0.5, 0.5, 1.5], ["年線上", "年線下"])
    prt("大盤在年線上／下", out["by_below"])

    print("\n只在大盤跌後才買（其他時間不開新倉，持有中的照規則）")
    m20 = (txd.shift(1) / txd.shift(21) - 1)
    dd = (txd.shift(1) / txd.rolling(250).max().shift(1) - 1)
    for lab, cond in (("前 20 日跌 >5%", m20 <= -0.05), ("前 20 日跌 >0%", m20 < 0), ("離一年高點 >10%", dd <= -0.10),
                      ("前 20 日漲（對照）", m20 >= 0)):
        ok = cond.reindex(e["date"]).fillna(False).astype(bool).to_numpy()
        res = pf.simulate(e[ok], 60, 20, start=START, slip=er.SLIP, skip_held=True)
        c = er.curve(res["_eq"])
        print(f"  {lab:<16} 年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}｜交易 {res['n_trades']} 每筆 {res['trade']['mean']:+.1%} 賺錢 {res['trade']['win']:.0%}｜持股 {res['invested']:.0%}")
        out[f"only:{lab}"] = {**c, "n": res["n_trades"], "trade": res["trade"], "invested": res["invested"]}
    # 大盤跌後加碼：平常 20 份，大盤前 20 日跌 >5% 時新進場的部位加倍（等於該批多買一倍，用 40 份的資金規模算）
    print("\n  大盤跌後加碼（平常只用 80% 資金；前 20 日跌 >5% 後進場的那幾批用滿）")
    hot = (m20 <= -0.05).reindex(e["date"]).fillna(False).astype(bool).to_numpy()
    res_all = base
    eq = base["_eq"]
    drv = eq.pct_change().fillna(0)
    w = pd.Series(0.8, index=days)
    entry_hot = pd.Series(hot, index=e.index).groupby(e["date"]).any()
    for d, h in entry_hot.items():
        if h and d in days:
            k = days.get_loc(d)
            w.iloc[k:k + 60] = 1.0
    eq2 = (1 + drv * w.shift(1).reindex(drv.index).fillna(0.8)).cumprod()
    c = er.curve(eq2)
    print(f"  平常 80%、大盤跌後 100%：年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（前 {c['early']:+.1%}／後 {c['late']:+.1%}）")
    eq3 = (1 + drv * 0.8).cumprod()
    c3 = er.curve(eq3)
    print(f"  對照：一直只用 80%：年化 {c3['cagr']:+.1%} 回落 {c3['mdd']:+.0%}")
    out["boost"], out["flat80"] = c, c3

    # ---------- 二、族群動能 ----------
    th = themes()
    print(f"\n== 二、族群動能（themes.json 共 {len(set(th.values()))} 個族群、{len(th)} 檔）==")
    acc = pf.events_at_next_close(r.loc[rs["rev_accel"].fillna(False), ["code", "deadline"]])
    acc["theme"] = acc["code"].map(th)
    n_acc = acc.dropna(subset=["theme"]).groupby(["date", "theme"]).size()
    tdf = pd.Series(th)
    hi = (near >= 0.95)
    breadth = {}
    for d in sorted(e["date"].unique()):
        row = hi.loc[d].reindex(tdf.index)
        okv = near.loc[d].reindex(tdf.index).notna()
        g = pd.DataFrame({"t": tdf.values, "hi": row.fillna(False).values, "ok": okv.values})
        g = g[g["ok"]]
        s = g.groupby("t").agg(n=("hi", "size"), h=("hi", "mean"))
        breadth[d] = s[s["n"] >= 3]["h"]
    e["theme"] = e["code"].map(th)
    e["n_acc"] = [n_acc.get((d, t_), 0) if isinstance(t_, str) else 0 for d, t_ in zip(e["date"], e["theme"])]
    e["br"] = [breadth[d].get(t_, np.nan) if isinstance(t_, str) else np.nan for d, t_ in zip(e["date"], e["theme"])]
    print(f"有族群資料的訊號 {e['theme'].notna().mean():.0%}；同族群 ≥2 家加速 {(e['n_acc'] >= 2).mean():.0%}、≥3 家 {(e['n_acc'] >= 3).mean():.0%}；族群創高 ≥30% {(e['br'] >= 0.3).mean():.0%}")
    cases = {
        "基準": e,
        "有族群資料的才買（偷看檢查）": e[e["theme"].notna()],
        "同族群 ≥2 家營收加速": e[e["n_acc"] >= 2],
        "同族群 ≥3 家營收加速": e[e["n_acc"] >= 3],
        "族群創高比例 ≥30%": e[e["br"] >= 0.3],
        "族群創高比例 ≥50%": e[e["br"] >= 0.5],
        "排序：同族群加速家數多的優先": e.assign(score=e["n_acc"].clip(upper=5) * 10 + e["score"]),
        "排序：族群創高比例高的優先": e.assign(score=e["br"].fillna(0) * 10 + e["score"]),
        "排除：族群創高比例 <10%": e[~(e["br"] < 0.1)],
    }
    for lab, x in cases.items():
        res = pf.simulate(x, 60, 20, start=START, slip=er.SLIP, skip_held=True)
        c = er.curve(res["_eq"])
        print(f"  {lab:<22} 年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（前 {c['early']:+.1%}／後 {c['late']:+.1%}）｜交易 {res['n_trades']} 每筆 {res['trade']['mean']:+.1%} 賺錢 {res['trade']['win']:.0%}｜持股 {res['invested']:.0%}", flush=True)
        out[f"theme:{lab}"] = {**c, "n": res["n_trades"], "trade": res["trade"], "invested": res["invested"]}

    # 純族群策略（不看營收）
    print("\n  純族群動能（不看營收）：每月營收期限後同一天，挑創高比例最高的 5 個族群，各買最強 4 檔")
    rows = []
    for d, br in breadth.items():
        top = br.sort_values(ascending=False).head(5).index
        cand = pd.DataFrame({"code": tdf.index, "t": tdf.values})
        cand = cand[cand["t"].isin(top)].copy()
        cand["date"] = d
        cand["score"] = near.loc[d].reindex(cand["code"]).values
        cand["liq"] = liq.loc[d].reindex(cand["code"]).values
        cand = cand[cand["liq"].fillna(0) >= 1e8]
        rows.append(cand.sort_values("score", ascending=False).groupby("t").head(4))
    pe = pd.concat(rows)
    pe = pe[~excl_mask(pe)][["code", "date", "score"]]
    for lab, hh in (("持有 60 日", None), ("停損 20%（最多 60 日）", er.stop(0.20, 60))):
        x = pe if hh is None else pe.assign(hold=X.holds(pe, hh))
        res = pf.simulate(x, 60, 20, start=START, slip=er.SLIP, skip_held=True)
        c = er.curve(res["_eq"])
        print(f"  純族群 {lab:<18} 年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（前 {c['early']:+.1%}／後 {c['late']:+.1%}）｜持股 {res['invested']:.0%}")
        out[f"pure_theme:{lab}"] = c
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
