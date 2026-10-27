"""回測鄭詩翰的可轉債訊號（規則在 pipeline/cbsig.py 的 SIGNALS／detect，網站每天也用同一份規則標記）。

做法
  1. 每檔 CB 每天組一筆特徵：CB 價格（行情 2011 起）、轉換價值與餘額（資訊看板 2017 起）、
     標的股還原價（股票行情；目前 2018/7 起，長期資料庫補到哪就算到哪）。
  2. 丟進 detect 找訊號；同一檔同一訊號 20 個交易日內只算第一次。
  3. 訊號日收盤後才知道，所以從「隔天收盤」進場，看之後 20／60 個交易日：
     股票超額報酬＝標的股報酬 − 全市場等權報酬；CB 報酬＝CB 價格漲跌（與同期全部 CB 平均比）。
  4. 前段（2022/6 以前）與後段分開看，兩段各 ≥ 30 次且都符合才算「通過」（CB 報酬很偏，不看勝率）：
     做多：60 日 CB 超額平均 > 0，且大賺（CB 60 日 ≥ +20%）機率 ≥ 同期全部 CB 的 1.2 倍；
     警訊：60 日 CB 超額平均 < 0，且大賠（CB 60 日 ≤ −10%）機率 ≥ 同期全部 CB 的 1.2 倍。

python -m research.cb_signals        印出結果，並存給網站（data/state/cb_sig.json → site/data/cb_sig.json）
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from pipeline import cbsig

ARCH = bt.ARCHIVE
SPLIT = "2022-07-01"
H = (1, 5, 10, 20, 60)     # 持有天數（判定只看 60 日，其他給網站看短線）


def _read(kind, cols):
    fr = []
    for p in sorted(glob.glob(str(ARCH / kind / "*" / "*.csv.gz"))):
        df = pd.read_csv(p, dtype={"code": str}, usecols=lambda c: c in cols)
        df["date"] = Path(p).name[:10]
        fr.append(df)
    df = pd.concat(fr, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def panel():
    q = _read("cbq", {"code", "name", "close", "lots"})
    q["close"] = pd.to_numeric(q["close"], errors="coerce")
    q["lots"] = pd.to_numeric(q["lots"], errors="coerce").fillna(0)
    q = q.sort_values(["code", "date"]).reset_index(drop=True)
    first_arch = q["date"].min()
    first = q.groupby("code")["date"].transform("min")
    q["listing"] = first.where(first > first_arch + pd.Timedelta(days=30))
    g = q.groupby("code", sort=False)
    q["price"] = g["close"].ffill()
    g = q.groupby("code", sort=False)
    q["age"] = g.cumcount() + 1
    q.loc[q["listing"].isna(), "age"] = np.nan
    q["hi60"] = g["price"].transform(lambda s: s.shift(1).rolling(59, min_periods=40).max())
    q["lo60"] = g["price"].transform(lambda s: s.shift(1).rolling(59, min_periods=40).min())
    q["v20"] = g["lots"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    q["chg"] = g["price"].diff()
    q["cret20"] = g["price"].transform(lambda s: s / s.shift(20) - 1)
    # 提前下市（強制贖回、轉換完、到期、賣回）的 CB：持有期還沒滿就沒有價格了。
    # 不能直接丟掉（會漏掉被贖回的大賺、到期的平盤），改用下市前最後價格出場。
    last_px = g["price"].transform("last")
    gone = q.groupby("code")["date"].transform("max") < q["date"].max()
    for n in H:
        nxt, fut = g["price"].shift(-1), g["price"].shift(-1 - n)
        fut = fut.where(fut.notna() | ~gone | nxt.isna(), last_px)
        q[f"cb{n}"] = fut / nxt - 1

    b = _read("cbb", {"code", "conv_price", "stock_price", "put_end", "out_amt", "issue_amt", "conv_end"})
    for c in ("conv_price", "stock_price", "out_amt", "issue_amt"):
        b[c] = pd.to_numeric(b[c], errors="coerce")
    q = q.merge(b, on=["date", "code"], how="left")
    q["conv"] = q["stock_price"] / q["conv_price"] * 100
    q.loc[~q["conv"].between(1, 2000), "conv"] = np.nan
    q["remain"] = q["out_amt"] / q["issue_amt"] * 100
    g = q.groupby("code", sort=False)
    q["conv1"] = g["conv"].shift(1)
    q["conv20"] = g["conv"].shift(20)
    mat = pd.to_datetime(q["conv_end"], errors="coerce")
    q["yrs"] = (mat - q["date"]).dt.days / 365.25
    q["yrs1"] = g["yrs"].shift(1)
    q["age_days"] = (q["date"] - q["listing"]).dt.days
    q["age_days1"] = g["age_days"].shift(1)

    s = bt.load_quotes()[["date", "code", "adj"]].sort_values(["code", "date"])
    gs = s.groupby("code", sort=False)["adj"]
    s["shi60"] = gs.transform(lambda x: x.shift(1).rolling(59, min_periods=40).max())
    s["slo60"] = gs.transform(lambda x: x.shift(1).rolling(59, min_periods=40).min())
    s["sma87"] = gs.transform(lambda x: x.rolling(87, min_periods=87).mean())
    s["sret20"] = gs.transform(lambda x: x / x.shift(20) - 1)
    mk = bt.market_index(bt.load_quotes())
    for n in H:
        s[f"s{n}"] = gs.transform(lambda x, n=n: x.shift(-1 - n) / x.shift(-1) - 1)
    s = s.rename(columns={"code": "scode", "adj": "stockpx"})
    q["scode"] = q["code"].str[:4]
    q = q.merge(s, on=["date", "scode"], how="left")
    mkt = pd.DataFrame({"date": mk.index, **{f"m{n}": (mk.shift(-1 - n) / mk.shift(-1) - 1).values for n in H}})
    q = q.merge(mkt, on="date", how="left")
    for n in H:
        q[f"ex{n}"] = q[f"s{n}"] - q[f"m{n}"]
        q[f"cbbase{n}"] = q.groupby("date")[f"cb{n}"].transform("mean")
    # CB 是「虧損有限、獲利無限」：看大賺（60 日 ≥ +20%）與大賠（≤ −10%）的機率，跟同一天全部 CB 比
    q["big"] = (q["cb60"] >= 0.2).where(q["cb60"].notna())
    q["loss"] = (q["cb60"] <= -0.1).where(q["cb60"].notna())
    q["bigbase"] = q.groupby("date")["big"].transform("mean")
    q["lossbase"] = q.groupby("date")["loss"].transform("mean")
    return q


def events(q: pd.DataFrame) -> pd.DataFrame:
    cols = ["price", "hi60", "lo60", "lots", "v20", "chg", "conv", "conv1", "conv20", "stockpx", "shi60", "slo60", "sma87",
            "sret20", "cret20", "remain", "age", "age_days", "age_days1", "put_end", "yrs", "yrs1"]
    sub = q[q["date"] >= q.loc[q["conv"].notna(), "date"].min()]
    rows = []
    recs = sub[["code", "date"] + cols].to_dict("records")
    idx = sub.index.to_numpy()
    for i, r in zip(idx, recs):
        f = {k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in r.items()}
        f["stock"] = f.pop("stockpx")
        f["d"] = r["date"].strftime("%Y-%m-%d")
        f["age"] = int(f["age"]) if f["age"] is not None else None
        if isinstance(f.get("put_end"), str) and not f["put_end"]:
            f["put_end"] = None
        for k in cbsig.detect(f):
            rows.append((i, k))
    ev = pd.DataFrame(rows, columns=["i", "sig"])
    ev = ev.join(q[["code", "name", "date", "scode", *[f"{p}{n}" for n in H for p in ("ex", "cb", "cbbase")], "big", "loss", "bigbase", "lossbase"]], on="i")
    # 同一檔同一訊號 20 個交易日內只算一次
    q_rank = q.groupby("code").cumcount()
    ev["k"] = q_rank.reindex(ev["i"]).to_numpy()
    ev = ev.sort_values(["sig", "code", "date"])
    keep, last = [], {}
    for r in ev.itertuples():
        key = (r.sig, r.code)
        if key in last and r.k - last[key] < 20:
            continue
        last[key] = r.k
        keep.append(r.Index)
    return ev.loc[keep].drop(columns=["k"])


def stat(e: pd.DataFrame) -> dict:
    f = lambda x: None if x is None or pd.isna(x) else round(float(x), 4)  # noqa: E731
    v = e.dropna(subset=["ex60"])
    w = e.dropna(subset=["ex20"])
    hz = {}
    for n in H:   # 各持有天數：股票超額平均、勝率、CB 超額平均
        x, c = e[f"ex{n}"].dropna(), (e[f"cb{n}"] - e[f"cbbase{n}"]).dropna()
        hz[str(n)] = [f(x.mean()) if len(x) >= 10 else None, f((x > 0).mean()) if len(x) >= 10 else None, f(c.mean()) if len(c) >= 10 else None]
    return {"n": int(len(e)), "n60": int(len(v)), "hz": hz,
            "win20": f((w["ex20"] > 0).mean()) if len(w) else None, "mean20": f(w["ex20"].mean()), "med20": f(w["ex20"].median()),
            "win60": f((v["ex60"] > 0).mean()) if len(v) else None, "mean60": f(v["ex60"].mean()), "med60": f(v["ex60"].median()),
            "cb20": f(e["cb20"].mean()), "cb60": f(e["cb60"].mean()), "cbbase60": f(e["cbbase60"].mean()),
            "cbwin60": f((e.dropna(subset=["cb60"])["cb60"] > 0).mean()) if e["cb60"].notna().any() else None,
            # CB 超額＝這檔 CB 之後漲跌 − 同一天全部 CB 平均漲跌（他是買 CB／CBAS，這是主要看的）
            **({} if not e["cb60"].notna().any() else {
                "cbx20": f((e["cb20"] - e["cbbase20"]).mean()), "cbx60": f((e["cb60"] - e["cbbase60"]).mean()),
                "cbxmed60": f((e["cb60"] - e["cbbase60"]).median()),
                "cbxwin60": f(((e["cb60"] - e["cbbase60"]).dropna() > 0).mean()),
                "big": f(e["big"].mean()), "bigbase": f(e["bigbase"].mean()), "loss": f(e["loss"].mean()), "lossbase": f(e["lossbase"].mean())})}


def main():
    q = panel()
    ev = events(q)
    split = pd.Timestamp(SPLIT)
    rng = [ev["date"].min().strftime("%Y-%m-%d"), ev["date"].max().strftime("%Y-%m-%d")]
    out, stats = [f"事件期間 {rng[0]} ~ {rng[1]}，前後段切在 {SPLIT}"], {}
    for key, name, kind, rule, _ in cbsig.SIGNALS:
        e = ev[ev["sig"] == key]
        a, b2 = e[e["date"] < split], e[e["date"] >= split]
        sa, sb, s_all = stat(a), stat(b2), stat(e)
        # 判定看 CB（他買的是 CB／CBAS）：CB 報酬分布很偏（少數大賺拉高平均），所以不看勝率，看
        #   做多：60 日 CB 超額平均 > 0，且大賺（≥ +20%）機率 ≥ 同期全部 CB 的 1.2 倍
        #   警訊：60 日 CB 超額平均 < 0，且大賠（≤ −10%）機率 ≥ 同期全部 CB 的 1.2 倍
        def good(x):
            if x["n60"] < 30 or x.get("cbx60") is None:
                return None
            if kind == "多":
                return x["cbx60"] > 0 and (x.get("big") or 0) >= 1.2 * (x.get("bigbase") or 1)
            return x["cbx60"] < 0 and (x.get("loss") or 0) >= 1.2 * (x.get("lossbase") or 1)
        ga, gb = good(sa), good(sb)
        ok = bool(ga and gb)
        yearly = {}
        for y, g in e.dropna(subset=["cb60"]).groupby(e["date"].dt.year):
            x = g["cb60"] - g["cbbase60"]
            yearly[str(y)] = {"n": int(len(g)), "cbx60": round(float(x.mean()), 4), "big": round(float(g["big"].mean()), 3),
                              "ex60": None if g["ex60"].isna().all() else round(float(g["ex60"].mean()), 4)}
        recent = e.sort_values("date").tail(8)
        ex = [{"date": r.date.strftime("%Y-%m-%d"), "code": r.code, "name": r.name, "ex60": None if pd.isna(r.ex60) else round(float(r.ex60), 4),
               "cb60": None if pd.isna(r.cb60) else round(float(r.cb60), 4),
               "cbx60": None if pd.isna(r.cb60) else round(float(r.cb60 - r.cbbase60), 4)} for r in recent.itertuples()]
        verdict = "通過" if ok else ("樣本不足" if ga is None or gb is None else ("只有一段有效" if ga or gb else "未通過"))
        stats[key] = {"all": s_all, "early": sa, "late": sb, "yearly": yearly, "verdict": verdict, "examples": ex}
        out.append(f"\n== {name}（{kind}）{verdict} ==  {rule}")
        fm = lambda x: "—" if x is None else f"{x:+.1%}"  # noqa: E731
        fw = lambda x: "—" if x is None else f"{x:.0%}"  # noqa: E731
        for lab, st_ in (("全部", s_all), ("前段", sa), ("後段", sb)):
            out.append(f"  {lab}: {st_['n']} 次  CB 60日 {fm(st_['cb60'])}（全部 CB {fm(st_['cbbase60'])}，超額 {fm(st_.get('cbx60'))}）"
                       f"｜大賺 {fw(st_.get('big'))} vs {fw(st_.get('bigbase'))}｜大賠 {fw(st_.get('loss'))} vs {fw(st_.get('lossbase'))}"
                       f"｜股票 60日超額 平均 {fm(st_['mean60'])}")
    # 基準：所有有發 CB 的標的股（每天每檔一次）之後 60 日超額的勝率與中位數；所有 CB 的 60 日報酬
    base = q[q["date"] >= pd.Timestamp(rng[0])].drop_duplicates(["date", "scode"]).dropna(subset=["ex60"])
    bstat = {"win60": round(float((base["ex60"] > 0).mean()), 4), "med60": round(float(base["ex60"].median()), 4),
             "mean60": round(float(base["ex60"].mean()), 4), "cb60": round(float(q["cb60"].mean()), 4)}
    out.append(f"\n基準（所有發 CB 的股票）：60日超額 勝率 {bstat['win60']:.0%} 中位 {bstat['med60']:+.1%} 平均 {bstat['mean60']:+.1%}")
    stats["_base"] = bstat
    print("\n".join(out))
    cbsig.save_stats(stats, rng, SPLIT)
    cbsig.run()
    return ev


if __name__ == "__main__":
    sys.exit(main() is None)
