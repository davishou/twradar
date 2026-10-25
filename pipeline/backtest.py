"""回測工具（研究用，網站排程不會執行）。讀 data/archive 長期資料庫，產生「漲停事件表」與超額報酬。

需要額外套件：pip install -r requirements-backtest.txt（pandas、scipy）

用法：
  python -m pipeline.backtest volratio        兩種量比的分組勝率與預測力（2026-10-25 的分析）
  python -m pipeline.backtest signals         漲停股訊號搜尋：前段資料找、後段資料驗證（research/）

程式內使用：
  from pipeline import backtest as bt
  q = bt.load_quotes()                # 全部行情（含還原價、漲停旗標），第一次約 15 秒，之後讀快取
  ev = bt.limitup_events(q)           # 每一次漲停一列，含各種特徵與之後 5/20/60 日報酬
  print(bt.bucket_table(ev, "B", [0, 1, 5, float("inf")], ["<1", "1-5", "≥5"]))

報酬定義（所有數字都已還原除權息）：
  - entry="next_close"：隔日收盤進場，持有 h 個交易日後收盤出場。需要隔日資料的特徵（如原網站量比）只能用這個。
  - entry="next_open"：隔日開盤進場，第 h 個交易日收盤出場（只用漲停日資料的特徵可以用）。
  - x{h}：超額報酬＝個股報酬 − 同期全市場等權平均報酬。勝率＝超額報酬 > 0 的比例（贏大盤）。
  - 隔日開盤就漲停（next_open_lu）或收盤鎖漲停（next_is_lu）實際上很難買到，研究時可排除。
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from . import config
from .util import limit_up

ARCHIVE = config.DATA_DIR / "archive"
CACHE = config.DATA_DIR / ".cache"          # 已列入 .gitignore
H = (5, 20, 60)


def _pd():
    try:
        import numpy as np
        import pandas as pd
    except ImportError as e:  # pragma: no cover
        raise SystemExit("回測需要 pandas：pip install -r requirements-backtest.txt") from e
    return pd, np


def _read_kind(kind: str, usecols=None, dtype=None):
    pd, _ = _pd()
    frames = []
    for p in sorted(glob.glob(str(ARCHIVE / kind / "*" / "*.csv.gz"))):
        df = pd.read_csv(p, dtype={"code": str, **(dtype or {})}, usecols=usecols)
        df["date"] = Path(p).name[:10]
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _cached(name: str, build):
    """依資料庫檔案數做快取鍵，資料庫有新資料時自動重建"""
    pd, _ = _pd()
    n = len(glob.glob(str(ARCHIVE / "*" / "*" / "*.csv.gz")))
    p = CACHE / f"{name}_{n}.pkl"
    if p.exists():
        return pd.read_pickle(p)
    CACHE.mkdir(parents=True, exist_ok=True)
    for old in CACHE.glob(f"{name}_*.pkl"):
        old.unlink()
    df = build()
    df.to_pickle(p)
    return df


# ------------------------------------------------------------------ 原始資料

def load_quotes():
    """全部普通股日行情 + 漲停旗標 + 還原價 adj（同一檔股票內，adj 的比值＝含權息報酬）"""
    pd, np = _pd()

    def build():
        q = _read_kind("quotes", usecols=["code", "market", "open", "high", "low", "close", "ref", "volume", "value"])
        q = q[q["code"].str.fullmatch(r"\d{4}")]
        for c in ("open", "high", "low", "close", "ref", "volume", "value"):
            q[c] = pd.to_numeric(q[c], errors="coerce")
        q = q.dropna(subset=["close"])
        refs = q["ref"].dropna().unique()
        lu = {r: limit_up(float(r)) for r in refs if r > 0}
        q["lu"] = q["ref"].map(lu)
        q["is_lu"] = (q["close"] >= q["lu"] - 1e-9) & q["lu"].notna()
        adj = pd.read_csv(ARCHIVE / "adjust.csv.gz", dtype={"code": str}, parse_dates=["date"])
        q = q.merge(adj[["date", "code", "factor"]], on=["date", "code"], how="left")
        q["factor"] = q["factor"].fillna(1.0)
        q = q.sort_values(["code", "date"]).reset_index(drop=True)
        q["cumf"] = q.groupby("code")["factor"].cumprod()
        q["adj"] = q["close"] / q["cumf"]
        q["adj_open"] = q["open"] / q["cumf"]
        return q
    return _cached("quotes", build)


def load_inst():
    """三大法人買賣超（張）"""
    return _cached("inst", lambda: _read_kind("inst"))


def load_margin():
    """融資融券餘額與限額（張）"""
    return _cached("margin", lambda: _read_kind("margin"))


def load_notices():
    """注意股（公告日），clauses 為款次；分號分隔"""
    return _cached("notices", lambda: _read_kind("notices", usecols=["code", "market", "clauses"]))


def companies() -> dict:
    """目前的公司資料（產業別、股數）。注意：這是現在的資料，不是當時的，回測用產業別大致可接受"""
    st = json.loads((config.STATE_DIR / "companies.json").read_text("utf-8"))
    return st.get("data", {})


def market_index(q):
    """全市場等權指數：每天所有股票報酬的平均（截在 ±11% 去掉錯誤值）累乘"""
    pd, _ = _pd()
    r = q.groupby("code", sort=False)["adj"].pct_change()
    mk = r.clip(-0.11, 0.11).groupby(q["date"]).mean().fillna(0)
    return (1 + mk).cumprod()


# ------------------------------------------------------------------ 事件表

def limitup_events(q=None, with_inst: bool = True, with_margin: bool = True, with_notices: bool = True):
    """每一次收盤漲停一列。特徵欄位（漲停日收盤就知道的，除非註明）：
      A          均量比：漲停日量 ÷ 前 5 日均量
      B          量比（原網站）：隔日量 ÷ 漲停日量  ← 需要隔日資料
      streak     連續漲停天數（含當天）
      one_price  一字漲停（開高低收同價）；locked＝收在最高價
      run20/run60  漲停前 20／60 日漲幅（不含當天）
      hi120      收盤 ÷ 前 120 日最高收盤（>1 代表創 120 日新高）
      value_e    成交金額（億）；price 收盤價
      mkt_n      當天全市場漲停家數；mkt20 全市場指數前 20 日報酬
      ind_n      同產業當天漲停家數
      f/t/d      外資／投信／自營買賣超占當天成交量比（%）
      fin_chg    融資餘額 5 日變化（%）；short_ratio 券資比（%）
      notice10   漲停前 10 個交易日內被列注意股的次數
      gap_next   隔日開盤相對漲停價（%）← 隔日資料；next_ret 隔日收盤報酬 ← 隔日資料
    報酬欄：xc{h}/rc{h}（隔日收盤進場）、xo{h}/ro{h}（隔日開盤進場），h = 5, 20, 60
    """
    pd, np = _pd()
    q = load_quotes() if q is None else q
    q = q.copy()
    g = q.groupby("code", sort=False)
    q["i"] = g.cumcount()
    q["dpos"] = q["date"].map({d: k for k, d in enumerate(sorted(q["date"].unique()))})
    q["v5"] = g["volume"].transform(lambda s: s.shift(1).rolling(5, min_periods=5).mean())
    q["run20"] = g["adj"].transform(lambda s: s.shift(1) / s.shift(21) - 1)
    q["run60"] = g["adj"].transform(lambda s: s.shift(1) / s.shift(61) - 1)
    q["hi120"] = q["adj"] / g["adj"].transform(lambda s: s.shift(1).rolling(120, min_periods=60).max())
    lu = q["is_lu"].astype(int)
    q["streak"] = lu.groupby((lu != lu.groupby(q["code"]).shift()).cumsum()).cumsum() * lu
    for k in ("volume", "open", "adj", "adj_open", "is_lu", "dpos", "close"):
        q[f"n_{k}"] = g[k].shift(-1)
    for h in H:
        q[f"c_{h}"] = g["adj"].shift(-1 - h)       # 隔日收盤進場的出場價
        q[f"cp_{h}"] = g["dpos"].shift(-1 - h)
        q[f"o_{h}"] = g["adj"].shift(-h)            # 隔日開盤進場、第 h 日收盤出場
        q[f"op_{h}"] = g["dpos"].shift(-h)

    idx = market_index(q)
    ix = idx.reindex(sorted(q["date"].unique())).values
    q["mkt20"] = q["dpos"].map(lambda p: ix[p] / ix[p - 20] - 1 if p >= 20 else np.nan)
    q["mkt_n"] = q.groupby("date")["is_lu"].transform("sum")

    ev = q[q["is_lu"] & (q["i"] >= 5) & q["n_volume"].notna() & (q["n_dpos"] == q["dpos"] + 1)].copy()
    ev = ev[(ev["volume"] > 0) & (ev["v5"] > 0)]
    ev["A"] = ev["volume"] / ev["v5"]
    ev["B"] = ev["n_volume"] / ev["volume"]
    ev["one_price"] = (ev["open"] == ev["close"]) & (ev["high"] == ev["low"])
    ev["locked"] = ev["high"] == ev["close"]
    ev["value_e"] = ev["value"] / 1e8
    ev["price"] = ev["close"]
    ev["next_is_lu"] = ev["n_is_lu"].astype(bool)
    ev["next_lu_price"] = ev["close"].map(lambda c: limit_up(float(c)))
    ev["next_open_lu"] = ev["n_open"] >= ev["next_lu_price"] - 1e-9
    ev["gap_next"] = (ev["n_open"] / ev["close"] - 1) * 100
    ev["next_ret"] = (ev["n_close"] / ev["close"] - 1) * 100
    comp = companies()
    ev["industry"] = ev["code"].map(lambda c: (comp.get(c) or {}).get("industry", ""))
    ev["ind_n"] = ev.groupby(["date", "industry"])["code"].transform("count")

    for h in H:
        okc = ev[f"cp_{h}"] == ev["dpos"] + 1 + h
        oko = ev[f"op_{h}"] == ev["dpos"] + h
        mc = ev["dpos"].map(lambda p, h=h: ix[p + 1 + h] / ix[p + 1] - 1 if p + 1 + h < len(ix) else np.nan)
        mo = ev["dpos"].map(lambda p, h=h: ix[p + h] / ix[p] - 1 if p + h < len(ix) else np.nan)
        ev[f"rc{h}"] = np.where(okc, ev[f"c_{h}"] / ev["n_adj"] - 1, np.nan)
        ev[f"xc{h}"] = ev[f"rc{h}"] - mc
        ev[f"ro{h}"] = np.where(oko, ev[f"o_{h}"] / ev["n_adj_open"] - 1, np.nan)
        ev[f"xo{h}"] = ev[f"ro{h}"] - mo

    if with_inst:
        inst = load_inst()
        ev = ev.merge(inst, on=["date", "code"], how="left")
        lots = ev["volume"] / 1000
        for k, c in (("f", "foreign"), ("t", "trust"), ("d", "dealer")):
            ev[k] = pd.to_numeric(ev[c], errors="coerce") / lots * 100
    if with_margin:
        m = load_margin().sort_values(["code", "date"])
        m["fin_bal"] = pd.to_numeric(m["fin_bal"], errors="coerce")
        m["short_bal"] = pd.to_numeric(m["short_bal"], errors="coerce")
        m["fin_chg"] = m.groupby("code")["fin_bal"].transform(lambda s: (s / s.shift(5).where(s.shift(5) > 0) - 1) * 100)
        m["short_ratio"] = m["short_bal"] / m["fin_bal"].where(m["fin_bal"] > 0) * 100
        ev = ev.merge(m[["date", "code", "fin_chg", "short_ratio"]], on=["date", "code"], how="left")
    if with_notices:
        n = load_notices()
        n = n.assign(dpos=n["date"].map({d: k for k, d in enumerate(sorted(q["date"].unique()))})).dropna(subset=["dpos"])
        by = n.groupby("code")["dpos"].apply(lambda s: np.sort(s.values)).to_dict()
        ev["notice10"] = [int(((a := by.get(c, np.array([]))) >= p - 10).sum() - (a >= p).sum()) if c in by else 0
                          for c, p in zip(ev["code"], ev["dpos"])]
    keep = ["date", "code", "market", "industry", "close", "price", "volume", "value_e", "A", "B", "streak", "one_price",
            "locked", "run20", "run60", "hi120", "mkt_n", "mkt20", "ind_n", "gap_next", "next_ret", "next_is_lu",
            "next_open_lu"] + [c for c in ("f", "t", "d", "fin_chg", "short_ratio", "notice10") if c in ev] + \
           [f"{p}{h}" for h in H for p in ("rc", "xc", "ro", "xo")]
    return ev[keep].reset_index(drop=True)


# ------------------------------------------------------------------ 統計

def stats(x) -> dict:
    """一組超額報酬的勝率、中位數、平均、次數"""
    x = x.dropna()
    return {"n": len(x), "win": (x > 0).mean() if len(x) else float("nan"),
            "med": x.median() if len(x) else float("nan"), "mean": x.mean() if len(x) else float("nan")}


def bucket_table(ev, col: str, bins, labels, prefix: str = "xc") -> str:
    """依 col 分組，列出各期間的勝率（贏大盤比例）、超額中位數、超額平均"""
    pd, _ = _pd()
    bk = pd.cut(ev[col], bins=bins, labels=labels, right=False)
    rows = []
    for b, s in ev.groupby(bk, observed=True):
        r = {"區間": b, "次數": len(s)}
        for h in H:
            st = stats(s[f"{prefix}{h}"])
            r[f"{h}日勝率"] = f"{st['win']:.0%}"
            r[f"{h}日超額中位"] = f"{st['med']:+.1%}"
            r[f"{h}日超額平均"] = f"{st['mean']:+.1%}"
        rows.append(r)
    return pd.DataFrame(rows).to_string(index=False)


def monthly_ic(ev, col: str, ret: str):
    """每月 Spearman 相關（特徵排名 vs 報酬排名）：回傳 (全體 IC, 月平均, t 值, 正的月份比例)"""
    pd, np = _pd()
    from scipy.stats import spearmanr
    d = ev[[col, ret, "date"]].dropna()
    ic = spearmanr(d[col], d[ret]).statistic
    m = d.groupby(d["date"].dt.to_period("M")).apply(
        lambda s: spearmanr(s[col], s[ret]).statistic if len(s) >= 20 else np.nan).dropna()
    return ic, m.mean(), m.mean() / m.std() * np.sqrt(len(m)), (m > 0).mean()


def report_volratio(ev) -> str:
    """2026-10-25：兩種量比的回測報告（隔日收盤進場）"""
    out = [f"樣本：{len(ev)} 次漲停，{ev['date'].min().date()} ~ {ev['date'].max().date()}",
           f"隔日收盤仍鎖漲停：{ev['next_is_lu'].mean():.1%}", "",
           "=== 原網站量比 B：隔日量 ÷ 漲停日量 ===",
           bucket_table(ev, "B", [0, 0.3, 0.6, 1, 2, 5, 10, float("inf")], ["<0.3", "0.3-0.6", "0.6-1", "1-2", "2-5", "5-10", "≥10"]),
           "", "=== 均量比 A：漲停日量 ÷ 前 5 日均量 ===",
           bucket_table(ev, "A", [0, 1, 2, 3, 5, 10, float("inf")], ["<1", "1-2", "2-3", "3-5", "5-10", "≥10"]),
           "", "=== B 排除隔日鎖漲停（買不到的） ===",
           bucket_table(ev[~ev["next_is_lu"]], "B", [0, 0.3, 0.6, 1, 2, 5, 10, float("inf")],
                        ["<0.3", "0.3-0.6", "0.6-1", "1-2", "2-5", "5-10", "≥10"]),
           "", "=== 預測力（月 IC） ==="]
    for h in H:
        parts = []
        for col in ("A", "B"):
            ic, m, t, pos = monthly_ic(ev, col, f"xc{h}")
            parts.append(f"{col}: 全體 {ic:+.3f}｜月平均 {m:+.3f} t={t:+.1f} 正月份 {pos:.0%}")
        out.append(f"{h:>2} 日　" + "　".join(parts))
    return "\n".join(out)


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "volratio"
    if cmd == "volratio":
        print(report_volratio(limitup_events(with_inst=False, with_margin=False, with_notices=False)))
    elif cmd == "signals":
        sys.path.insert(0, str(config.ROOT))
        from research import signal_search
        signal_search.main(argv[1:])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
