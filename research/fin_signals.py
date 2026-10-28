"""「缺貨漲價型」財報訊號回測：公布後進場，之後股票有沒有贏大盤？

資料：data/archive/revenue（月營收，2013 起）、data/archive/fin（季報累計數，2013 起，自己減出單季）、
      股票還原價（長期資料庫，補到哪算到哪；目前 2017/11 起）。
進場：不知道每家實際公布日，一律用「法定最後期限」的隔一個交易日收盤進場（保守、不偷看）：
      月營收 → 次月 10 日；Q1 → 5/15、Q2 → 8/14、Q3 → 11/14、Q4（年報）→ 隔年 3/31。
報酬：股票還原報酬 − 全市場等權報酬（超額），看 20／60／120 個交易日。
驗證：2022/7 以前當「前段」（找規則），以後當「後段」（驗證），兩段都要贏才算數。

訊號
  rev_turn   營收由衰退轉成長：近 3 個月合計年增 ≥ 20%，且 3 個月前那一期 ≤ 0%
  rev_accel  營收年增加速：單月年增 ≥ 30%，且近 3 個月年增一個月比一個月高
  rev_high   營收創 24 個月新高且年增 ≥ 30%
  gm_jump    毛利率跳升：單季毛利率比去年同季高 ≥ 3 個百分點、也比上一季高 ≥ 2 個百分點
  turn_prof  轉虧為盈：單季營業利益 > 0，前兩季都 < 0
  shortage   缺貨漲價（組合）：毛利率比去年同季高 ≥ 3 個百分點，且單季營收年增 ≥ 20%
  shortage2  缺貨漲價＋營業利益率也比去年同季高 ≥ 3 個百分點

python -m research.fin_signals
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import backtest as bt

ARCH = bt.ARCHIVE
SPLIT = pd.Timestamp("2022-07-01")
HZ = (20, 60, 120)
OUT = Path(__file__).parent / "out" / "fin_signals.json"


def _read(kind):
    fr = []
    for p in sorted(glob.glob(str(ARCH / kind / "*" / "*.csv.gz"))):
        df = pd.read_csv(p, dtype={"code": str})
        df["period"] = Path(p).name.split(".")[0]
        fr.append(df)
    return pd.concat(fr, ignore_index=True)


def revenue():
    r = _read("revenue")
    r = r[r["code"].str.fullmatch(r"\d{4}")]
    for c in ("rev", "rev_ly", "yoy"):
        r[c] = pd.to_numeric(r[c], errors="coerce")
    r["ym"] = pd.PeriodIndex(r["period"], freq="M")
    r = r.drop_duplicates(["code", "ym"]).sort_values(["code", "ym"]).reset_index(drop=True)
    g = r.groupby("code", sort=False)
    r["rev3"] = g["rev"].transform(lambda s: s.rolling(3).sum())
    r["rev3_ly"] = g["rev_ly"].transform(lambda s: s.rolling(3).sum())
    r["yoy3"] = r["rev3"] / r["rev3_ly"] - 1
    r["yoy3_3"] = g["yoy3"].shift(3)
    r["yoy_1"], r["yoy_2"] = g["yoy"].shift(1), g["yoy"].shift(2)
    r["hi24"] = g["rev"].transform(lambda s: s.shift(1).rolling(23, min_periods=12).max())
    # 次月 10 日公布期限
    r["deadline"] = (r["ym"] + 1).dt.to_timestamp() + pd.Timedelta(days=9)
    sig = {
        "rev_turn": (r["yoy3"] >= 0.20) & (r["yoy3_3"] <= 0),
        "rev_accel": (r["yoy"] >= 30) & (r["yoy"] > r["yoy_1"]) & (r["yoy_1"] > r["yoy_2"]),
        "rev_high": (r["rev"] > r["hi24"]) & (r["yoy"] >= 30),
    }
    return r, sig


def fin():
    f = _read("fin")
    f = f[f["code"].str.fullmatch(r"\d{4}")]
    for c in ("rev", "gross", "op", "pretax", "eps"):
        f[c] = pd.to_numeric(f[c], errors="coerce")
    f["y"] = f["period"].str[:4].astype(int)
    f["q"] = f["period"].str[-1].astype(int)
    f = f.drop_duplicates(["code", "y", "q"]).sort_values(["code", "y", "q"]).reset_index(drop=True)
    # 累計 → 單季：同一年內減掉上一季累計
    for c in ("rev", "gross", "op"):
        prev = f.groupby(["code", "y"])[c].shift(1)
        f[c + "_q"] = np.where(f["q"] == 1, f[c], f[c] - prev)
    f.loc[f["rev_q"] <= 0, "rev_q"] = np.nan
    f["gm"] = f["gross_q"] / f["rev_q"] * 100
    f["om"] = f["op_q"] / f["rev_q"] * 100
    f["t"] = f["y"] * 4 + f["q"]
    f = f.set_index(["code", "t"])
    for c in ("gm", "om", "rev_q", "op_q"):
        for k in (1, 2, 4):
            f[f"{c}_{k}"] = f.groupby(level="code")[c].shift(k)
            # shift 只在連續季度才對：檢查前 k 季真的存在
    f = f.reset_index()
    f["gap4"] = f.groupby("code")["t"].diff(4) == 4
    f["gap2"] = f.groupby("code")["t"].diff(2) == 2
    f["ryoy"] = f["rev_q"] / f["rev_q_4"] - 1
    dl = {1: "-05-15", 2: "-08-14", 3: "-11-14"}
    f["deadline"] = [pd.Timestamp(f"{y + 1}-03-31") if q == 4 else pd.Timestamp(f"{y}{dl[q]}") for y, q in zip(f["y"], f["q"])]
    ok4, ok2 = f["gap4"], f["gap2"]
    gm_yoy = f["gm"] - f["gm_4"]
    sig = {
        "gm_jump": ok4 & (gm_yoy >= 3) & (f["gm"] - f["gm_1"] >= 2) & (f["rev_q"] > 1e5),
        "turn_prof": ok2 & (f["op_q"] > 0) & (f["op_q_1"] < 0) & (f["op_q_2"] < 0),
        "shortage": ok4 & (gm_yoy >= 3) & (f["ryoy"] >= 0.20) & (f["rev_q"] > 1e5),
        "shortage2": ok4 & (gm_yoy >= 3) & (f["ryoy"] >= 0.20) & (f["om"] - f["om_4"] >= 3) & (f["rev_q"] > 1e5),
    }
    return f, sig


def prices():
    q = bt.load_quotes()[["date", "code", "adj"]]
    mk = bt.market_index(bt.load_quotes())
    px = q.pivot(index="date", columns="code", values="adj").sort_index()
    return px, mk.reindex(px.index)


def returns(ev, px, mk):
    """ev: code, deadline → 隔一個交易日收盤進場，之後 n 日超額"""
    days = px.index
    i0 = days.searchsorted(ev["deadline"].values, side="right")      # 期限當天之後的第一個交易日
    ev = ev.assign(i0=i0)
    ev = ev[(ev["i0"] < len(days)) & ev["code"].isin(px.columns)].copy()
    cols = {c: k for k, c in enumerate(px.columns)}
    arr, m = px.to_numpy(), mk.to_numpy()
    ci = ev["code"].map(cols).to_numpy()
    ev["date"] = days[ev["i0"].to_numpy()]
    for n in HZ:
        j = ev["i0"].to_numpy() + n
        okj = j < len(days)
        p0 = arr[ev["i0"].to_numpy(), ci]
        p1 = np.where(okj, arr[np.minimum(j, len(days) - 1), ci], np.nan)
        m0, m1 = m[ev["i0"].to_numpy()], np.where(okj, m[np.minimum(j, len(days) - 1)], np.nan)
        ev[f"ex{n}"] = (p1 / p0 - 1) - (m1 / m0 - 1)
    return ev


def summary(e):
    out = {"n": int(len(e))}
    for n in HZ:
        x = e[f"ex{n}"].dropna()
        out[f"n{n}"] = int(len(x))
        out[f"mean{n}"] = None if len(x) < 10 else round(float(x.mean()), 4)
        out[f"med{n}"] = None if len(x) < 10 else round(float(x.median()), 4)
        out[f"win{n}"] = None if len(x) < 10 else round(float((x > 0).mean()), 4)
        out[f"big{n}"] = None if len(x) < 10 else round(float((x > 0.3).mean()), 4)
    return out


NAMES = {"rev_turn": "營收由衰退轉成長", "rev_accel": "營收年增加速", "rev_high": "營收創兩年新高＋年增 30%",
         "gm_jump": "毛利率跳升", "turn_prof": "轉虧為盈", "shortage": "缺貨漲價（毛利率↑＋營收年增）",
         "shortage2": "缺貨漲價＋營益率↑", "base_m": "基準：每月所有公司", "base_q": "基準：每季所有公司"}


def main():
    px, mk = prices()
    start = px.index[0]
    r, rs = revenue()
    f, fs = fin()
    res, rows = {}, []
    evs = {k: r.loc[m.fillna(False), ["code", "deadline"]] for k, m in rs.items()}
    evs.update({k: f.loc[m.fillna(False), ["code", "deadline"]] for k, m in fs.items()})
    evs["base_m"] = r.loc[r["yoy"].notna(), ["code", "deadline"]]
    evs["base_q"] = f.loc[f["gm"].notna(), ["code", "deadline"]]
    for k, e in evs.items():
        e = returns(e[e["deadline"] >= start], px, mk)
        a, b = e[e["date"] < SPLIT], e[e["date"] >= SPLIT]
        res[k] = {"name": NAMES[k], "all": summary(e), "early": summary(a), "late": summary(b)}
        for lab, s in (("全部", res[k]["all"]), ("前段", res[k]["early"]), ("後段", res[k]["late"])):
            fm = lambda x: "—" if x is None else f"{x:+.1%}"  # noqa: E731
            fw = lambda x: "—" if x is None else f"{x:.0%}"  # noqa: E731
            rows.append({"訊號": NAMES[k], "期間": lab, "次數": s["n"],
                         **{f"{n}日": f"{fm(s[f'mean{n}'])} 中位{fm(s[f'med{n}'])} 勝{fw(s[f'win{n}'])}" for n in HZ},
                         "120日大漲(>30%)": fw(s["big120"])})
    pd.set_option("display.width", 250)
    print(f"股價期間 {px.index[0].date()} ~ {px.index[-1].date()}；前後段切在 {SPLIT.date()}；數字＝超額報酬（減全市場等權）")
    print(pd.DataFrame(rows).to_string(index=False))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"range": [str(px.index[0].date()), str(px.index[-1].date())], "split": str(SPLIT.date()), "res": res},
                              ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    main()
