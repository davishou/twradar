"""財報比率的參數掃描（2026-11-03）：毛利率、營業利益率、稅前淨利率、股東權益報酬率（ROE）、三率三升

每個比率都試同一組格子：
  年增   本季比去年同季高 ≥ x 個百分點（x = >0、1、2、3、5），而且連續 k 季都這樣（k = 1~4）
  季增   本季比上一季高，連續 n 季（n = 1~3），同時本季比去年同季高 ≥ x（x = >0、1、3）
ROE 另外試「ROE 水準 ≥ 10／15／20%（年化）且比去年同季高」。
三率三升＝毛利率、營益率、稅前淨利率三個都比去年同季高 ≥ x，連續 k 季。

比率定義（都用單季，自己把累計數減出來）：
  毛利率＝毛利÷營收、營業利益率＝營業利益÷營收、稅前淨利率＝稅前淨利÷營收
  ROE（年化）＝單季 EPS × 4 ÷ 每股淨值；每股淨值＝公布期限那天收盤價 ÷ 股價淨值比（證交所／櫃買每日本益比檔）
共同：季報期限隔天收盤買、成交 ≥1 億、排除營建金融、每邊滑價 0.3%、20 份挑最接近一年高點；持有 60／120 日。
前段（2013~19）、後段（2020~26）用全期資金曲線切開算（不另外重跑）。

python -m research.ratio_sweep [base gm om pm roe tri]   結果存 research/results/ratio_<比率>.json
"""
from __future__ import annotations

import glob
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import fin_signals as fs
from research import portfolio as pf
from research.robust_check import excl_mask, lookup, strength

SLIP = 0.003
OUTDIR = Path(__file__).parent / "results"
NAMES = {"base": "對照：每季所有公司（不看比率）", "gm": "毛利率", "om": "營業利益率", "pm": "稅前淨利率", "roe": "股東權益報酬率（ROE）", "tri": "三率三升"}
XS = (0, 1, 2, 3, 5)


def frame():
    f, _ = fs.fin()
    for c in ("pretax", "eps"):
        prev = f.groupby(["code", "y"])[c].shift(1)
        f[c + "_q"] = np.where(f["q"] == 1, f[c], f[c] - prev)
    f["pm"] = f["pretax_q"] / f["rev_q"] * 100
    # ROE：單季 EPS×4 ÷ 每股淨值（期限日或之前最後一個交易日的 收盤÷淨值比）
    q = bt.load_quotes()[["date", "code", "close"]]
    days = np.array(sorted(q["date"].unique()))
    bv = []
    for dl in sorted(f["deadline"].unique()):
        i = days.searchsorted(np.datetime64(dl), side="right") - 1
        if i < 0:
            continue
        d = pd.Timestamp(days[i])
        p = bt.ARCHIVE / "val" / f"{d.year}" / f"{d.date()}.csv.gz"
        if not p.exists():
            continue
        v = pd.read_csv(p, dtype={"code": str})
        v["pb"] = pd.to_numeric(v["pb"], errors="coerce")
        c = q[q["date"] == d][["code", "close"]]
        v = v.merge(c, on="code")
        v["bvps"] = v["close"] / v["pb"]
        v["deadline"] = dl
        bv.append(v[["code", "deadline", "bvps"]])
    bv = pd.concat(bv)
    f = f.merge(bv, on=["code", "deadline"], how="left")
    f["roe"] = (f["eps_q"] * 4 / f["bvps"] * 100).where(f["bvps"] > 0)
    f = f.sort_values(["code", "t"]).reset_index(drop=True)
    g = f.groupby("code")
    for c in ("gm", "om", "pm", "roe"):
        f[f"{c}_yoy"] = (f[c] - g[c].shift(4)).where(g["t"].diff(4) == 4)
        f[f"{c}_qoq"] = (f[c] - g[c].shift(1)).where(g["t"].diff(1) == 1)
    f["big"] = f["rev_q"] > 1e5
    return f


def streak(f, ok: pd.Series, k: int) -> pd.Series:
    """ok 連續 k 季都成立（季度要連續）"""
    g = f.groupby("code")
    out = ok.fillna(False).astype(bool)
    for j in range(1, k):
        prev = ok.groupby(f["code"]).shift(j).fillna(False).astype(bool)
        out &= prev & (g["t"].diff(j) == j)
    return out


def cases(f, key):
    cs = {}
    if key == "base":
        return {("all", 0, 1): f["gm"].notna()}
    if key == "tri":
        for x in (0, 1, 2):
            ok = pd.Series(True, index=f.index)
            for c in ("gm", "om", "pm"):
                ok &= (f[f"{c}_yoy"] > 0) if x == 0 else (f[f"{c}_yoy"] >= x)
            for k in (1, 2, 3, 4):
                cs[("yoy", x, k)] = streak(f, ok, k)
        return cs
    yoy, qoq = f[f"{key}_yoy"], f[f"{key}_qoq"]
    for x in XS:
        ok = (yoy > 0) if x == 0 else (yoy >= x)
        for k in (1, 2, 3, 4):
            cs[("yoy", x, k)] = streak(f, ok, k)
    for n in (1, 2, 3):
        up = streak(f, qoq > 0, n)
        for x in (0, 1, 3):
            cs[("qoq", x, n)] = up & ((yoy > 0) if x == 0 else (yoy >= x))
    if key == "roe":
        for lv in (10, 15, 20):
            cs[("lvl", lv, 1)] = (f["roe"] >= lv) & (yoy > 0)
    return cs


def label(key, kind, x, k):
    if kind == "all":
        return NAMES["base"]
    nm = NAMES[key] if key != "roe" else "ROE"
    xs = ">0" if x == 0 else f"≥{x}pt"
    if kind == "yoy":
        return f"{nm} 年增 {xs}" + (f"，連 {k} 季" if k > 1 else "")
    if kind == "qoq":
        return f"{nm} 季增連 {k} 季＋年增 {xs}"
    return f"ROE ≥ {x}%＋年增"


def seg_cagr(yearly: dict, y0: int, y1: int):
    v = [1 + r for y, r in yearly.items() if y0 <= int(y) <= y1]
    if not v:
        return None
    yrs = len(v) - (11 / 12 if y0 == 2013 else 0) - (2 / 12 if y1 == 2026 else 0)   # 2013 從 2 月、2026 到 11 月
    return float(np.prod(v) ** (1 / max(yrs, 0.5)) - 1)


def main(keys):
    near, liq = strength()
    f = frame()
    f = f[f["big"]]
    excl = None
    OUTDIR.mkdir(exist_ok=True)
    for key in keys:
        t0 = time.time()
        out = []
        for (kind, x, k), m in cases(f, key).items():
            e = pf.events_at_next_close(f.loc[m.fillna(False), ["code", "deadline"]])
            e = e[e["date"] >= "2013-02-01"].copy()
            if e.empty:
                continue
            e["score"], e["liq"] = lookup(near, e), lookup(liq, e)
            e = e[(e["liq"].fillna(0) >= 1e8)]
            e = e[~excl_mask(e)].assign(score=lambda d: d["score"].fillna(-1))[["code", "date", "score"]]
            row = {"kind": kind, "x": x, "k": k, "name": label(key, kind, x, k), "per_q": round(len(e) / 52, 1)}
            for hold in (60, 120):
                res = pf.simulate(e, hold, 20, start="2013-02-01", slip=SLIP)
                y = res["yearly"]
                row[f"h{hold}"] = {"cagr": res["curve"]["cagr"], "mdd": res["curve"]["mdd"], "early": seg_cagr(y, 2013, 2019),
                                   "late": seg_cagr(y, 2020, 2026), "win": res["trade"]["win"], "n": res["n_trades"],
                                   "invested": res["invested"], "yearly": y}
            out.append(row)
            h = row["h60"]
            print(f"{row['name']:<28} 每季{row['per_q']:>5}檔｜60日 {h['cagr']:+.1%} 回落 {h['mdd']:+.0%} 前{h['early'] or 0:+.1%} 後{h['late'] or 0:+.1%}"
                  f"｜120日 {row['h120']['cagr']:+.1%} 回落 {row['h120']['mdd']:+.0%}", flush=True)
        (OUTDIR / f"ratio_{key}.json").write_text(json.dumps({"key": key, "name": NAMES[key], "rows": out}, ensure_ascii=False, indent=1))
        print(f"== {NAMES[key]} 完成 {len(out)} 組，{time.time() - t0:.0f} 秒 ==", flush=True)
    del excl


if __name__ == "__main__":
    main(sys.argv[1:] or ["base", "gm", "om", "pm", "roe", "tri"])
