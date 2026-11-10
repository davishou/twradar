"""期貨、選擇權三個策略的回測（2026-11-10）：python -m research.fo_bt <btdata 資料夾> [night|intraday|opt]

資料（tools/backfill_bt.py taifex／yahoo_intraday 產生，在 btdata 分支）：
  fut_TX_YYYY.csv      台指期每日行情（各月份、一般＋盤後時段）
  opt_TXO_YYYY.csv.gz  台指選擇權每日行情（一般時段、近月與次月、有成交或有未平倉）
  twii_60m.csv、twii_5m.csv  加權指數盤中 K（Yahoo；60 分約 3 年、5 分 60 天）

night    夜盤反轉：夜盤（前一天 15:00~當天 05:00）漲跌 → 當天日盤（08:45 開盤~13:45 收盤）反向做。2017/5 起。
         另看 2005 起「隔夜跳空 → 日盤」與「只抱隔夜／只抱日盤」的分解。
intraday 日內動能：第一個小時（含開盤跳空）的方向 → 13:00 進場做到收盤。用加權指數 60 分 K 近似（不是期貨）。
opt      選擇權賣方：到期前 N 個交易日用結算價賣價平跨式（或 ±% 價外勒式），抱到結算；另測買外側保護（鐵蝴蝶、鐵兀鷹）。
         成本每一腳 2 點。**用每日結算價、假設一定抱得到結算（沒算盤中保證金追繳／被強制平倉）**，裸賣的結果偏樂觀。
期貨成本：來回 3 點滑價＋期交稅 0.004%（手續費含在滑價裡）。報酬都以「契約價值」為分母（沒開槓桿）。
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ERAS = (("05~12", "2005", "2012-12-31"), ("13~19", "2013", "2019-12-31"), ("20~26", "2020", "2030"))
OUT = Path(__file__).parent / "out"


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", ""), errors="coerce")


def load_fut(folder):
    f = pd.concat([pd.read_csv(p, dtype=str) for p in sorted(glob.glob(f"{folder}/fut_TX_*.csv"))], ignore_index=True)
    f["contract"] = f["contract"].str.strip()
    f = f[f["contract"].str.fullmatch(r"\d{6}")]
    f["date"] = pd.to_datetime(f["date"])
    for c in ("open", "high", "low", "close", "volume", "settle", "oi"):
        f[c] = num(f[c])
    return f.dropna(subset=["close"]).drop_duplicates(["date", "contract", "session"])


def stat(r: pd.Series, per_year: float | None = None) -> str:
    r = r.dropna()
    if len(r) < 10:
        return f"n={len(r)}"
    yrs = max((r.index[-1] - r.index[0]).days / 365.25, 0.5)
    eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    t = r.mean() / r.std() * np.sqrt(len(r)) if r.std() > 0 else np.nan
    return (f"n={len(r)} 每筆 {r.mean() * 1e4:+.1f}bp 賺錢 {(r > 0).mean():.0%} t={t:.1f}｜年化 {cagr:+.1%} 回落 {mdd:+.0%}（"
            + "／".join(f"{(lambda s: (((1 + s).prod()) ** (365.25 / max((s.index[-1] - s.index[0]).days, 200)) - 1) if len(s) > 20 else float('nan'))(r[(r.index >= a) & (r.index <= b)]):+.0%}" for _, a, b in ERAS) + "）")


def day_night(f):
    """每天一列：近月（一般時段成交量最大的月份）的日盤開高低收，與同一月份的夜盤開收、前一交易日日盤收盤"""
    d = f[f["session"] == "一般"]
    idx = d.groupby("date")["volume"].idxmax()
    day = d.loc[idx].set_index("date")[["contract", "open", "high", "low", "close", "settle"]].sort_index()
    key = d.set_index(["date", "contract"])["close"]
    n = f[f["session"] == "盤後"].set_index(["date", "contract"])
    dates = day.index
    prev = pd.Series(dates, index=dates).shift(1)
    rows = []
    for dt, r in day.iterrows():
        pc = key.get((prev[dt], r["contract"]), np.nan) if pd.notna(prev[dt]) else np.nan
        no = nc = np.nan
        if (dt, r["contract"]) in n.index:
            no, nc = n.at[(dt, r["contract"]), "open"], n.at[(dt, r["contract"]), "close"]
        rows.append((dt, pc, no, nc))
    x = pd.DataFrame(rows, columns=["date", "prev_close", "n_open", "n_close"]).set_index("date")
    return day.join(x)


def do_night(folder, P):
    t = day_night(load_fut(folder))
    cost = lambda px: 3 / px + 0.00004  # noqa: E731
    t["day"] = t["close"] / t["open"] - 1
    t["gap"] = t["open"] / t["prev_close"] - 1                 # 前一天日盤收盤 → 今天日盤開盤（含夜盤）
    t["night"] = t["n_close"] / t["prev_close"] - 1            # 夜盤那一段
    t["open_gap"] = t["open"] / t["n_close"] - 1               # 夜盤收盤（05:00）→ 日盤開盤（08:45）
    c = cost(t["open"])
    P("===== 夜盤反轉／隔夜與日盤（台指期近月） =====")
    P(f"資料 {t.index[0].date()} ~ {t.index[-1].date()}，共 {len(t)} 天；有夜盤 {t['night'].notna().sum()} 天（{t['night'].first_valid_index().date() if t['night'].notna().any() else '—'} 起）")
    P("\n--- 1. 分解：只抱隔夜（日盤收盤→隔天日盤開盤） vs 只抱日盤（開盤→收盤），未扣成本／每天來回扣成本 ---")
    P("只抱隔夜  未扣 " + stat(t["gap"]))
    P("只抱隔夜  扣成本 " + stat(t["gap"] - c))
    P("只抱日盤  未扣 " + stat(t["day"]))
    P("只抱日盤  扣成本 " + stat(t["day"] - c))
    P("一直抱著  " + stat(t["close"].pct_change().where(t["contract"] == t["contract"].shift(1), t["close"] / t["prev_close"] - 1)))
    for name, col in (("夜盤漲跌（前一天日盤收盤→夜盤收盤，2017/5 起）", "night"), ("隔夜跳空（前一天日盤收盤→今天開盤，2005 起）", "gap")):
        s = t.dropna(subset=[col, "day"])
        P(f"\n--- 2. {name} 和當天日盤（開盤→收盤）的關係 ---")
        P(f"相關係數 {s[col].corr(s['day']):+.3f}（n={len(s)}）；分三段：" + "／".join(f"{s[(s.index >= a) & (s.index <= b)][col].corr(s[(s.index >= a) & (s.index <= b)]['day']):+.3f}" if ((s.index >= a) & (s.index <= b)).sum() > 50 else "—" for _, a, b in ERAS))
        bins = [-1, -0.015, -0.0075, -0.0025, 0.0025, 0.0075, 0.015, 1]
        labs = ["跌>1.5%", "跌0.75~1.5%", "跌0.25~0.75%", "±0.25%", "漲0.25~0.75%", "漲0.75~1.5%", "漲>1.5%"]
        for k, g in s.groupby(pd.cut(s[col], bins, labels=labs), observed=True):
            P(f"  {k:<12} n={len(g):>4} 日盤平均 {g['day'].mean() * 1e4:+6.1f}bp 中位 {g['day'].median() * 1e4:+6.1f}bp 上漲 {(g['day'] > 0).mean():.0%}")
        P("  反向做（漲了就開盤空、跌了就開盤多，收盤平倉，扣成本）：")
        for thr in (0, 0.0025, 0.005, 0.0075, 0.01, 0.015):
            pos = -np.sign(s[col]).where(s[col].abs() >= thr, 0)
            r = (pos * s["day"] - pos.abs() * cost(s["open"]))[pos != 0]
            P(f"    門檻 {thr:.2%}: " + stat(r))
        P("  順向做（對照）：")
        for thr in (0.005, 0.01):
            pos = np.sign(s[col]).where(s[col].abs() >= thr, 0)
            r = (pos * s["day"] - pos.abs() * cost(s["open"]))[pos != 0]
            P(f"    門檻 {thr:.2%}: " + stat(r))
        P("  只做一邊（門檻 0.75%）：")
        for lab, sgn in (("夜盤／隔夜大漲 → 開盤空", 1), ("夜盤／隔夜大跌 → 開盤多", -1)):
            m = (s[col] * sgn >= 0.0075)
            r = (-sgn * s["day"] - cost(s["open"]))[m]
            P(f"    {lab}: " + stat(r))


def do_intraday(folder, P):
    P("\n===== 日內動能（加權指數盤中 K 近似；實際要用台指期或 0050 下單） =====")
    for fn, first_n, last_n, lab in (("twii_60m.csv", 1, 1, "60 分 K：第一小時（09:00~10:00，含跳空）→ 最後半小時（13:00~13:30）"),
                                     ("twii_5m.csv", 6, 6, "5 分 K：第一個半小時（含跳空）→ 最後半小時")):
        p = Path(folder) / fn
        if not p.exists():
            P(f"{fn} 還沒有")
            continue
        k = pd.read_csv(p)
        k["t"] = pd.to_datetime(k["ts"], unit="s", utc=True).dt.tz_convert("Asia/Taipei")
        k = k[(k["t"].dt.hour >= 9) & ((k["t"].dt.hour < 13) | ((k["t"].dt.hour == 13) & (k["t"].dt.minute < 30)))]
        k["d"] = k["t"].dt.date
        rows = []
        prev_close = None
        for d, g in k.groupby("d"):
            g = g.sort_values("t")
            if len(g) < first_n + last_n + 1:
                prev_close = g["close"].iloc[-1]
                continue
            c_first = g["close"].iloc[first_n - 1]
            p_last = g["close"].iloc[-last_n - 1]
            cl = g["close"].iloc[-1]
            if prev_close:
                rows.append((pd.Timestamp(d), c_first / prev_close - 1, c_first / g["open"].iloc[0] - 1, p_last / c_first - 1, cl / p_last - 1, cl / g["open"].iloc[0] - 1))
            prev_close = cl
        x = pd.DataFrame(rows, columns=["date", "first", "first_nogap", "mid", "last", "day"]).set_index("date")
        P(f"\n--- {lab}：{x.index[0].date()} ~ {x.index[-1].date()}，{len(x)} 天 ---")
        P(f"第一段（含跳空）和最後半小時的相關 {x['first'].corr(x['last']):+.3f}；不含跳空 {x['first_nogap'].corr(x['last']):+.3f}；中段和最後半小時 {x['mid'].corr(x['last']):+.3f}")
        cost = 0.0003                                               # 期貨來回約 0.02~0.03%
        for nm, sig in (("跟第一段同方向", np.sign(x["first"])), ("第一段和中段同方向才做", np.sign(x["first"]).where(np.sign(x["first"]) == np.sign(x["mid"]), 0)),
                        ("只做多（第一段上漲）", (x["first"] > 0).astype(float)), ("只做空（第一段下跌）", -(x["first"] < 0).astype(float)),
                        ("第一段 |漲跌| ≥0.5% 才做", np.sign(x["first"]).where(x["first"].abs() >= 0.005, 0)), ("對照：每天最後半小時都做多", pd.Series(1.0, index=x.index))):
            r = (sig * x["last"])[sig != 0]
            P(f"  {nm:<16} 未扣成本 {stat(r)}")
            P(f"  {'':<16} 扣成本   {stat(r - cost)}")


# ------------------------------------------------------------------ 選擇權賣方

def load_opt(folder):
    o = pd.concat([pd.read_csv(p, dtype=str) for p in sorted(glob.glob(f"{folder}/opt_TXO_*.csv.gz"))], ignore_index=True)
    o["date"] = pd.to_datetime(o["date"])
    o["contract"] = o["contract"].str.strip()
    for c in ("strike", "settle", "close", "volume", "oi", "bid", "ask"):
        o[c] = num(o[c])
    o["px"] = o["settle"].where(o["settle"] > 0, o["close"])
    return o.dropna(subset=["strike"])


def build_trades(o, fut, ns=(1, 3, 5, 10, 20), leg_cost=2.0):
    days = np.array(sorted(o["date"].unique()))
    di = {d: i for i, d in enumerate(days)}
    last = o.groupby("contract")["date"].max()
    first = o.groupby("contract")["date"].min()
    end = days[-1]
    fs = fut[fut["session"] == "一般"].set_index(["date", "contract"])["settle"]
    by = {k: g for k, g in o.groupby(["contract", "date"])}
    out = []
    for con, E in last.items():
        if E >= end - np.timedelta64(3, "D"):
            continue                                                  # 還沒到期
        ge = by[(con, E)]
        if (ge["settle"] > 0).mean() > 0.2:
            continue                                                  # 最後一天還有結算價＝不是到期日（資料缺口）
        # 最後結算價：到期日的結算價欄是 0，用到期日有成交、接近價平的價內選擇權收盤價反推（買權：履約價＋權利金；賣權：履約價−權利金）
        gv = ge[(ge["volume"] > 0) & (ge["close"] >= 3)]
        est = pd.concat([gv[gv["cp"] == "C"].assign(e=lambda d: d["strike"] + d["close"]), gv[gv["cp"] == "P"].assign(e=lambda d: d["strike"] - d["close"])])
        est = est.nsmallest(6, "close")["e"]
        fsp_o = est.median() if len(est) >= 2 else np.nan
        fsp_f = np.nan
        fsp = fsp_o
        if not np.isfinite(fsp):
            continue
        monthly = con.isdigit()
        for n in ns:
            i = di[E] - n
            if i < 0 or days[i] < first[con]:
                continue
            g = by.get((con, days[i]))
            if g is None:
                continue
            C, Pp = g[g["cp"] == "C"].set_index("strike")["px"], g[g["cp"] == "P"].set_index("strike")["px"]
            both = pd.concat([C.rename("c"), Pp.rename("p")], axis=1).dropna()
            both = both[(both["c"] > 0) & (both["p"] > 0)]
            if len(both) < 5:
                continue
            k0 = (both["c"] - both["p"]).abs().idxmin()
            F = k0 + both.at[k0, "c"] - both.at[k0, "p"]
            prem = both.at[k0, "c"] + both.at[k0, "p"]

            def px_at(series, k_target, side):
                ks = series.index.values
                ks = ks[ks >= k_target] if side > 0 else ks[ks <= k_target]
                if len(ks) == 0:
                    return np.nan, np.nan
                k = ks.min() if side > 0 else ks.max()
                return k, series[k]
            pay = lambda kc, kp: max(fsp - kc, 0) + max(kp - fsp, 0)  # noqa: E731
            rec = {"contract": con, "monthly": monthly, "n": n, "entry": pd.Timestamp(days[i]), "expiry": pd.Timestamp(E), "F": F, "fsp": fsp,
                   "fsp_gap": est.max() - est.min(),
                   "prem": prem, "move": abs(fsp - k0), "straddle": prem - abs(fsp - k0) - 2 * leg_cost}
            w = 0.03 if n <= 5 else 0.05
            kc, pc = px_at(C[C > 0], k0 + w * F, 1)
            kp, pp = px_at(Pp[Pp > 0], k0 - w * F, -1)
            if np.isfinite(kc) and np.isfinite(kp):
                rec["butterfly"] = rec["straddle"] - (pc + pp) - 2 * leg_cost + pay(kc, kp)
                rec["bf_risk"] = max(kc - k0, k0 - kp) - (prem - pc - pp)
            y = 0.02 if n <= 5 else 0.04
            sc, spc = px_at(C[C > 0], F * (1 + y), 1)
            sp, spp = px_at(Pp[Pp > 0], F * (1 - y), -1)
            if np.isfinite(sc) and np.isfinite(sp):
                rec["strangle"] = spc + spp - pay(sc, sp) - 2 * leg_cost
                rec["strangle_prem"] = spc + spp
                wc, wpc = px_at(C[C > 0], sc + 0.02 * F, 1)
                wp, wpp = px_at(Pp[Pp > 0], sp - 0.02 * F, -1)
                if np.isfinite(wc) and np.isfinite(wp):
                    rec["condor"] = rec["strangle"] - (wpc + wpp) - 2 * leg_cost + pay(wc, wp)
                    rec["cd_risk"] = max(wc - sc, sp - wp) - (spc + spp - wpc - wpp)
            out.append(rec)
    return pd.DataFrame(out)


def opt_line(t, col, risk=None):
    x = t.dropna(subset=[col]).sort_values("expiry")
    if len(x) < 20:
        return f"n={len(x)}"
    r = (x[col] / x["F"]).set_axis(x["expiry"])                       # 以契約價值為分母
    eq = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    w, l = x.loc[x[col] > 0, col], x.loc[x[col] <= 0, col]
    s = (f"n={len(x):>4} 每筆 {x[col].mean():+7.1f} 點（{r.mean():+.2%}）賺錢 {(x[col] > 0).mean():.0%} 平均賺 {w.mean():.0f}／平均賠 {l.mean():.0f} 點 "
         f"最慘 {x[col].min():.0f} 點（{(x[col] / x['F']).min():+.1%}，{x.loc[x[col].idxmin(), 'expiry'].date()}）t={r.mean() / r.std() * np.sqrt(len(r)):.1f}"
         f"｜無槓桿年化 {eq.iloc[-1] ** (1 / yrs) - 1:+.1%} 回落 {(eq / eq.cummax() - 1).min():+.1%}｜三段每筆 "
         + "／".join(f"{x[(x['expiry'] >= a) & (x['expiry'] <= b)][col].mean():+.0f}" for _, a, b in ERAS))
    if risk and risk in x:
        rr = (x[col] / x[risk].clip(lower=1)).replace([np.inf, -np.inf], np.nan).dropna()
        s += f"｜每筆÷最大風險 {rr.mean():+.1%}"
    return s


def do_opt(folder, P):
    o, fut = load_opt(folder), load_fut(folder)
    t = build_trades(o, fut)
    OUT.mkdir(exist_ok=True)
    t.to_csv(OUT / "fo_opt_trades.csv", index=False)
    P("\n===== 選擇權賣方（台指選擇權，結算價進場、抱到結算，每腳成本 2 點） =====")
    P(f"資料 {o['date'].min().date()} ~ {o['date'].max().date()}；到期契約 {t['contract'].nunique()} 個（月選 {t[t['monthly']]['contract'].nunique()}、週選 {t[~t['monthly']]['contract'].nunique()}）")
    g = t.drop_duplicates("contract").dropna(subset=["fsp_gap"])
    P(f"檢查：最後結算價是用到期日價內選擇權收盤價反推的；同一契約各履約價反推值的差距中位 {g['fsp_gap'].median():.1f} 點、九成在 {g['fsp_gap'].quantile(0.9):.0f} 點內、最大 {g['fsp_gap'].max():.0f} 點")
    for lab, m in (("月選（每月一次）", t["monthly"]), ("週選（每週，2012/11 起）", ~t["monthly"])):
        for n in sorted(t["n"].unique()):
            x = t[m & (t["n"] == n)]
            if len(x) < 20:
                continue
            P(f"\n--- {lab}，到期前 {n} 個交易日進場（平均權利金 {x['prem'].mean():.0f} 點＝指數的 {(x['prem'] / x['F']).mean():.2%}；到期時平均離履約價 {(x['move'] / x['F']).mean():.2%}） ---")
            P("  裸賣價平跨式          " + opt_line(x, "straddle"))
            P("  鐵蝴蝶（買外側保護）  " + opt_line(x, "butterfly", "bf_risk"))
            P("  裸賣價外勒式          " + opt_line(x, "strangle"))
            P("  鐵兀鷹（買外側保護）  " + opt_line(x, "condor", "cd_risk"))
    P("\n--- 每年合計（點數；月選到期前 20 日的裸賣跨式／鐵蝴蝶；週選到期前 5 日的裸賣跨式／鐵蝴蝶） ---")
    a = t[t["monthly"] & (t["n"] == 20)].groupby(t["expiry"].dt.year)[["straddle", "butterfly"]].sum()
    b = t[~t["monthly"] & (t["n"] == 5)].groupby(t["expiry"].dt.year)[["straddle", "butterfly"]].sum()
    P(pd.concat([a.add_prefix("月選_"), b.add_prefix("週選_")], axis=1).round(0).to_string())
    P("\n--- 權利金高低（隱含波動高低）和裸賣跨式的結果：依『權利金÷指數』分三等分 ---")
    for lab, m in (("月選 到期前 20 日", t["monthly"] & (t["n"] == 20)), ("週選 到期前 5 日", ~t["monthly"] & (t["n"] == 5)), ("月選 到期前 5 日", t["monthly"] & (t["n"] == 5))):
        x = t[m].dropna(subset=["straddle"]).copy()
        if len(x) < 60:
            continue
        x["q"] = pd.qcut(x["prem"] / x["F"], 3, labels=["低", "中", "高"])
        P(f"  {lab}：" + "　".join(f"{k} 每筆 {g_['straddle'].mean():+.0f} 點（賺錢 {(g_['straddle'] > 0).mean():.0%}、最慘 {g_['straddle'].min():.0f}）" for k, g_ in x.groupby("q", observed=True)))
    P("\n--- 最慘的 8 筆（月選到期前 20 日裸賣跨式） ---")
    x = t[t["monthly"] & (t["n"] == 20)].nsmallest(8, "straddle")
    for r in x.itertuples():
        P(f"  {r.entry.date()} 進場、{r.expiry.date()} 結算：收 {r.prem:.0f} 點，指數走了 {r.move:.0f} 點（{r.move / r.F:.1%}），賠 {-r.straddle:.0f} 點＝{-r.straddle * 50:,.0f} 元／口；同期鐵蝴蝶 {r.butterfly:+.0f} 點")


def main(argv):
    folder = argv[0]
    what = argv[1:] or ["night", "intraday", "opt"]
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    for w in what:
        {"night": do_night, "intraday": do_intraday, "opt": do_opt}[w](folder, P)
    OUT.mkdir(exist_ok=True)
    (OUT / f"fo_bt_{'_'.join(what)}.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
