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


def episodes(st, col, thr, below=True, gap=40):
    s = st[col].astype(float)
    hit = (s < thr) if below else (s > thr)
    rows, last = [], None
    for t in st.index[hit.fillna(False).astype(bool)]:
        if last is None or (t - last).days > gap:
            r = [st.loc[t, k] for k in ("ew20", "ew60", "big60")]
            rows.append(f"{t.date()}  均價≈{st.loc[t, 'zheng']:.1f}  之後20日 {r[0]:+.1%}  60日 {r[1]:+.1%}  大型股60日 {r[2]:+.1%}"
                        if not any(pd.isna(x) for x in r) else f"{t.date()}  均價≈{st.loc[t, 'zheng']:.1f}  （大盤資料不足）")
        last = t
    return rows


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
    # 用他公布過的 8 個數字（2025/1~2026/8）把平均轉換價值換算成「鄭大委買均價」的估計值（r=0.97，誤差約 ±3 元）
    st["zheng"] = 0.655 * st["conv"] + 49.3
    st["zheng_hi"] = st["zheng"] >= st["zheng"].rolling(500, min_periods=250).max() - 1e-9
    out += ["", "== 換算的鄭大委買均價（0.655×平均轉換價值+49.3） ==",
            tab("zheng", [0, 105, 108, 110, 113, 117, 121, 1e9], ["<105", "105-108", "108-110", "110-113", "113-117", "117-121", "≥121"])]
    out += ["", "== 恐慌事件（換算均價首次 <110，與前一次相隔 40 天以上） =="]
    out += episodes(st, "zheng", 110, True) + ["", "== 換算均價創兩年新高（相隔 40 天以上） =="] + episodes(st, "zheng_hi", 0.5, False)
    print("\n".join(out))
    OUT.parent.mkdir(exist_ok=True)
    keep = ["zheng", "n", "avg", "med", "pr75", "pr90", "lt100", "lt110", "ge120", "conv", "prem", "prem100", "avg_pct", "ew20", "ew60", "big60"]
    js = {"dates": [d.strftime("%Y-%m-%d") for d in st.index],
          "mkt": [None if pd.isna(x) else round(float(x), 4) for x in mk["ew"]],
          **{k: [None if pd.isna(x) else round(float(x), 4) for x in st[k]] for k in keep}}
    OUT.write_text(json.dumps(js, ensure_ascii=False))
    save_site_stats(st)
    return st


def save_site_stats(st: pd.DataFrame) -> None:
    """把回測結果存給網站的 CB 溫度計卡片（pipeline/cbtemp.py）"""
    from pipeline import cbtemp
    f = lambda x: None if pd.isna(x) else round(float(x), 4)  # noqa: E731
    edges = [(None, 105), (105, 108), (108, 110), (110, 113), (113, 117), (117, 121), (121, None)]
    buckets = []
    for lo, hi in edges:
        m = st["zheng"].notna() & st["ew60"].notna()
        if lo is not None:
            m &= st["zheng"] >= lo
        if hi is not None:
            m &= st["zheng"] < hi
        g = st[m]
        buckets.append({"lo": lo, "hi": hi, "n": int(len(g)), "r20": f(g["ew20"].mean()), "r60": f(g["ew60"].mean()),
                        "w60": f((g["ew60"] > 0).mean()), "big60": f(g["big60"].mean())})

    def ev(col, thr, below):
        s = st[col].astype(float)
        hit = (s < thr) if below else (s > thr)
        rows, last = [], None
        for t in st.index[hit.fillna(False).astype(bool)]:
            if last is None or (t - last).days > 40:
                rows.append({"date": t.strftime("%Y-%m-%d"), "value": f(st.loc[t, "zheng"]),
                             "r20": f(st.loc[t, "ew20"]), "r60": f(st.loc[t, "ew60"]), "big60": f(st.loc[t, "big60"])})
            last = t
        return rows
    v = st[st["ew60"].notna()]
    cbtemp.save_stats({"buckets": buckets, "episodes": ev("zheng", 110, True), "highs": ev("zheng_hi", 0.5, False),
                       "base": {"r20": f(v["ew20"].mean()), "r60": f(v["ew60"].mean()), "big60": f(v["big60"].mean())},
                       "stats_range": [v.index.min().strftime("%Y-%m-%d"), v.index.max().strftime("%Y-%m-%d")],
                       "stats_updated": pd.Timestamp.today().strftime("%Y-%m-%d")})


if __name__ == "__main__":
    main()
