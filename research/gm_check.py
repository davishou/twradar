"""毛利率提高的各種策略：用 2026-11-02 的最嚴格條件重跑（排除營建金融、成交 ≥1 億、每邊滑價 0.3%）

訊號（季報；法定期限隔一個交易日收盤進場：Q1 5/15、Q2 8/14、Q3 11/14、年報 3/31）
  gm_jump    毛利率跳升：比去年同季 ≥ +3 個百分點、也比上一季 ≥ +2
  shortage   缺貨漲價：毛利率比去年同季 ≥ +3 個百分點，且單季營收年增 ≥ 20%
  shortage2  缺貨漲價＋營業利益率也比去年同季 ≥ +3 個百分點
  gm_yoy3    毛利率比去年同季 ≥ +3 個百分點（只看這一條）
  gm_up3     毛利率連 3 季上升（本季 > 上季 > 上上季），且比去年同季高
  gm_high    單季毛利率創 8 季新高
比較：全部買（資金平均分）、20 份挑最接近一年高點、20 份隨機（10 次中位數）；持有 60／120 日。

python -m research.gm_check
"""
from __future__ import annotations

import numpy as np

from research import fin_signals as fs
from research import portfolio as pf
from research.robust_check import excl_mask, lookup, strength

SLIP = 0.003


def signals():
    f, sig = fs.fin()
    g = f.groupby("code")
    ok4 = f["gap4"]
    ok2 = f["gap2"]
    big = f["rev_q"] > 1e5
    gm_yoy = f["gm"] - f["gm_4"]
    gmax7 = g["gm"].transform(lambda s: s.shift(1).rolling(7, min_periods=7).max())
    t7 = g["t"].diff(7) == 7
    sig = dict(sig)
    sig.pop("turn_prof")
    sig["gm_yoy3"] = ok4 & (gm_yoy >= 3) & big
    sig["gm_up3"] = ok4 & ok2 & (f["gm"] > f["gm_1"]) & (f["gm_1"] > f["gm_2"]) & (gm_yoy > 0) & big
    sig["gm_high"] = t7 & (f["gm"] > gmax7) & big
    return f, sig


NAMES = {**fs.NAMES, "gm_yoy3": "毛利率年增 ≥3 個百分點", "gm_up3": "毛利率連 3 季上升", "gm_high": "毛利率創 8 季新高"}


def main():
    near, liq = strength()
    f, sig = signals()
    base = f["gm"].notna() & (f["rev_q"] > 1e5)
    for k, m in list(sig.items()) + [("base_q", base)]:
        e = pf.events_at_next_close(f.loc[m.fillna(False), ["code", "deadline"]])
        e = e[e["date"] >= "2013-02-01"].copy()
        e["score"], e["liq"] = lookup(near, e), lookup(liq, e)
        e = e[(e["liq"].fillna(0) >= 1e8)]
        e = e[~excl_mask(e)].assign(score=lambda x: x["score"].fillna(-1))
        print(f"\n===== {NAMES.get(k, '基準：每季所有公司')}（成交≥1億、排除營建金融後 {len(e)} 次，每季約 {len(e) / 54:.0f} 檔） =====")
        for hold in (60, 120):
            res = pf.simulate(e[["code", "date"]], hold, None, start="2013-02-01", slip=SLIP)
            print(pf.fmt(res, "  全買"))
            if k == "base_q":
                continue
            r20 = pf.simulate(e[["code", "date", "score"]], hold, 20, start="2013-02-01", slip=SLIP)
            a = pf.simulate(e[["code", "date", "score"]], hold, 20, start="2013-02-01", end="2019-12-31", slip=SLIP)["curve"]
            b = pf.simulate(e[["code", "date", "score"]], hold, 20, start="2020-01-01", slip=SLIP)["curve"]
            print(pf.fmt(r20, "  20份挑最接近高點") + f"｜前段13~19 {a['cagr']:+.1%}/{a['mdd']:+.0%}｜後段20~26 {b['cagr']:+.1%}/{b['mdd']:+.0%}")
            rnd = [pf.simulate(e[["code", "date"]], hold, 20, start="2013-02-01", seed=s, slip=SLIP)["curve"] for s in range(10)]
            print(f"  20份隨機 持有{hold}日：年化 中位 {np.median([x['cagr'] for x in rnd]):+.1%}，最大回落 中位 {np.median([x['mdd'] for x in rnd]):+.1%}")
            if hold == 60:
                print("     挑高點 每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in r20["yearly"].items()))
    print("     加權每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly_taiex"].items()))


if __name__ == "__main__":
    main()
