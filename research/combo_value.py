"""營收年增加速 × 便宜＋強勢：能不能互補？（2026-11-03）

一、營收策略加上「便宜」條件（每月營收期限後進場、20 份、持有 60／120 日）
   a 原本：營收年增加速＋挑最接近一年高點
   b 再要求便宜一半（價值綜合排名在股票池前 50%）
   c 再要求便宜 30%
   d 排序改成「便宜排名＋強勢排名」平均
   e 只排除最貴的 20%
   f 只要求賺錢（本益比 > 0）
二、便宜＋強勢（每季）加上營收條件（持有 3／6／12 個月）
   g 原本：便宜 30% 裡挑最強勢
   h 再要求最新一個月營收年增 > 0
   i 再要求近 3 個月內出現過「營收年增加速」
三、兩個策略各放一半資金（每天各自照自己的規則跑，合併算）
價值綜合＝本益比、淨值比、殖利率三個排名平均（本益比 ≤ 0、資料不全的不算便宜）。
股票池：成交 ≥1 億（另看 ≥2 千萬）、排除營建金融；扣成本＋滑價 0.3%；2013/2 起（營收資料起點）。

python -m research.combo_value
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research import fin_signals as fs
from research import portfolio as pf
from research import value_factor as vf
from research.robust_check import excl_mask, lookup, strength

SLIP = 0.003
START = "2013-02-01"
OUT = Path(__file__).parent / "results" / "combo_value.json"


def value_rank(dates, near, liq, minliq):
    """每個進場日（前一天資料）：股票池內的價值綜合百分位 vs（越小越便宜）"""
    px, *_ = pf.prices()
    days = px.index
    prev = {d: days[days.get_loc(d) - 1] for d in dates}
    val = vf.load_val(sorted(set(prev.values())))
    out = []
    for d in dates:
        v = val[val["vdate"] == prev[d]].copy()
        v = v[v["code"].str.fullmatch(r"\d{4}", na=False)]
        v["liq"] = liq.loc[d].reindex(v["code"]).values
        v = v[v["liq"].fillna(0) >= minliq]
        v = v[~excl_mask(v)]
        ok = (v["pe"] > 0) & (v["pb"] > 0) & v["dy"].notna()
        h = v[ok].copy()
        h["vs"] = (h["pe"].rank(pct=True) + h["pb"].rank(pct=True) + (-h["dy"]).rank(pct=True)) / 3
        h["vs"] = h["vs"].rank(pct=True)
        h["date"] = d
        out.append(h[["code", "date", "vs", "pe"]])
        # 沒有價值資料（虧損等）的也要留著，vs 空白
        miss = v[~ok][["code", "pe"]].assign(date=d, vs=np.nan)
        out.append(miss[["code", "date", "vs", "pe"]])
    return pd.concat(out, ignore_index=True)


def fmt_res(res, lab, start=START):
    return pf.fmt(res, lab)


def seg(eq: pd.Series, a, b):
    s = eq[(eq.index >= a) & (eq.index <= b)]
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return float((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1)


def curve(eq):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return {"cagr": float(eq.iloc[-1] ** (1 / yrs) - 1), "mdd": float((eq / eq.cummax() - 1).min()),
            "early": seg(eq, "2013-01-01", "2019-12-31"), "late": seg(eq, "2020-01-01", "2030-01-01")}


def show(lab, res):
    c = curve(res["_eq"])
    t = res["trade"]
    print(f"{lab:<40} 年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（前 {c['early']:+.1%}／後 {c['late']:+.1%}）"
          f"｜交易 {res['n_trades']} 次 每筆平均 {t['mean']:+.1%} 賺錢 {t['win']:.0%}｜持股 {res['invested']:.0%}", flush=True)
    return {"label": lab, **c, "n": res["n_trades"], "invested": res["invested"], "yearly": res["yearly"]}


def main():
    near, liq = strength()
    r, rs = fs.revenue()
    out = {}
    for minliq, ulab in ((1e8, "≥1億"), (2e7, "≥2千萬")):
        print(f"\n################ 股票池：成交 {ulab}、排除營建金融 ################")
        # ---- 一、營收策略＋便宜 ----
        e0 = pf.events_at_next_close(r.loc[rs["rev_accel"].fillna(False), ["code", "deadline"]])
        e0 = e0[e0["date"] >= START].copy()
        e0["near"], e0["liq"] = lookup(near, e0), lookup(liq, e0)
        e0 = e0[(e0["liq"].fillna(0) >= minliq)]
        e0 = e0[~excl_mask(e0)]
        vr = value_rank(sorted(e0["date"].unique()), near, liq, minliq)
        e0 = e0.merge(vr, on=["code", "date"], how="left")
        e0["near"] = e0["near"].fillna(-1)
        e0["vs_r"] = e0.groupby("date")["vs"].rank(pct=True)
        e0["nr"] = e0.groupby("date")["near"].rank(pct=True, ascending=False)
        cases = {
            "a 營收加速＋挑強勢（原本）": e0.assign(score=e0["near"]),
            "b ＋便宜一半（價值前 50%）": e0[e0["vs"] <= 0.5].assign(score=lambda x: x["near"]),
            "c ＋便宜 30%": e0[e0["vs"] <= 0.3].assign(score=lambda x: x["near"]),
            "d 排序＝便宜＋強勢排名平均": e0.assign(score=-(e0["vs_r"].fillna(1) + e0["nr"]) / 2),
            "e 只排除最貴 20%": e0[e0["vs"].fillna(0) <= 0.8].assign(score=lambda x: x["near"]),
            "f 只要求賺錢（本益比 > 0）": e0[e0["pe"] > 0].assign(score=lambda x: x["near"]),
        }
        print(f"營收加速訊號 {len(e0)} 次；其中價值排名在前 50% 的 {(e0['vs'] <= 0.5).mean():.0%}、前 30% 的 {(e0['vs'] <= 0.3).mean():.0%}、虧損或資料不全 {e0['vs'].isna().mean():.0%}")
        rev_eq = None
        for lab, e in cases.items():
            for hold in (60, 120):
                res = pf.simulate(e[["code", "date", "score"]], hold, 20, start=START, slip=SLIP)
                out[f"{ulab}|{lab}|{hold}"] = show(f"{lab} 持有{hold}日", res)
                if lab.startswith("a") and hold == 60:
                    rev_eq = res["_eq"]
        # ---- 二、便宜＋強勢＋營收條件 ----
        u, anc, days = vf.universe(minliq, True)
        u = u[u["date"] >= START]
        anc = [i for i in anc if days[i] >= pd.Timestamp(START)]
        # 每個季進場日：最新已過期限的營收月份、近 3 個月是否出現營收加速
        rr = r[["code", "deadline", "yoy"]].assign(acc=rs["rev_accel"].fillna(False).values)
        rr = rr.sort_values("deadline")
        info = []
        for d in sorted(u["date"].unique()):
            known = rr[rr["deadline"] < d]
            last_dl = known["deadline"].max()
            lm = known[known["deadline"] == last_dl].set_index("code")["yoy"]
            acc3 = set(known[(known["deadline"] > last_dl - pd.Timedelta(days=80)) & known["acc"]]["code"])
            info.append(pd.DataFrame({"code": lm.index, "date": d, "ryoy": lm.values}).assign(acc3=lambda x: x["code"].isin(acc3)))
        info = pd.concat(info)
        u2 = u.merge(info, on=["code", "date"], how="left")
        variants = {"g 便宜＋強勢（原本）": u2, "h ＋最新月營收年增 > 0": u2[u2["ryoy"] > 0],
                    "i ＋近 3 個月出現營收加速": u2[u2["acc3"].fillna(False)]}
        cs_eq = None
        for lab, uu in variants.items():
            ev = vf.picks(uu, "cheap_strong") if not lab.startswith("i") else None
            if lab.startswith("i"):   # 符合的公司少：直接在符合的裡挑強勢（不要求便宜 30%，另列要求便宜一半）
                for sub, cond in (("（不限便宜）", None), ("（＋便宜一半）", 0.5)):
                    h = uu.copy()
                    okv = (h["pe"] > 0) & (h["pb"] > 0) & h["dy"].notna()
                    vv = []
                    for d, g in u2.groupby("date"):
                        gg = g[(g["pe"] > 0) & (g["pb"] > 0) & g["dy"].notna()].copy()
                        gg["vs"] = ((gg["pe"].rank(pct=True) + gg["pb"].rank(pct=True) + (-gg["dy"]).rank(pct=True)) / 3).rank(pct=True)
                        vv.append(gg[["code", "date", "vs"]])
                    h = h.merge(pd.concat(vv), on=["code", "date"], how="left")
                    if cond:
                        h = h[h["vs"] <= cond]
                    ev = pd.concat([g.nlargest(vf.N, "near")[["code", "date", "i"]] for _, g in h.groupby("date")])
                    for hn, hq in (("3個月", 1), ("6個月", 2), ("1年", 4)):
                        res = vf.run(ev, anc, hq, start=START)
                        out[f"{ulab}|{lab}{sub}|{hn}"] = show(f"{lab}{sub} 持有{hn}", res)
                    del okv
                continue
            for hn, hq in (("3個月", 1), ("6個月", 2), ("1年", 4)):
                res = vf.run(ev, anc, hq, start=START)
                out[f"{ulab}|{lab}|{hn}"] = show(f"{lab} 持有{hn}", res)
                if lab.startswith("g") and hn == "6個月":
                    cs_eq = res["_eq"]
        # ---- 三、各放一半資金 ----
        both = pd.concat([rev_eq.pct_change(), cs_eq.pct_change()], axis=1).dropna()
        mix = (1 + both.mean(axis=1)).cumprod()
        corr = both.corr().iloc[0, 1]
        c = curve(mix)
        print(f"三 各一半（營收加速＋強勢 60日 ／ 便宜＋強勢 6個月）：年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（前 {c['early']:+.1%}／後 {c['late']:+.1%}）｜每日報酬相關係數 {corr:.2f}")
        ra, rb = curve(rev_eq[rev_eq.index >= both.index[0]]), curve(cs_eq[cs_eq.index >= both.index[0]])
        print(f"   單獨：營收 {ra['cagr']:+.1%}/{ra['mdd']:+.0%}、便宜＋強勢 {rb['cagr']:+.1%}/{rb['mdd']:+.0%}")
        yy = mix.groupby(mix.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
        print("   各一半 每年：" + "  ".join(f"{y % 100:02d} {v:+.0%}" for y, v in yy.items()))
        out[f"{ulab}|mix"] = {**c, "corr": float(corr), "rev": ra, "cs": rb, "yearly": {str(k): float(v) for k, v in yy.items()}}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
