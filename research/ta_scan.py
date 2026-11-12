"""技術指標全面測試（2026-11-10）：python -m research.ta_scan [ic|lift|bt|rev]（不給參數＝全部）

問題：常見技術指標裡，哪些真的有用？分四種看法（全部只用當天收盤以前的資料，隔日收盤進場）：
  ic   連續型指標和之後 20／60 日報酬的排名相關（每個取樣日橫斷面 Spearman，取平均與 t 值，分三段）
       —— 正＝數值越高之後越漲；|t|>3 且三段同號才算穩。
  lift 指標狀態／訊號下的飆股機率（60 日內曾漲 ≥50%）、重摔機率（曾跌 ≤−25%）、60 日中位報酬、贏全市場
  bt   訊號單獨做的資金曲線（訊號隔日收盤買、20 份、持有 60 日、同天太多挑最接近一年高點）
  rev  加在營收策略上：基準名單裡只留「進場前一天符合」的，或把排序換成該指標
共同：成交 ≥1 億（lift／ic 用 ≥3,000 萬）、排除營建金融、每邊滑價 0.3%、手續費 FEE_DISC。

指標：均線（站上 20／60／200 日線、黃金交叉、多頭排列）、乖離、RSI、KD、MACD、布林 %b、唐奇安新高新低、
      ADX／DMI、量（量比、OBV 創高、價漲量增）、動能（20／60／120／250 日、12-1）、相對強度排名、跳空、長紅、波動度。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import exit_rules as ex
from research import fin_signals as fs
from research import portfolio as pf
from research import squeeze as sq
from research.robust_check import excl_mask

FWD, STEP = 60, 5
_I = None


def indicators() -> tuple[dict, dict, dict]:
    """回傳（連續型, 狀態型, 事件型）三個 dict，值都是 日期×代號 矩陣"""
    global _I
    if _I is not None:
        return _I
    f = sq.feats()
    px, r = f["px"], f["r"].astype("float32")
    h, l, o, V = px * f["hc"], px * f["lc"], px * f["oc"], f["vol"]     # 還原後的高、低、開；成交量
    E32 = lambda m, **kw: m.ewm(**kw).mean().astype("float32")  # noqa: E731
    ma = {n: px.rolling(n, min_periods=int(n * 0.8)).mean() for n in (5, 10, 20, 60, 120, 200)}
    cont, state, event = {}, {}, {}
    # --- 動能／相對強度
    for n in (20, 60, 120, 250):
        cont[f"前{n}日漲幅"] = px / px.shift(n) - 1
    cont["12-1 動能（前250日扣掉最近20日）"] = px.shift(20) / px.shift(250) - 1
    cont["離一年高點（越高越近）"] = f["near"]
    rs = cont["前120日漲幅"].rank(axis=1, pct=True)
    cont["相對強度排名（120日）"] = rs
    # --- 均線
    for n in (20, 60, 200):
        cont[f"乖離{n}（收盤÷{n}日線−1）"] = px / ma[n] - 1
        state[f"站上{n}日線"] = px > ma[n]
    state["多頭排列 5>10>20>60"] = (ma[5] > ma[10]) & (ma[10] > ma[20]) & (ma[20] > ma[60])
    state["空頭排列 5<10<20<60"] = (ma[5] < ma[10]) & (ma[10] < ma[20]) & (ma[20] < ma[60])
    state["60日線上揚"] = ma[60] > ma[60].shift(20)

    def cross(a, b):
        if np.isscalar(b):
            return (a > b) & (a.shift(1) <= b)
        return (a > b) & (a.shift(1) <= b.shift(1))
    event["5/20 黃金交叉"] = cross(ma[5], ma[20])
    event["20/60 黃金交叉"] = cross(ma[20], ma[60])
    event["20/60 死亡交叉（對照）"] = cross(ma[60], ma[20])
    event["站上200日線（突破年線）"] = cross(px, ma[200])
    # --- RSI14（Wilder）
    up, dn = r.clip(lower=0), (-r).clip(lower=0)
    rsi = 100 - 100 / (1 + E32(up, alpha=1 / 14, min_periods=14) / E32(dn, alpha=1 / 14, min_periods=14))
    cont["RSI14"] = rsi
    event["RSI 跌破30後回到30上（超賣反彈）"] = cross(rsi, 30.0)
    event["RSI 突破70（強勢）"] = cross(rsi, 70.0)
    # --- KD(9,3,3)
    hh, ll = h.rolling(9, min_periods=9).max(), l.rolling(9, min_periods=9).min()
    rsv = ((px - ll) / (hh - ll) * 100).where(hh > ll)
    K = E32(rsv, alpha=1 / 3, min_periods=3)
    D = E32(K, alpha=1 / 3, min_periods=3)
    cont["KD 的 K 值"] = K
    kx = cross(K, D)
    event["KD 黃金交叉（全部）"] = kx
    event["KD 低檔黃金交叉（K<20）"] = kx & (K.shift(1) < 20)
    event["KD 高檔黃金交叉（K>80）"] = kx & (K > 80)
    # --- MACD(12,26,9)
    dif = E32(px, span=12, min_periods=26) - E32(px, span=26, min_periods=26)
    dea = E32(dif, span=9, min_periods=9)
    cont["MACD 柱狀體÷股價"] = (dif - dea) / px
    state["MACD DIF>0"] = dif > 0
    event["MACD 黃金交叉（全部）"] = cross(dif, dea)
    event["MACD 零軸上黃金交叉"] = cross(dif, dea) & (dif > 0)
    event["MACD 零軸下黃金交叉"] = cross(dif, dea) & (dif < 0)
    # --- 布林
    sd = px.rolling(20, min_periods=15).std()
    pb = (px - (ma[20] - 2 * sd)) / (4 * sd)
    cont["布林 %b"] = pb.where(sd > 0)
    cont["布林寬度排名（越小越收縮）"] = f["bbw_pct"]
    event["收盤突破布林上軌"] = cross(pb, 1.0)
    event["跌破布林下軌後站回"] = cross(pb, 0.0)
    # --- 唐奇安
    for n in (20, 60, 120, 250):
        event[f"創{n}日新高（前一天不是）"] = (px >= px.rolling(n, min_periods=int(n * 0.8)).max()) & ~(px.shift(1) >= px.shift(1).rolling(n, min_periods=int(n * 0.8)).max())
    event["創60日新低（對照）"] = (px <= px.rolling(60, min_periods=48).min()) & ~(px.shift(1) <= px.shift(1).rolling(60, min_periods=48).min())
    # --- ADX／DMI(14)
    pc = px.shift(1)
    tr = pd.DataFrame(np.fmax(np.fmax((h - l).to_numpy(), (h - pc).abs().to_numpy()), (l - pc).abs().to_numpy()), index=px.index, columns=px.columns)
    upm, dnm = h - h.shift(1), l.shift(1) - l
    pdm = upm.where((upm > dnm) & (upm > 0), 0.0)
    ndm = dnm.where((dnm > upm) & (dnm > 0), 0.0)
    atr = E32(tr, alpha=1 / 14, min_periods=14)
    pdi = 100 * E32(pdm, alpha=1 / 14, min_periods=14) / atr
    ndi = 100 * E32(ndm, alpha=1 / 14, min_periods=14) / atr
    adx = E32(100 * (pdi - ndi).abs() / (pdi + ndi), alpha=1 / 14, min_periods=14)
    cont["ADX14"] = adx
    state["ADX>25 且 +DI>−DI（趨勢向上）"] = (adx > 25) & (pdi > ndi)
    state["ADX>25 且 +DI<−DI（趨勢向下）"] = (adx > 25) & (pdi < ndi)
    cont["ATR14÷股價（波動）"] = atr / px
    # --- 量
    cont["量比（當天÷前20日均量）"] = f["vx"]
    cont["量能趨勢（近10日÷近60日）"] = f["vdry"]
    obv = (np.sign(r.fillna(0)) * V.fillna(0)).cumsum()
    event["OBV 創60日新高（前一天不是）"] = (obv >= obv.rolling(60, min_periods=48).max()) & ~(obv.shift(1) >= obv.shift(1).rolling(60, min_periods=48).max())
    event["價漲量增（漲≥3%、量≥2倍）"] = (r >= 0.03) & (f["vx"] >= 2)
    event["價跌量增（跌≥3%、量≥2倍）"] = (r <= -0.03) & (f["vx"] >= 2)
    event["帶量創60日新高（量≥2倍）"] = f["hi60"] & (f["vx"] >= 2)
    # --- K 線
    event["跳空開高≥3%且收紅"] = (o / px.shift(1) - 1 >= 0.03) & (px > o)
    event["長紅K（實體≥5%）"] = (px / o - 1 >= 0.05)
    event["長黑K（實體≤−5%）（對照）"] = (px / o - 1 <= -0.05)
    event["漲停"] = f["is_lu"]
    cont["60日波動度"] = f["volat"]
    cont = {k: v.astype("float32") for k, v in cont.items()}
    state = {k: v.fillna(False).astype(bool) for k, v in state.items()}
    event = {k: v.fillna(False).astype(bool) for k, v in event.items()}
    del V, h, l, o, tr, pdm, ndm, upm, dnm, atr, pdi, ndi, adx, obv, dif, dea, K, D, rsv, hh, ll, rsi, up, dn, sd, pb, ma
    import gc
    gc.collect()
    _I = (cont, state, event)
    return _I


def fwd_mats(f):
    px, ew = f["px"], f["ew"]
    pfw = px.ffill(limit=FWD)
    rev = lambda m: m[::-1]  # noqa: E731
    out = {}
    for n in (20, 60):
        out[f"x{n}"] = (pfw.shift(-n) / px - 1).sub(ew.shift(-n) / ew - 1, axis=0).astype("float32")
    out["fwd"] = (pfw.shift(-FWD) / px - 1).astype("float32")
    out["up"] = (rev(rev(pfw).rolling(FWD, min_periods=FWD).max()).shift(-1) / px - 1).astype("float32")
    out["dn"] = (rev(rev(pfw).rolling(FWD, min_periods=FWD).min()).shift(-1) / px - 1).astype("float32")
    return out


ERAS = (("05~12", "2005", "2012-12-31"), ("13~19", "2013", "2019-12-31"), ("20~26", "2020", "2030"))


def do_ic(P):
    f = sq.feats()
    cont, _, _ = indicators()
    F = fwd_mats(f)
    days = f["px"].index[250:len(f["px"].index) - FWD:STEP]
    ok = (f["val20"].loc[days] >= 3e7)
    P("===== 一、連續型指標的預測力（排名相關 IC；正＝越高之後越漲，贏全市場的幅度） =====")
    P(f"{'指標':<28}{'20日IC':>8}{'t':>6}{'60日IC':>9}{'t':>6}   60日IC 三段（05~12／13~19／20~26）   最高20%−最低20% 的 60日超額")
    rows = []
    for name, m in cont.items():
        a = m.loc[days].where(ok)
        res = {}
        for n in (20, 60):
            b = F[f"x{n}"].loc[days]
            ic = a.rank(axis=1).corrwith(b.rank(axis=1), axis=1)
            res[n] = ic.dropna()
        ic60 = res[60]
        eras = "／".join(f"{ic60[(ic60.index >= a_) & (ic60.index <= b_)].mean():+.3f}" for _, a_, b_ in ERAS)
        rk = a.rank(axis=1, pct=True)
        x = F["x60"].loc[days]
        spread = x.where(rk >= 0.8).mean(axis=1) - x.where(rk <= 0.2).mean(axis=1)
        sp_e = "／".join(f"{spread[(spread.index >= a_) & (spread.index <= b_)].mean():+.1%}" for _, a_, b_ in ERAS)
        t = lambda s: s.mean() / (s.std() / np.sqrt(len(s) / (60 / STEP)))  # noqa: E731  （重疊樣本，有效樣本數約除以 12）
        rows.append((abs(t(ic60)), f"{name:<26}{res[20].mean():>+8.3f}{t(res[20]) * np.sqrt(3):>6.1f}{ic60.mean():>+9.3f}{t(ic60):>6.1f}   {eras}   {spread.mean():+.1%}（{sp_e}）"))
    for _, s in sorted(rows, reverse=True):
        P(s)
    P("（t 已用重疊樣本調整；|t|>3 且三段同號才算穩）")


def do_lift(P):
    f = sq.feats()
    cont, state, event = indicators()
    F = fwd_mats(f)
    days = f["px"].index[250:len(f["px"].index) - FWD:STEP]
    ok = ((f["val20"].loc[days] >= 3e7) & F["fwd"].loc[days].notna()).to_numpy()
    up, dn, fwd, xs = (F[k].loc[days].to_numpy() for k in ("up", "dn", "fwd", "x60"))
    boom, bust = up >= 0.5, dn <= -0.25
    yrs = days.year.to_numpy()[:, None] * np.ones((1, ok.shape[1]), dtype=int)
    b0, d0 = boom[ok].mean(), bust[ok].mean()
    P(f"\n===== 二、指標狀態／訊號下的飆股與重摔機率（基準：飆 {b0:.1%}、摔 {d0:.1%}、60日中位 {np.median(fwd[ok]):+.1%}、賺錢 {(fwd[ok] > 0).mean():.0%}） =====")
    P(f"{'條件':<30}{'樣本':>8}{'飆股':>7}{'倍數':>6}{'三段倍數':>16}{'重摔':>7}{'摔÷飆':>6}{'中位':>7}{'贏全市場':>8}{'賺錢':>6}")

    def line(name, mask):
        m = mask & ok
        n = m.sum()
        if n < 300:
            return None
        b = boom[m].mean()
        er = []
        for _, a_, b_ in ERAS:
            e = (yrs >= int(a_[:4])) & (yrs <= int(b_[:4]))
            er.append(f"{boom[m & e].mean() / boom[ok & e].mean():.1f}" if (m & e).sum() > 50 else "—")
        return (xs[m].mean(), f"{name:<28}{n:>9,}{b:>7.1%}{b / b0:>5.1f}x{'／'.join(er):>16}{bust[m].mean():>7.1%}{bust[m].mean() / b if b else 0:>6.1f}"
                f"{np.median(fwd[m]):>+7.1%}{xs[m].mean():>+8.1%}{(fwd[m] > 0).mean():>6.0%}")
    rows = []
    for name, m in {**state, **event}.items():
        r_ = line(name, m.loc[days].fillna(False).to_numpy().astype(bool))
        if r_:
            rows.append(r_)
    bins = {"RSI14": [0, 30, 50, 70, 80, 101], "KD 的 K 值": [0, 20, 50, 80, 101], "布林 %b": [-9, 0, 0.5, 1, 9],
            "乖離20（收盤÷20日線−1）": [-9, -0.1, 0, 0.1, 0.2, 9], "相對強度排名（120日）": [0, 0.2, 0.5, 0.8, 0.9, 0.98, 1.01],
            "ADX14": [0, 15, 25, 40, 101]}
    for name, bs in bins.items():
        a = cont[name].loc[days].to_numpy()
        for lo, hi in zip(bs[:-1], bs[1:]):
            r_ = line(f"{name.split('（')[0]} {lo:g}~{hi:g}", (a >= lo) & (a < hi))
            if r_:
                rows.append(r_)
    for _, s in sorted(rows, reverse=True):
        P(s)
    P("（依『贏全市場』由高到低排序）")


def to_events(sig, f, minliq=1e8):
    from research.vcp_bt import to_events as te
    return te(sig, f, minliq)


def do_bt(P):
    f = sq.feats()
    _, _, event = indicators()
    r, _ = fs.revenue()
    X = ex.Exits(r)
    P("\n===== 三、訊號單獨做（隔日收盤買、20 份、持有 60 日、同天太多挑最接近一年高點；2005/3 起；加權同期 +9.1%／−58%） =====")
    rows = []
    for name, sig in event.items():
        e = to_events(sig, f)
        e = e[e["date"] >= "2005-03-01"]
        if len(e) < 500:
            continue
        res = pf.simulate(e.assign(hold=X.holds(e, ex.fixed(60))), 60, 20, start="2005-03-01", slip=0.003, skip_held=True)
        eq = res["_eq"]

        def seg(a, b):
            s = eq[(eq.index >= a) & (eq.index <= b)]
            y = (s.index[-1] - s.index[0]).days / 365.25
            return float((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1)
        c, t = res["curve"], res["trade"]
        rows.append((c["cagr"], f"{name:<28} 年化 {c['cagr']:+6.1%} 回落 {c['mdd']:+.0%}（{'／'.join(f'{seg(a, b):+.0%}' for _, a, b in ERAS)}）"
                     f"｜訊號 {len(e):>6,} 交易 {res['n_trades']:>5} 每筆 {t['mean']:+.1%} 中位 {t['med']:+.1%} 賺錢 {t['win']:.0%} 盈虧比 {t['payoff']} 持股 {res['invested']:.0%}"))
    for _, s in sorted(rows, reverse=True):
        P(s)
    # 隨機對照：每月第一個交易日隨機買（成交 ≥1 億、排除營建金融）
    px = f["px"]
    days = px.index[px.index >= "2005-03-01"]
    first = pd.Series(days).groupby([days.year, days.month]).first().values
    liq = f["val20"].shift(1)
    rr = [pd.DataFrame({"code": px.columns, "date": d, "liq": liq.loc[d].values}) for d in first]
    m = pd.concat(rr)
    m = m[(m["liq"] >= 1e8)]
    m = m[~excl_mask(m)][["code", "date"]]
    cs = [pf.simulate(m, 60, 20, start="2005-03-01", slip=0.003, seed=s)["curve"] for s in range(5)]
    P(f"對照：每月隨機買 20 檔（5 次平均） 年化 {np.mean([c['cagr'] for c in cs]):+.1%} 回落 {np.mean([c['mdd'] for c in cs]):+.0%}")


def do_rev(P):
    f = sq.feats()
    cont, state, event = indicators()
    r, rs = fs.revenue()
    X = ex.Exits(r)
    near1, liq1 = f["near"].shift(1), f["val20"].shift(1)
    base = ex.events(near1, liq1, r, rs, 10)
    h = X.holds(base, ex.fixed(60))

    def run(e, hh):
        res = pf.simulate(e.assign(hold=hh), 60, 20, start="2013-02-01", slip=0.003, skip_held=True)
        eq = res["_eq"]

        def seg(a, b):
            s = eq[(eq.index >= a) & (eq.index <= b)]
            y = (s.index[-1] - s.index[0]).days / 365.25
            return float((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1)
        return res, f"年化 {res['curve']['cagr']:+6.1%} 回落 {res['curve']['mdd']:+.0%}（13~19 {seg('2013', '2019-12-31'):+.0%}／20~26 {seg('2020', '2030'):+.0%}）｜交易 {res['n_trades']} 每筆 {res['trade']['mean']:+.1%} 賺錢 {res['trade']['win']:.0%} 持股 {res['invested']:.0%}"
    res0, s0 = run(base, h)
    P(f"\n===== 四、加在營收策略上（2013/2 起）｜基準（營收加速＋挑最接近一年高點）：{s0} =====")

    def look(m):
        m1 = m.shift(1)
        return np.array([m1.at[d, c] if c in m1.columns else np.nan for d, c in zip(base["date"], base["code"])], dtype=float)
    P("--- A. 只買『進場前一天符合』的（占比＝符合的訊號比例；不符合的另列） ---")
    rows = []
    recent = {k: v.rolling(10, min_periods=1).max() > 0 for k, v in event.items()}      # 事件：最近 10 日內發生過
    conds = {**state, **{f"近10日內：{k}": v for k, v in recent.items()}}
    for name, m in conds.items():
        v = look(m.astype("float32"))
        yes, no = base[v > 0], base[~(v > 0)]
        if len(yes) < 300:
            continue
        ry, sy = run(yes, X.holds(yes, ex.fixed(60)))
        rn, sn = run(no, X.holds(no, ex.fixed(60))) if len(no) >= 300 else (None, "—")
        rows.append((ry["curve"]["cagr"], f"{name:<30} 占 {len(yes) / len(base):>4.0%}｜符合 {sy}\n{'':<38}不符合 {sn}"))
    for _, s in sorted(rows, reverse=True):
        P(s)
    P("--- B. 排序換成該指標（越高越優先；加＊＝越低越優先） ---")
    rows = []
    for name, m in cont.items():
        v = look(m)
        for sign, tag in ((1, ""), (-1, "＊")):
            e = base.assign(score=np.nan_to_num(sign * v, nan=-9e9))
            res, s = run(e, h)
            rows.append((res["curve"]["cagr"], f"{tag + name:<30} {s}"))
    for _, s in sorted(rows, reverse=True)[:14]:
        P(s)
    P("  …（只列前 14 名；基準的排序＝離一年高點）")


def main(argv):
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    what = argv or ["ic", "lift", "bt", "rev"]
    P(f"手續費折數 {pf.FEE_DISC:g}")
    for w in what:
        {"ic": do_ic, "lift": do_lift, "bt": do_bt, "rev": do_rev}[w](P)
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / f"ta_scan_{'_'.join(what)}.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
