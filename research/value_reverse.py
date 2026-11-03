"""價值因子反過來測（2026-11-03，只做研究、不放進網站回測頁）

和 research/value_factor.py 同一套做法（每季財報期限後買 20 檔，持有 3 個月～5 年，各批重疊、資金平均分；扣成本＋滑價 0.3%），
只是把排序反過來：
  高本益比     本益比 > 0 裡最高的（賺錢但很貴）
  高淨值比     淨值比最高的
  低殖利率     殖利率最低的（含不配息的 0）
  價值綜合最貴 三個排名平均最貴的
  弱勢         離一年高點最遠的（跌最深）
  貴＋弱       最貴 30% 裡挑最弱的（便宜＋強勢的完全相反）
  貴＋強       最貴 30% 裡挑最強的
  便宜＋弱     最便宜 30% 裡挑最弱的（「撿便宜、逢低承接」）
python -m research.value_reverse     結果存 research/results/value_reverse.json
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research import value_factor as vf

OUT = vf.OUT.parent / "value_reverse.json"
NAMES = {"pe_hi": "高本益比", "pb_hi": "高淨值比", "dy_lo": "低殖利率", "val_hi": "價值綜合最貴", "weak": "弱勢（離一年高點最遠）",
         "exp_weak": "貴＋弱（最貴 30% 挑最弱）", "exp_strong": "貴＋強（最貴 30% 挑最強）", "cheap_weak": "便宜＋弱（最便宜 30% 挑最弱）",
         "val": "（對照）價值綜合最便宜", "cheap_strong": "（對照）便宜＋強勢", "random": "（對照）股票池隨機 20 檔"}


def picks(u: pd.DataFrame, how: str, seed: int = 0) -> pd.DataFrame:
    if how in ("val", "cheap_strong", "random"):
        return vf.picks(u, how, seed)
    N = vf.N
    out = []
    for d, g in u.groupby("date"):
        if how == "pe_hi":
            s = g[g["pe"] > 0].nlargest(N, "pe")
        elif how == "pb_hi":
            s = g[g["pb"] > 0].nlargest(N, "pb")
        elif how == "dy_lo":
            s = g[g["dy"].notna()].nsmallest(N, "dy")
        elif how == "weak":
            s = g[g["near"].notna()].nsmallest(N, "near")
        else:
            h = g[(g["pe"] > 0) & (g["pb"] > 0) & g["dy"].notna()].copy()
            h["vs"] = (h["pe"].rank(pct=True) + h["pb"].rank(pct=True) + (-h["dy"]).rank(pct=True)) / 3
            if how == "val_hi":
                s = h.nlargest(N, "vs")
            elif how == "exp_weak":
                s = h[h["vs"] >= h["vs"].quantile(0.7)].nsmallest(N, "near")
            elif how == "exp_strong":
                s = h[h["vs"] >= h["vs"].quantile(0.7)].nlargest(N, "near")
            else:   # cheap_weak
                s = h[h["vs"] <= h["vs"].quantile(0.3)].nsmallest(N, "near")
        out.append(s[["code", "date", "i"]])
    return pd.concat(out, ignore_index=True)


def main():
    res = {}
    for uni, minliq in (("≥1億", 1e8), ("≥2千萬", 2e7)):
        u, anc, days = vf.universe(minliq, True)
        print(f"\n######## 股票池：成交 {uni}、排除營建金融（2006/4 起；前段 2006~15、後段 2016~26；加權不含息 +9.7%） ########")
        for how in NAMES:
            line, rr = [], {}
            for hn, hq in vf.HOLDS.items():
                if how == "random":
                    sims = [vf.run(picks(u, how, s), anc, hq) for s in range(10)]
                    r = {"cagr": float(np.median([x["curve"]["cagr"] for x in sims])), "mdd": float(np.median([x["curve"]["mdd"] for x in sims]))}
                    line.append(f"{hn} {r['cagr']:+.1%}/{r['mdd']:+.0%}")
                else:
                    ev = picks(u, how)
                    x = vf.run(ev, anc, hq)
                    a = vf.run(ev, anc, hq, end="2015-12-31")["curve"]["cagr"]
                    b = vf.run(ev, anc, hq, start="2016-01-01")["curve"]["cagr"]
                    r = {"cagr": x["curve"]["cagr"], "mdd": x["curve"]["mdd"], "early": a, "late": b, "yearly": x["yearly"]}
                    line.append(f"{hn} {r['cagr']:+.1%}/{r['mdd']:+.0%}(前{a:+.0%} 後{b:+.0%})")
                rr[hn] = r
            res[f"{uni}:{how}"] = rr
            print(f"{NAMES[how]:<22} " + "｜".join(line), flush=True)
        for how in ("weak", "exp_weak", "cheap_weak"):
            y = res[f"{uni}:{how}"]["1年"]["yearly"]
            print(f"   {NAMES[how]} 持有1年 每年：" + "  ".join(f"{k[2:]} {v:+.0%}" for k, v in y.items()))
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
