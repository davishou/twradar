"""標借：鎖單（現股買進＋融券賣出）後把現股拿去出借賺標借費。python -m research.lend_bt [lend.csv]

資料：tools/backfill_bt.py lend（證交所 BFIB8U 2005 起、櫃買 margin/lend）。每天每檔有：最高標借單價、最低／最高得標單價（元／股）。
做法（避免偷看）：某檔第一天出現標借（早上 8:30 公布）→ 當天收盤鎖單 → T+2 交割後（第 3 天起）每天掛單出借，
標借停止的隔天收盤平倉（賣現股、回補融券）。
收入：每天的得標單價 ×（1 − 券商收 10%）。保守＝最低得標價（一定借得出去），樂觀＝最高得標價、中間＝兩者平均。
成本：現股買賣（手續費＋證交稅）＋融券賣出（手續費＋證交稅＋融券手續費 0.08%）＋回補手續費，四邊各再扣滑價 0.1%（收盤價成交）。
報酬分母：股價（每股）；實際占用資金約 1.9 倍（現股＋融券保證金 9 成），另列。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research import event_bt as eb

COST = (0.001425 + 0.001) + (0.001425 + 0.003 + 0.001) + (0.001425 + 0.003 + 0.0008 + 0.001) + (0.001425 + 0.001)


def _f(x):
    x = str(x).replace(",", "").strip()
    try:
        return float(x)
    except ValueError:
        return np.nan


def load(path):
    df = pd.read_csv(path, dtype=str)
    out = []
    tw = df[df["market"] == "TWSE"].dropna(subset=["最高得標單價"]) if "最高得標單價" in df else df.iloc[0:0]
    for r in tw.itertuples(index=False):
        d = str(getattr(r, "標借日期")).replace(".", "/")
        y, m, dd = d.split("/")
        out.append({"date": pd.Timestamp(int(y) + 1911, int(m), int(dd)), "code": getattr(r, "證券代號"), "market": "TWSE",
                    "need": _f(getattr(r, "標借數量")), "cap": _f(getattr(r, "最高標借單價")),
                    "lo": _f(getattr(r, "最低得標單價")), "hi": _f(getattr(r, "最高得標單價"))})
    tp = df[df["market"] == "TPEX"] if "標定單價" in df else df.iloc[0:0]
    for r in tp.itertuples(index=False):
        d = str(getattr(r, "標借日期"))
        y, m, dd = d.split("/")
        rng = str(getattr(r, "標定單價"))
        lo, hi = (rng.split("~") + [""])[:2]
        f = _f
        out.append({"date": pd.Timestamp(int(y) + 1911, int(m), int(dd)), "code": getattr(r, "股票代號"), "market": "TPEX",
                    "need": f(str(getattr(r, "標借張數"))), "cap": f(str(getattr(r, "最高標借單價"))), "lo": f(lo), "hi": f(hi)})
    x = pd.DataFrame(out)
    # 同一天同一檔可能有好幾家證金公司：得標價取最低的最低、最高的最高
    return x.groupby(["date", "code", "market"], as_index=False).agg(need=("need", "sum"), cap=("cap", "max"), lo=("lo", "min"), hi=("hi", "max"))


def main(argv):
    path = Path(argv[0]) if argv else Path("/tmp/btdata/lend.csv")
    L = load(path)
    out = [f"標借紀錄 {len(L)} 檔日（上市 {int((L.market=='TWSE').sum())}、上櫃 {int((L.market=='TPEX').sum())}）；"
           f"{L.date.min().date()}~{L.date.max().date()}；有得標價的 {int(L.lo.notna().sum())}"]
    M = eb.mats()
    days, C = M["adj"].index, M["close"]
    di = {d: i for i, d in enumerate(days)}
    L = L[L.date.isin(di) & L.code.isin(C.columns)].copy()
    L["i"] = L.date.map(di)
    L["px"] = [C.iat[i, C.columns.get_loc(c)] for i, c in zip(L.i, L.code)]
    rows = []
    for code, g in L.sort_values("i").groupby("code"):
        ii = g.i.to_numpy()
        brk = np.where(np.diff(ii) > 3)[0]            # 中斷 3 個交易日以上算新的一段
        for seg in np.split(np.arange(len(g)), brk + 1):
            s = g.iloc[seg]
            i0, i1 = int(s.i.iloc[0]), int(s.i.iloc[-1])
            px0 = C.iat[i0, C.columns.get_loc(code)]
            if not np.isfinite(px0) or px0 <= 0:
                continue
            lendable = s[s.i >= i0 + 2]              # T+2 交割後才能出借
            rev = {k: (lendable[k].fillna(0) * 0.9).sum() / px0 for k in ("lo", "hi")}
            rev["mid"] = (rev["lo"] + rev["hi"]) / 2
            first = s.iloc[0]
            rows.append({"code": code, "market": first.market, "start": days[i0].date(), "days": int(i1 - i0 + 1),
                         "lend_days": len(lendable), "day1_hi_pct": first.hi / px0 if first.hi == first.hi else np.nan,
                         "day1_cap_pct": first.cap / px0, "need0": first.need,
                         **{f"rev_{k}": v for k, v in rev.items()}})
    E = pd.DataFrame(rows)
    E.to_csv(eb.pf.OUT / "lend_episodes.csv", index=False)
    out.append(f"標借段落 {len(E)} 段；平均持續 {E.days.mean():.1f} 個交易日（中位 {E.days.median():.0f}）；鎖單成本約 {COST:.2%}（占股價）")

    def stat(e, nm):
        if len(e) == 0:
            return f"{nm}：0 段"
        net = {k: e[f"rev_{k}"] - COST for k in ("lo", "mid", "hi")}
        return (f"{nm}：{len(e)} 段｜收入（占股價）保守 {e.rev_lo.mean():+.2%} 中間 {e.rev_mid.mean():+.2%} 樂觀 {e.rev_hi.mean():+.2%}｜"
                f"扣成本淨賺：保守 平均 {net['lo'].mean():+.2%} 賺錢 {(net['lo'] > 0).mean():.0%}；中間 平均 {net['mid'].mean():+.2%} "
                f"賺錢 {(net['mid'] > 0).mean():.0%}；樂觀 平均 {net['hi'].mean():+.2%} 賺錢 {(net['hi'] > 0).mean():.0%}｜"
                f"占用資金約 1.9 倍，換算資金報酬（中間）{net['mid'].mean() / 1.9:+.2%}／段")
    out.append(stat(E, "全部"))
    for lo, hi in ((0, 0.001), (0.001, 0.005), (0.005, 0.02), (0.02, 1)):
        m = (E.day1_hi_pct >= lo) & (E.day1_hi_pct < hi)
        out.append(stat(E[m], f"第一天最高得標價占股價 {lo:.1%}~{hi:.1%}"))
    for yr0, yr1 in ((2005, 2012), (2013, 2019), (2020, 2026)):
        m = pd.to_datetime(E.start).dt.year.between(yr0, yr1)
        out.append(stat(E[m], f"{yr0}~{yr1}"))
    for mk in ("TWSE", "TPEX"):
        out.append(stat(E[E.market == mk], mk))
    # 年度化：每年所有段落的中間淨利加總 ÷ 同時最多段數（粗估一個人每年能賺多少）
    E["year"] = pd.to_datetime(E.start).dt.year
    E["net_mid"] = E.rev_mid - COST
    yr = E.groupby("year").agg(n=("code", "size"), net=("net_mid", "mean"), win=("net_mid", lambda x: (x > 0).mean()))
    out.append("每年：" + "  ".join(f"{y} {r.n}段 平均{r.net:+.1%} 賺錢{r.win:.0%}" for y, r in yr.iterrows()))
    print("\n".join(out))
    (eb.pf.OUT / "lend_bt.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
