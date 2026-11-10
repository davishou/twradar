"""庫藏股宣告事件回測（2026-11-10）：python -m research.treasury_bt [btdata 資料夾]

資料：
  - 近半年：data/state/treasury_raw.json（每日公告累積，約 2026-05 起）
  - 歷史：btdata 分支的 treasury_YYYY.csv（tools/backfill_bt.py treasury 起年 迄年 掃觀測站重大訊息），放在 <資料夾>/treasury/ 或 <資料夾>/
只取「董事會決議買回」那一則（排除執行完畢／期間屆滿／更正／變更）。從內文抓：買回目的、預定買回占已發行股份比率、
買回價格區間上限、過去執行率。
進場：公告後第一個交易日收盤買（公告多在收盤後；這天一字漲停不買），持有 5／20／60 日。
先看事件平均（贏全市場幾點、賺錢比例），再做資金曲線（20 份、滑價 0.3%、成交 ≥3,000 萬）。
分組：買回比率、目的（維護股東權益＝註銷／轉讓員工）、公告前 20 日跌幅、股價對買回上限的位置、大盤前 60 日漲跌、規模。
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from pipeline import config
from research import portfolio as pf
from research import squeeze as sq

EXCL = re.compile(r"執行完畢|期間屆滿|屆滿|更正|補充|變更|調整|註銷|減資|轉讓|實際買回|買回情形|未執行|澄清|說明")


def load(folder: str | None) -> pd.DataFrame:
    rows = []
    raw = json.loads((config.STATE_DIR / "treasury_raw.json").read_text("utf-8"))
    rows += [v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)]
    if folder:
        for p in sorted(glob.glob(f"{folder}/treasury/treasury_*.csv") + glob.glob(f"{folder}/treasury_*.csv")):
            rows += list(csv.DictReader(open(p, encoding="utf-8")))
    df = pd.DataFrame(rows)
    df = df[df["code"].astype(str).str.fullmatch(r"\d{4}")]
    return df.drop_duplicates(["date", "code", "subject"]).reset_index(drop=True)


def parse(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for r in df.itertuples():
        subj = re.sub(r"\s+", "", str(r.subject))
        body = re.sub(r"[ \t\r]+", "", str(r.body))
        if not re.search(r"買回", subj) or not re.search(r"庫藏|本公司股份|買回股份", subj + body[:200]):
            continue
        if "董事會決議日期" not in body or "預定買回之期間" not in body:
            continue
        if EXCL.search(subj):
            continue
        m = re.search(r"占公司已發行股份總數之比率\(%\)[:：]?([\d.]+)", body)
        hi = re.search(r"買回區間價格\(元\)[:：]?([\d,.]+)[~～至\-]+([\d,.]+)", body)
        pur = re.search(r"買回股份目的[:：]?(.{0,30})", body)
        purpose = pur.group(1) if pur else ""
        kind = "維護權益（註銷）" if re.search(r"維護|權益|信用", purpose) else ("轉讓員工" if "員工" in purpose else "其他")
        ex = [float(x) for x in re.findall(r"執行情形\(實際已買回股數占預定買回股數%\)[:：]?([\d.]+)", body)]
        hh, mm = (str(r.time).split(":") + ["0"])[:2] if isinstance(r.time, str) and ":" in r.time else ("17", "0")
        out.append({"code": r.code, "ann": pd.Timestamp(r.date), "hour": int(hh) + int(mm) / 60,
                    "pct": float(m.group(1)) if m else np.nan,
                    "lo": float(hi.group(1).replace(",", "")) if hi else np.nan, "hi": float(hi.group(2).replace(",", "")) if hi else np.nan,
                    "kind": kind, "past_exec": float(np.mean(ex)) if ex else np.nan, "n_past": len(ex)})
    return pd.DataFrame(out)


def attach(ev: pd.DataFrame) -> pd.DataFrame:
    f = sq.feats()
    px, ew = f["px"], f["ew"]
    days = px.index
    q = bt.load_quotes()[["date", "code", "close", "high", "low", "is_lu"]]
    raw_close = q.pivot(index="date", columns="code", values="close")
    lock = q[q["is_lu"] & (q["high"] <= q["low"] + 1e-9)]
    locked = set(zip(lock["date"], lock["code"]))
    # 盤中（13:30 前）公告：當天收盤就能買；收盤後公告：下一個交易日收盤
    i_after = days.searchsorted(ev["ann"].values, side="right")
    i_same = days.searchsorted(ev["ann"].values, side="left")
    intraday = (ev["hour"].to_numpy() < 13.4) & (i_same < len(days)) & (days[np.minimum(i_same, len(days) - 1)] == ev["ann"].values)
    i0 = np.where(intraday, i_same, i_after)
    ev = ev[i0 < len(days)].copy()
    i0 = i0[i0 < len(days)]
    ev["i"], ev["date"] = i0, days[i0]
    ev = ev[ev["code"].isin(px.columns)]
    ev = ev[[(d, c) not in locked for d, c in zip(ev["date"], ev["code"])]].copy()
    a, e = px.to_numpy(), ew.to_numpy()
    col = {c: k for k, c in enumerate(px.columns)}
    n = len(days)
    pff = px.ffill(limit=60).to_numpy()
    for h in (5, 20, 60):
        ret, xs = [], []
        for i, c in zip(ev["i"], ev["code"]):
            j = col[c]
            if i + h >= n or not np.isfinite(a[i, j]):
                ret.append(np.nan), xs.append(np.nan)
                continue
            rr = pff[i + h, j] / a[i, j] - 1
            ret.append(rr), xs.append(rr - (e[i + h] / e[i] - 1))
        ev[f"r{h}"], ev[f"x{h}"] = ret, xs
    pre = lambda m, k=1: [m.iat[max(i - k, 0), col[c]] for i, c in zip(ev["i"], ev["code"])]  # noqa: E731
    ev["pre20"] = pre(f["ret20"])
    ev["near"] = pre(f["near"])
    ev["liq"] = pre(f["val20"])
    ev["px_raw"] = [raw_close.iat[max(raw_close.index.searchsorted(d) - 1, 0), raw_close.columns.get_loc(c)] if c in raw_close.columns else np.nan
                    for d, c in zip(ev["date"], ev["code"])]
    ev["to_hi"] = ev["px_raw"] / ev["hi"]
    mk60 = ew / ew.shift(60) - 1
    ev["mk60"] = [mk60.iat[max(i - 1, 0)] for i in ev["i"]]
    return ev


def line(s, name):
    def one(h):
        x = s[f"x{h}"].dropna()
        r = s[f"r{h}"].dropna()
        if len(x) < 5:
            return f"{h}日 —"
        t = x.mean() / (x.std() / np.sqrt(len(x))) if x.std() > 0 else np.nan
        return f"{h}日 {r.mean():+.1%}（贏全市場 {x.mean():+.1%}、t={t:.1f}、贏 {(x > 0).mean():.0%}、n={len(x)}）"
    return f"{name:<26} " + "｜".join(one(h) for h in (5, 20, 60))


def main(argv):
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    folder = argv[0] if argv else None
    raw = load(folder)
    ev = attach(parse(raw))
    ev = ev[ev["liq"] >= 3e7]
    P(f"庫藏股『董事會決議買回』公告：{len(ev)} 筆（{ev['ann'].min().date()} ~ {ev['ann'].max().date()}；成交 ≥3,000 萬），手續費折數 {pf.FEE_DISC:g}")
    P("各年筆數：" + "　".join(f"{y}:{n}" for y, n in ev.groupby(ev["ann"].dt.year).size().items()))
    P("（報酬未扣成本；贏全市場＝減同期全市場等權平均）")
    P(line(ev, "全部"))
    inf = np.inf
    groups = [
        ("買回占股本比率", pd.cut(ev["pct"], [0, 1, 2, 3, 5, inf], labels=["<1%", "1~2%", "2~3%", "3~5%", "≥5%"], right=False)),
        ("目的", ev["kind"]),
        ("公告前 20 日漲跌", pd.cut(ev["pre20"], [-inf, -0.2, -0.1, 0, inf], labels=["跌>20%", "跌10~20%", "跌0~10%", "上漲"], right=False)),
        ("離一年高點", pd.cut(ev["near"], [0, 0.6, 0.8, 0.9, inf], labels=["跌>40%", "跌20~40%", "跌10~20%", "跌<10%"], right=False)),
        ("股價÷買回價上限", pd.cut(ev["to_hi"], [0, 0.6, 0.75, 0.9, inf], labels=["<0.6", "0.6~0.75", "0.75~0.9", "≥0.9"], right=False)),
        ("大盤（等權）前 60 日", pd.cut(ev["mk60"], [-inf, -0.1, 0, 0.1, inf], labels=["跌>10%", "跌0~10%", "漲0~10%", "漲>10%"], right=False)),
        ("20 日均成交", pd.cut(ev["liq"], [0, 1e8, 3e8, 1e9, inf], labels=["0.3~1億", "1~3億", "3~10億", "≥10億"], right=False)),
        ("過去執行率", pd.cut(ev["past_exec"], [0, 50, 90, inf], labels=["<50%", "50~90%", "≥90%"], right=False)),
        ("時期", pd.cut(ev["ann"].dt.year, [0, 2012, 2019, 2100], labels=["05~12", "13~19", "20~26"])),
    ]
    for name, g in groups:
        P(f"\n=== {name} ===")
        for k, s in ev.groupby(g, observed=True):
            P(line(s, str(k)))
    if (ev["ann"].max() - ev["ann"].min()).days > 700:
        P("\n=== 資金曲線（隔日收盤買、20 份、每邊滑價 0.3%、同一檔在手上不重複買） ===")
        start = str(max(ev["date"].min(), pd.Timestamp("2005-03-01")).date())
        sets = [("全部", ev), ("買回 ≥3%", ev[ev["pct"] >= 3]), ("買回 ≥3%＋公告前 20 日下跌", ev[(ev["pct"] >= 3) & (ev["pre20"] < 0)]),
                ("維護權益（註銷）", ev[ev["kind"].str.startswith("維護")]), ("大盤前 60 日下跌", ev[ev["mk60"] < 0]),
                ("買回 ≥2%＋大盤前 60 日下跌", ev[(ev["pct"] >= 2) & (ev["mk60"] < 0)])]
        for nm, s in sets:
            e = s.assign(score=s["pct"].fillna(0))[["code", "date", "score"]]
            for hold in (20, 60):
                res = pf.simulate(e, hold, 20, start=start, slip=0.003, skip_held=True)
                P(pf.fmt(res, nm))
                if hold == 60:
                    P("     每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
    else:
        P("\n（資料不到兩年，不做資金曲線；等歷史公告回補完再跑）")
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / "treasury_bt.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
