"""最佳組合的耐用度檢查（2026-11-02 第二輪）：排除營建、金融，加滑價、提高流動性門檻，再測一次。

組合：營收年增加速（或營收創兩年新高）＋同天挑「股價最接近一年高點」（前一天資料）、20 日均成交 ≥ 1 億，
      資金 20 份、持有 60 日（也看 10 份、20 日）。
變化：
  - 產業：全部／排除營建（建材營造）與金融（金融保險）
  - 滑價：每邊 0、0.3%、0.5%（加在手續費 0.1425%×2＋證交稅 0.3% 之外）
  - 流動性：20 日均成交 ≥ 1 億／≥ 3 億
產業別用 companies.json（現在上市櫃的公司）；已下市的公司沒有產業別，用代號推：25xx＝營建、28xx＝金融。

python -m research.robust_check
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from pipeline import config
from research import fin_signals as fs
from research import portfolio as pf

EXCL_IND = {"建材營造", "金融保險"}


def sector_excluded() -> set[str]:
    comp = json.loads((config.DATA_DIR / "state" / "companies.json").read_text())["data"]
    return {c for c, v in comp.items() if v.get("industry") in EXCL_IND}


def is_excluded(codes: pd.Series, known: set[str], listed: set[str]) -> pd.Series:
    by_prefix = codes.str[:2].isin(["25", "28"]) & ~codes.isin(listed)
    return codes.isin(known) | by_prefix


def lookup(mat: pd.DataFrame, e: pd.DataFrame) -> list:
    return [mat.at[d, c] if c in mat.columns and d in mat.index else np.nan for d, c in zip(e["date"], e["code"])]


def strength():
    """（最接近一年高點, 20 日均成交金額），都用前一天資料"""
    q = bt.load_quotes()[["date", "code", "adj", "value"]]
    adj = q.pivot(index="date", columns="code", values="adj")
    near = (adj / adj.rolling(250, min_periods=200).max()).shift(1)
    liq = q.pivot(index="date", columns="code", values="value").rolling(20, min_periods=15).mean().shift(1)
    return near, liq


def excl_mask(e: pd.DataFrame) -> pd.Series:
    comp = json.loads((config.DATA_DIR / "state" / "companies.json").read_text())["data"]
    return is_excluded(e["code"], sector_excluded(), set(comp))


def line(res, a, b, lab):
    return pf.fmt(res, lab) + f"｜前段13~19 {a['cagr']:+.1%}/{a['mdd']:+.0%}｜後段20~26 {b['cagr']:+.1%}/{b['mdd']:+.0%}"


def main():
    near, liq = strength()
    r, rs = fs.revenue()
    for key in ("rev_accel", "rev_high"):
        e0 = pf.events_at_next_close(r.loc[rs[key].fillna(False), ["code", "deadline"]])
        e0 = e0[e0["date"] >= "2013-02-01"].copy()
        e0["score"], e0["liq"] = lookup(near, e0), lookup(liq, e0)
        e0["score"] = e0["score"].fillna(-1)
        e0["excl"] = excl_mask(e0)
        n_ex = e0.loc[e0["liq"].fillna(0) >= 1e8, "excl"].mean()
        print(f"\n===== {fs.NAMES[key]}：成交 ≥1 億的訊號中營建＋金融占 {n_ex:.1%} =====")
        for minliq, llab in ((1e8, "≥1億"), (3e8, "≥3億")):
            for ex in (False, True):
                e = e0[(e0["liq"].fillna(0) >= minliq) & (~e0["excl"] if ex else True)][["code", "date", "score"]]
                for slip in (0, 0.003, 0.005):
                    for sl, hold in ((20, 60), (10, 60), (20, 20)):
                        if (sl, hold) != (20, 60) and slip != 0.003:
                            continue
                        kw = dict(slip=slip)
                        res = pf.simulate(e, hold, sl, start="2013-02-01", **kw)
                        a = pf.simulate(e, hold, sl, start="2013-02-01", end="2019-12-31", **kw)["curve"]
                        b = pf.simulate(e, hold, sl, start="2020-01-01", **kw)["curve"]
                        lab = f"{llab} {'排除營建金融' if ex else '全部產業'} 滑價{slip:.1%}"
                        print(line(res, a, b, lab))
                        if (sl, hold, slip) == (20, 60, 0.003):
                            print("     每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
        print("     加權：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly_taiex"].items()))
    # 對照：純強勢（每月第一個交易日、不看營收）同樣排除＋滑價
    days = near.index[near.index >= "2013-02-01"]
    first = pd.Series(days).groupby([days.year, days.month]).first().values
    rows = [pd.DataFrame({"code": near.columns, "date": d, "score": near.loc[d].values, "liq": liq.loc[d].values}) for d in first]
    m = pd.concat(rows).dropna(subset=["score"])
    m = m[(m["liq"].fillna(0) >= 1e8) & ~excl_mask(m)]
    print(pf.fmt(pf.simulate(m[["code", "date", "score"]], 60, 20, start="2013-02-01", slip=0.003), "\n對照 純強勢（不看營收）≥1億 排除營建金融 滑價0.3%"))


if __name__ == "__main__":
    main()
