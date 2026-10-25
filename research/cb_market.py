"""可轉債整體市況指標 → 大盤之後會不會反彈？（驗證鄭詩翰「CB 整體市場委買均價」的用法）

他在 FB 社團公布的 XQ 自寫表（2026/7/14、7/29、8/3 等）欄位：
  CB 委買平均價、PR75、PR90、平均轉換價值、平均轉換溢價率、轉換價值≥100 時的平均溢價率、
  委買價格區間 <95 / 95~100 / 100~105 / 105~110 / 110~120 / ≥120 的件數。
他的用法：均價跌到 108~110（2025 對等關稅後三天、2026/3 底、2026/7/29）＝極端恐慌，分批進場（波段部位最多 60%）；
          均價創兩年新高、僅次 2024 高峰＝過熱，降部位。

我們沒有每天的委買價，用替代：
  price  每檔的「次日參考價」（＝最後成交價；沒成交就沿用前一天），比委買價略高、但漲跌方向一致
  conv   平均轉換價值＝標的股價 ÷ 轉換價 × 100（資訊看板，2017 起）——和他的數字幾乎一樣（113.1 vs 112.6）
指標每天一筆，再看之後 20／60 個交易日的全市場等權報酬（以及前 50 大成交金額股票的等權報酬）。

python -m research.cb_market            印出結果並寫 research/out/cb_market.json（給報告頁用）
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import backtest as bt

ARCH = bt.ARCHIVE
OUT = Path(__file__).parent / "out" / "cb_market.json"


def _read(kind, cols):
    fr = []
    for p in sorted(glob.glob(str(ARCH / kind / "*" / "*.csv.gz"))):
        df = pd.read_csv(p, dtype={"code": str}, usecols=lambda c: c in cols)
        df["date"] = Path(p).name[:10]
        fr.append(df)
    df = pd.concat(fr, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def daily_stats() -> pd.DataFrame:
    q = _read("cbq", {"code", "close", "ref_next"})
    b = _read("cbb", {"code", "conv_price", "stock_price"})
    for c in ("close", "ref_next"):
        q[c] = pd.to_numeric(q[c], errors="coerce")
    for c in ("conv_price", "stock_price"):
        b[c] = pd.to_numeric(b[c], errors="coerce")
    q["price"] = q["ref_next"].fillna(q["close"])
    q = q[(q["price"] > 30) & (q["price"] < 2000)]
    m = q.merge(b, on=["date", "code"], how="left")
    m["conv"] = m["stock_price"] / m["conv_price"] * 100
    m.loc[~m["conv"].between(1, 2000), "conv"] = np.nan
    m["prem"] = m["price"] / m["conv"] - 1
    rows = []
    for d, g in m.groupby("date"):
        p = g["price"].to_numpy()
        cv = g["conv"].dropna()
        hi = g[g["conv"] >= 100]
        rows.append({"date": d, "n": len(p), "avg": p.mean(), "med": np.median(p), "pr75": np.percentile(p, 75),
                     "pr90": np.percentile(p, 90), "lt100": (p < 100).mean(), "lt105": (p < 105).mean(), "lt110": (p < 110).mean(),
                     "ge120": (p >= 120).mean(), "conv": cv.mean() if len(cv) > 20 else np.nan,
                     "prem": g["prem"].median() if len(cv) > 20 else np.nan,
                     "prem100": hi["prem"].mean() if len(hi) > 5 else np.nan})
    return pd.DataFrame(rows).set_index("date")


def market() -> pd.DataFrame:
    qq = bt.load_quotes()
    ew = bt.market_index(qq)
    # 大型股：每天前 50 大成交金額（前 20 日平均）的等權報酬，近似加權指數
    qq = qq.sort_values(["code", "date"])
    qq["r"] = qq.groupby("code", sort=False)["adj"].pct_change().clip(-0.11, 0.11)
    qq["v20"] = qq.groupby("code", sort=False)["value"].transform(lambda s: s.rolling(20, min_periods=10).mean().shift(1))
    qq["rk"] = qq.groupby("date")["v20"].rank(ascending=False)
    big = (1 + qq[qq["rk"] <= 50].groupby("date")["r"].mean().fillna(0)).cumprod()
    return pd.DataFrame({"ew": ew, "big": big})


def fwd(s: pd.Series, n: int) -> pd.Series:
    return s.shift(-n) / s - 1


def main():
    st = daily_stats()
    mk = market().reindex(st.index).ffill()
    for n in (20, 60):
        st[f"ew{n}"] = fwd(mk["ew"], n)
        st[f"big{n}"] = fwd(mk["big"], n)
    st["ew_dd"] = mk["ew"] / mk["ew"].rolling(250, min_periods=60).max() - 1
    # 指標的「歷史位階」：過去 500 日（約兩年）的百分位，跟他說的「兩年新高」對應
    for c in ("avg", "med", "lt110", "conv"):
        st[f"{c}_pct"] = st[c].rolling(500, min_periods=120).rank(pct=True)
    out = [f"期間 {st.index.min().date()} ~ {st.index.max().date()}，{len(st)} 天（CB 行情）；有轉換價值 {st['conv'].notna().sum()} 天"]
    base20, base60 = st["ew20"].mean(), st["ew60"].mean()
    out.append(f"全期平均：之後 20 日 {base20:+.2%}、60 日 {base60:+.2%}")

    def tab(col, bins, labels):
        g = st.groupby(pd.cut(st[col], bins, labels=labels), observed=True)
        t = g.agg(天數=("ew20", "size"), 之後20日=("ew20", "mean"), 勝率20=("ew20", lambda s: (s > 0).mean()),
                  之後60日=("ew60", "mean"), 勝率60=("ew60", lambda s: (s > 0).mean()), 大型股60=("big60", "mean"))
        return t.to_string(float_format=lambda x: f"{x:.3f}")
    out += ["", "== CB 平均價（參考價） ==", tab("avg", [0, 108, 112, 116, 120, 125, 130, 1e9], ["<108", "108-112", "112-116", "116-120", "120-125", "125-130", "≥130"])]
    out += ["", "== 平均轉換價值 ==", tab("conv", [0, 85, 90, 95, 100, 105, 110, 1e9], ["<85", "85-90", "90-95", "95-100", "100-105", "105-110", "≥110"])]
    out += ["", "== 價格 <110 的 CB 占比 ==", tab("lt110", [0, .4, .5, .55, .6, .65, 1.01], ["<40%", "40-50%", "50-55%", "55-60%", "60-65%", "≥65%"])]
    out += ["", "== 平均價兩年位階 ==", tab("avg_pct", [0, .05, .1, .25, .5, .75, .9, .95, 1.01], ["<5%", "5-10%", "10-25%", "25-50%", "50-75%", "75-90%", "90-95%", "≥95%"])]
    print("\n".join(out))
    OUT.parent.mkdir(exist_ok=True)
    keep = ["n", "avg", "med", "pr75", "pr90", "lt100", "lt110", "ge120", "conv", "prem", "prem100", "avg_pct", "ew20", "ew60", "big60"]
    js = {"dates": [d.strftime("%Y-%m-%d") for d in st.index],
          "mkt": [None if pd.isna(x) else round(float(x), 4) for x in mk["ew"]],
          **{k: [None if pd.isna(x) else round(float(x), 4) for x in st[k]] for k in keep}}
    OUT.write_text(json.dumps(js, ensure_ascii=False))
    return st


if __name__ == "__main__":
    main()
