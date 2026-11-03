"""價值因子與「便宜＋強勢」回測（2026-11-03）

選股時點：每季財報期限（3/31、5/15、8/14、11/14）之後第一個交易日收盤買，用前一天的本益比／淨值比／殖利率排名。
每次買 N=20 檔，持有 H（3 個月、6 個月、1 年、2 年、3 年、5 年），也就是每季加一批、各批重疊；
資金平均分給目前持有的所有股票（一開始就滿手，不會因為持有期長而閒置）。
股票池：普通股（4 碼）、20 日均成交 ≥ 1 億、排除營建金融（另看不排除、≥ 2 千萬的版本）。
成本：手續費＋證交稅＋每邊滑價 0.3%。

因子
  低本益比   本益比 > 0（賺錢）裡最低的 20 檔
  低淨值比   股價淨值比 > 0 裡最低的
  高殖利率   殖利率最高的
  價值綜合   三個排名平均（本益比 > 0 才算）
  強勢       股價 ÷ 一年最高價 最高的（對照用）
  便宜＋強勢 A：價值綜合最便宜的 30% 裡，挑最強勢的 20 檔；B：價值綜合排名與強勢排名平均
對照：同一股票池隨機挑 20 檔（10 次取中位數）、股票池全部都買（等權）、加權指數（不含息）。

python -m research.value_factor
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import portfolio as pf
from research.robust_check import excl_mask, strength

SLIP = 0.003
N = 20
HOLDS = {"3個月": 1, "6個月": 2, "1年": 4, "2年": 8, "3年": 12, "5年": 20}     # 單位：季
OUT = Path(__file__).parent / "results" / "value_factor.json"


def anchors(days: pd.DatetimeIndex) -> list[int]:
    """每季財報期限後第一個交易日的索引（2006/4 起）"""
    out = []
    for y in range(2006, 2027):
        for md in ("03-31", "05-15", "08-14", "11-14"):
            i = days.searchsorted(pd.Timestamp(f"{y}-{md}"), side="right")
            if i < len(days) and days[i] >= pd.Timestamp("2006-04-01"):
                out.append(int(i))
    return sorted(set(out))


def load_val(dates) -> pd.DataFrame:
    fr = []
    for d in dates:
        p = bt.ARCHIVE / "val" / f"{d.year}" / f"{d.date()}.csv.gz"
        if not p.exists():
            continue
        v = pd.read_csv(p, dtype={"code": str})
        for c in ("pe", "pb", "dy"):
            v[c] = pd.to_numeric(v[c], errors="coerce")
        v["vdate"] = d
        fr.append(v)
    return pd.concat(fr, ignore_index=True)


def universe(minliq=1e8, excl=True):
    px, *_ = pf.prices()
    days = px.index
    near, liq = strength()                       # 都已是「前一天」的資料
    anc = anchors(days)
    prev = [days[i - 1] for i in anc]
    val = load_val(prev)
    rows = []
    for i, d0 in zip(anc, prev):
        d = days[i]
        v = val[val["vdate"] == d0].set_index("code")
        v = v[v.index.str.fullmatch(r"\d{4}", na=False)]
        lq = liq.loc[d].reindex(v.index) if d in liq.index else pd.Series(np.nan, index=v.index)
        nh = near.loc[d].reindex(v.index) if d in near.index else pd.Series(np.nan, index=v.index)
        ok = px.loc[d].reindex(v.index).notna()
        df = v.assign(liq=lq.values, near=nh.values, i=i, date=d)[ok.values]
        rows.append(df.reset_index())
    u = pd.concat(rows, ignore_index=True)
    u = u[u["liq"].fillna(0) >= minliq]
    if excl:
        u = u[~excl_mask(u)]
    return u, anc, days


def picks(u: pd.DataFrame, how: str, seed: int = 0) -> pd.DataFrame:
    out = []
    for d, g in u.groupby("date"):
        g = g.copy()
        pe_ok = g["pe"] > 0
        if how == "pe":
            s = g[pe_ok].nsmallest(N, "pe")
        elif how == "pb":
            s = g[g["pb"] > 0].nsmallest(N, "pb")
        elif how == "dy":
            s = g[g["dy"] > 0].nlargest(N, "dy")
        elif how in ("val", "cheap_strong", "blend"):
            h = g[pe_ok & (g["pb"] > 0) & g["dy"].notna()].copy()
            h["vs"] = (h["pe"].rank(pct=True) + h["pb"].rank(pct=True) + (-h["dy"]).rank(pct=True)) / 3     # 越小越便宜
            if how == "val":
                s = h.nsmallest(N, "vs")
            elif how == "cheap_strong":
                s = h[h["vs"] <= h["vs"].quantile(0.3)].nlargest(N, "near")
            else:
                h["bs"] = (h["vs"].rank(pct=True) + (-h["near"]).rank(pct=True)) / 2
                s = h.nsmallest(N, "bs")
        elif how == "near":
            s = g.nlargest(N, "near")
        elif how == "random":
            s = g.sample(min(N, len(g)), random_state=seed + int(d.value // 86400e9))
        elif how == "all":
            s = g
        out.append(s[["code", "date", "i"]])
    return pd.concat(out, ignore_index=True)


def run(ev: pd.DataFrame, anc: list[int], hq: int, start=None, end=None):
    pos = {a: k for k, a in enumerate(anc)}
    n_days = len(pf.prices()[0].index)
    hold = [(anc[pos[i] + hq] if pos[i] + hq < len(anc) else n_days - 1) - i for i in ev["i"]]
    e = ev.assign(hold=hold)[["code", "date", "hold"]]
    return pf.simulate(e, 60, None, start=start or "2006-04-01", end=end, slip=SLIP)


NAMES = {"pe": "低本益比", "pb": "低股價淨值比", "dy": "高殖利率", "val": "價值綜合（三個平均）", "near": "強勢（最接近一年高點）",
         "cheap_strong": "便宜＋強勢 A（便宜 30% 裡挑強勢）", "blend": "便宜＋強勢 B（兩個排名平均）",
         "random": "對照：股票池隨機 20 檔", "all": "對照：股票池全部（等權）"}


def main():
    res = {}
    for uni, (minliq, excl) in {"main": (1e8, True), "incl": (1e8, False), "small": (2e7, True)}.items():
        u, anc, days = universe(minliq, excl)
        print(f"\n######## 股票池：成交 ≥{minliq / 1e8:g} 億、{'排除' if excl else '包含'}營建金融；每季平均 {u.groupby('date').size().mean():.0f} 檔可選 ########")
        hows = list(NAMES) if uni == "main" else ["pe", "pb", "dy", "val", "cheap_strong", "random", "all"]
        for how in hows:
            line, rr = [], {}
            for hn, hq in HOLDS.items():
                if how == "random":
                    sims = [run(picks(u, how, s), anc, hq) for s in range(10)]
                    cg = float(np.median([x["curve"]["cagr"] for x in sims]))
                    md = float(np.median([x["curve"]["mdd"] for x in sims]))
                    a = b = None
                    r = {"cagr": cg, "mdd": md}
                else:
                    ev = picks(u, how)
                    x = run(ev, anc, hq)
                    a = run(ev, anc, hq, end="2015-12-31")["curve"]["cagr"]
                    b = run(ev, anc, hq, start="2016-01-01")["curve"]["cagr"]
                    r = {"cagr": x["curve"]["cagr"], "mdd": x["curve"]["mdd"], "early": a, "late": b,
                         "yearly": x["yearly"], "win": x["trade"]["win"], "tmean": x["trade"]["mean"]}
                    if hn == "1年":
                        tx = x["yearly_taiex"]
                rr[hn] = r
                line.append(f"{hn} {r['cagr']:+.1%}/{r['mdd']:+.0%}" + (f"(前{a:+.0%} 後{b:+.0%})" if a is not None else ""))
            res[f"{uni}:{how}"] = rr
            print(f"{NAMES[how]:<26} " + "｜".join(line), flush=True)
        if uni == "main":
            for how in ("val", "near", "cheap_strong"):
                y = res[f"main:{how}"]["1年"]["yearly"]
                print(f"   {NAMES[how]} 持有1年 每年：" + "  ".join(f"{k[2:]} {v:+.0%}" for k, v in y.items()))
            print("   加權指數 每年：" + "  ".join(f"{k[2:]} {v:+.0%}" for k, v in tx.items()))
            res["_taiex"] = tx
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
