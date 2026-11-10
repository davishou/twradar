"""技術指標：多層濾網、看空訊號反著買、以及『10 萬變 1000 萬』模擬（2026-11-10）

python -m research.ta_combo layers   兩層、三層濾網全部組合：用 2005~2015 挑最好的，看 2016~2026 還剩多少（挑選偏誤有多大）
python -m research.ta_combo bear     看空訊號（死亡交叉、跌破年線、創新低、長黑、跌停、空頭排列…）拿來買進
python -m research.ta_combo rich     隨機交易者模擬：集中持股＋融資，多少人能 100 倍、多少人賠光
共同：3 折手續費（FEE_DISC）、每邊滑價 0.3%、成交 ≥1 億（layers 的篩選階段 ≥3,000 萬）、排除營建金融、訊號隔日收盤買。
"""
from __future__ import annotations

import itertools
import sys

import numpy as np
import pandas as pd

from research import exit_rules as ex
from research import fin_signals as fs
from research import portfolio as pf
from research import squeeze as sq
from research import ta_scan as ta
from research.vcp_bt import to_events

SPLIT = "2016-01-01"


def conditions() -> dict:
    f = sq.feats()
    cont, state, event = ta.indicators()
    rec = lambda k: event[k].rolling(10, min_periods=1).max() > 0  # noqa: E731
    c = {
        "站上20日線": state["站上20日線"], "站上60日線": state["站上60日線"], "站上200日線": state["站上200日線"],
        "多頭排列": state["多頭排列 5>10>20>60"], "60日線上揚": state["60日線上揚"], "MACD>0": state["MACD DIF>0"],
        "ADX趨勢向上": state["ADX>25 且 +DI>−DI（趨勢向上）"],
        "離高點<5%": f["near"] >= 0.95, "離高點<15%": f["near"] >= 0.85, "相對強度前10%": cont["相對強度排名（120日）"] >= 0.9,
        "RSI≥70": cont["RSI14"] >= 70, "RSI 50~70": (cont["RSI14"] >= 50) & (cont["RSI14"] < 70), "K≥80": cont["KD 的 K 值"] >= 80,
        "近10日創250日新高": rec("創250日新高（前一天不是）"), "近10日創60日新高": rec("創60日新高（前一天不是）"),
        "近10日KD金叉": rec("KD 黃金交叉（全部）"), "近10日MACD金叉": rec("MACD 黃金交叉（全部）"), "近10日5/20金叉": rec("5/20 黃金交叉"),
        "近10日價漲量增": rec("價漲量增（漲≥3%、量≥2倍）"), "近10日長紅K": rec("長紅K（實體≥5%）"), "近10日OBV創高": rec("OBV 創60日新高（前一天不是）"),
        "當天量≥2倍": f["vx"] >= 2, "量能放大": f["vdry"] >= 1.5, "量縮": f["vdry"] < 0.75,
        "低波動": f["volat"] < 0.35, "布林收縮": f["bbw_pct"] < 0.25, "布林擴張": f["bbw_pct"] > 0.75,
        "RSI<30": cont["RSI14"] < 30, "K<20": cont["KD 的 K 值"] < 20, "乖離20<−10%": cont["乖離20（收盤÷20日線−1）"] < -0.10,
    }
    return {k: v.fillna(False).astype(bool) for k, v in c.items()}


def do_layers(P):
    f = sq.feats()
    C = conditions()
    F = ta.fwd_mats(f)
    days = f["px"].index[250:len(f["px"].index) - ta.FWD:ta.STEP]
    ok = ((f["val20"].loc[days] >= 3e7) & F["fwd"].loc[days].notna()).to_numpy()
    xs = np.nan_to_num(F["x60"].loc[days].to_numpy())
    win = (F["fwd"].loc[days].to_numpy() > 0)
    is_ = (days < SPLIT)[:, None] & ok
    oos = (days >= SPLIT)[:, None] & ok
    A = {k: v.loc[days].to_numpy() for k, v in C.items()}
    names = list(A)
    rows = []
    for k in (1, 2, 3):
        for combo in itertools.combinations(names, k):
            m = A[combo[0]]
            for c in combo[1:]:
                m = m & A[c]
            a, b = m & is_, m & oos
            na, nb = a.sum(), b.sum()
            if na < 3000 or nb < 3000:
                continue
            rows.append((k, " ＋ ".join(combo), na, xs[a].mean(), win[a].mean(), nb, xs[b].mean(), win[b].mean()))
    R = pd.DataFrame(rows, columns=["層數", "條件", "前段樣本", "前段超額", "前段賺錢", "後段樣本", "後段超額", "後段賺錢"])
    P(f"===== 多層濾網：{len(names)} 個條件，一層 {sum(R['層數'] == 1)}、兩層 {sum(R['層數'] == 2)}、三層 {sum(R['層數'] == 3)} 個組合（樣本夠的） =====")
    P(f"衡量：符合條件的股票，之後 60 日贏全市場幾點。前段 2005~2015 用來挑，後段 2016~2026 驗證。基準（全部）：前段賺錢 {win[is_].mean():.0%}、後段 {win[oos].mean():.0%}")
    P("\n--- 1. 層數越多越好嗎？（各層數的組合：前段最好 10 名的平均／全部的中位） ---")
    for k in (1, 2, 3):
        r = R[R["層數"] == k]
        top = r.nlargest(10, "前段超額")
        P(f"  {k} 層：前段最好 10 名 前段 {top['前段超額'].mean():+.1%} → 後段 {top['後段超額'].mean():+.1%}（後段賺錢 {top['後段賺錢'].mean():.0%}）｜"
          f"全部組合中位 前段 {r['前段超額'].median():+.1%}、後段 {r['後段超額'].median():+.1%}｜前後段排名相關 {r['前段超額'].corr(r['後段超額'], method='spearman'):+.2f}")
    P("\n--- 2. 前段（2005~2015）最好的 12 個三層組合，到後段剩多少 ---")
    for r in R[R["層數"] == 3].nlargest(12, "前段超額").itertuples():
        P(f"  {r.條件:<44} 前段 {r.前段超額:+.1%}（賺錢 {r.前段賺錢:.0%}、n={r.前段樣本:,}）→ 後段 {r.後段超額:+.1%}（賺錢 {r.後段賺錢:.0%}、n={r.後段樣本:,}）")
    P("\n--- 3. 前後兩段都好的組合（依兩段較差的那一段排序，前 12 名；任何層數） ---")
    R["兩段較差"] = R[["前段超額", "後段超額"]].min(axis=1)
    for r in R.nlargest(12, "兩段較差").itertuples():
        P(f"  {r.層數} 層 {r.條件:<44} 前段 {r.前段超額:+.1%}／後段 {r.後段超額:+.1%}（賺錢 {r.前段賺錢:.0%}／{r.後段賺錢:.0%}、n={r.前段樣本:,}／{r.後段樣本:,}）")
    P("\n--- 4. 最常出現在『兩段都好』前 100 名裡的條件 ---")
    top = R.nlargest(100, "兩段較差")["條件"].str.split(" ＋ ").explode().value_counts()
    P("  " + "、".join(f"{k}（{v}）" for k, v in top.head(10).items()))
    worst = R.nsmallest(100, "兩段較差")["條件"].str.split(" ＋ ").explode().value_counts()
    P("  最差 100 名裡最常出現：" + "、".join(f"{k}（{v}）" for k, v in worst.head(8).items()))
    # 資金曲線：兩段都好的前 6 名（條件『剛成立』那天當訊號）
    P("\n--- 5. 真的拿去買（條件剛成立的隔日收盤買、20 份、持有 60 日；2005/3 起；加權 +9.1%／−58%） ---")
    r_, _ = fs.revenue()
    X = ex.Exits(r_)
    picks = list(R[R["層數"] >= 2].nlargest(6, "兩段較差")["條件"]) + ["近10日創250日新高", "離高點<5%"]
    for name in picks:
        m = None
        for c in name.split(" ＋ "):
            m = C[c] if m is None else (m & C[c])
        sig = m & ~m.shift(1, fill_value=False)
        e = to_events(sig, f)
        e = e[e["date"] >= "2005-03-01"]
        res = pf.simulate(e.assign(hold=X.holds(e, ex.fixed(60))), 60, 20, start="2005-03-01", slip=0.003, skip_held=True)
        eq = res["_eq"]

        def seg(a, b):
            s = eq[(eq.index >= a) & (eq.index <= b)]
            y = (s.index[-1] - s.index[0]).days / 365.25
            return float((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1)
        t = res["trade"]
        P(f"  {name:<44} 年化 {res['curve']['cagr']:+.1%} 回落 {res['curve']['mdd']:+.0%}（05~15 {seg('2005', '2015-12-31'):+.0%}／16~26 {seg('2016', '2030'):+.0%}）｜"
          f"訊號 {len(e):,} 交易 {res['n_trades']} 每筆 {t['mean']:+.1%} 賺錢 {t['win']:.0%} 持股 {res['invested']:.0%}")


def do_bear(P):
    f = sq.feats()
    cont, state, event = ta.indicators()
    px, r = f["px"], f["r"]
    ma = {n: px.rolling(n, min_periods=int(n * 0.8)).mean() for n in (5, 20, 60, 200)}
    cross_dn = lambda a, b: (a < b) & (a.shift(1) >= b.shift(1))  # noqa: E731
    K = cont["KD 的 K 值"]
    lim = pd.Series(np.where(px.index >= pd.Timestamp("2015-06-01"), 0.095, 0.065), index=px.index)
    bear = {
        "5/20 死亡交叉": cross_dn(ma[5], ma[20]), "20/60 死亡交叉": event["20/60 死亡交叉（對照）"],
        "跌破年線（200日線）": cross_dn(px, ma[200]), "跌破60日線": cross_dn(px, ma[60]),
        "MACD 死亡交叉": cross_dn(cont["MACD 柱狀體÷股價"], cont["MACD 柱狀體÷股價"] * 0),
        "KD 高檔死亡交叉（K>80 跌下來）": (K < 80) & (K.shift(1) >= 80),
        "RSI 跌破30": (cont["RSI14"] < 30) & (cont["RSI14"].shift(1) >= 30),
        "跌破布林下軌": (cont["布林 %b"] < 0) & (cont["布林 %b"].shift(1) >= 0),
        "創60日新低": event["創60日新低（對照）"],
        "創250日新低": (px <= px.rolling(250, min_periods=200).min()) & ~(px.shift(1) <= px.shift(1).rolling(250, min_periods=200).min()),
        "長黑K（實體≤−5%）": event["長黑K（實體≤−5%）（對照）"], "價跌量增（跌≥3%、量≥2倍）": event["價跌量增（跌≥3%、量≥2倍）"],
        "跌停": r.le(-lim, axis=0), "空頭排列剛形成": state["空頭排列 5<10<20<60"] & ~state["空頭排列 5<10<20<60"].shift(1, fill_value=False),
        "乖離20 跌破 −15%": (cont["乖離20（收盤÷20日線−1）"] < -0.15) & (cont["乖離20（收盤÷20日線−1）"].shift(1) >= -0.15),
        "連跌5天": (r < 0).rolling(5).sum().eq(5) & ~(r.shift(1) < 0).rolling(5).sum().eq(5),
        "20日內跌 ≥30%": (f["ret20"] <= -0.30) & (f["ret20"].shift(1) > -0.30),
    }
    bear = {k: v.fillna(False).astype(bool) for k, v in bear.items()}
    ew = f["ew"]
    mk60 = (ew / ew.shift(60) - 1)
    crash = mk60 < -0.10                                         # 全市場（等權）前 60 日跌 >10%
    R = sq.revenue_state(px.index, px.columns)
    good = (R["yoy"] >= 20)
    r_, _ = fs.revenue()
    X = ex.Exits(r_)
    P("===== 看空訊號拿來買進（隔日收盤買、20 份、同天太多時挑最接近一年高點；2005/3 起；加權 +9.1%／−58%；流動股全買約 +3%） =====")

    def run(sig, hold, start="2005-03-01", rank=None):
        e = to_events(sig, f)
        e = e[e["date"] >= start]
        if len(e) < 200:
            return None, f"訊號 {len(e)}（太少）"
        if rank is not None:
            e["score"] = [rank.at[d, c] for d, c in zip(e["date"], e["code"])]
            e["score"] = e["score"].fillna(-9)
        res = pf.simulate(e.assign(hold=X.holds(e, ex.fixed(hold))), hold, 20, start=start, slip=0.003, skip_held=True)
        t = res["trade"]
        return res, f"年化 {res['curve']['cagr']:+6.1%} 回落 {res['curve']['mdd']:+.0%}｜每筆 {t['mean']:+.1%} 中位 {t['med']:+.1%} 賺錢 {t['win']:.0%}（訊號 {len(e):,}、持股 {res['invested']:.0%}）"
    deep = -(f["near"].shift(1))                                  # 排序改成『離高點最遠（跌最深）』
    for name, sig in bear.items():
        P(f"\n{name}")
        for hold in (5, 20, 60):
            P(f"  持有 {hold:>2} 日：{run(sig, hold)[1]}")
        P(f"  持有 60 日、改挑跌最深的：{run(sig, 60, rank=deep)[1]}")
        cm = pd.DataFrame(sig.to_numpy() & crash.reindex(sig.index).fillna(False).to_numpy()[:, None], index=sig.index, columns=sig.columns)
        P(f"  只在大盤前 60 日跌 >10% 時買（60 日）：{run(cm, 60)[1]}")
        g = sig & (good.reindex(index=sig.index, columns=sig.columns).fillna(False))
        P(f"  加上營收年增 ≥20%（60 日，2013 起）：{run(g, 60, start='2013-02-01')[1]}")


def do_rich(P):
    """隨機交易者：每 20 個交易日換股一次，持有 k 檔（等權），槓桿 L（借錢利率年 6.5%，淨值跌到 0 就出局），
    成本每次換股 0.6%×槓桿。股票從成交 ≥1 億的普通股隨機挑（沒有任何選股能力）；另一組＝有『營收加速＋近高點』名單時從名單前 k 名挑。"""
    f = sq.feats()
    px = f["px"]
    rng = np.random.default_rng(7)
    idx = np.arange(250, len(px.index) - 21, 20)
    a = px.to_numpy()
    liq = f["val20"].to_numpy()
    blocks = []                                                  # 每個 20 日區間：可選股票的 20 日報酬、區間內最低點
    for i in idx:
        ok = np.isfinite(a[i]) & (liq[i] >= 1e8)
        seg = a[i:i + 21][:, ok]
        seg = pd.DataFrame(seg).ffill().to_numpy()
        ret = seg[-1] / seg[0] - 1
        low = np.nanmin(seg, axis=0) / seg[0] - 1
        blocks.append((np.clip(ret, -0.9, 3), low))
    P("===== 10 萬變 1000 萬（100 倍）需要什麼？隨機交易者模擬（完全沒有選股能力，只有集中＋槓桿） =====")
    P(f"每 20 個交易日換一次股，從成交 ≥1 億的股票隨機挑；{px.index[idx[0]].date()} 起，隨機抽起點；每組 20,000 人。借錢年息 6.5%、每次換股成本 0.6%×槓桿；淨值歸零就出局。")
    P(f"{'持股檔數':>6}{'槓桿':>6}{'年數':>5}{'  賺 100 倍以上':>12}{'  賺 10 倍以上':>11}{'  中位數':>8}{'  賠掉一半以上':>12}{'  賠光（剩<10%）':>14}")
    nper = {5: 62, 10: 125, 20: 250}
    for k in (1, 3, 10):
        for L in (1.0, 2.5):
            for yrs in (5, 10, 20):
                n = nper[yrs]
                if n >= len(blocks):
                    continue
                N = 20000
                eq = np.ones(N)
                alive = np.ones(N, bool)
                start = rng.integers(0, len(blocks) - n, N)
                for s in range(n):
                    for b0 in np.unique(start):
                        m = (start == b0) & alive
                        if not m.any():
                            continue
                        ret, low = blocks[b0 + s]
                        pick = rng.integers(0, len(ret), (m.sum(), k))
                        pr = ret[pick].mean(axis=1)
                        pl = low[pick].mean(axis=1)
                        wiped = (1 + L * pl) <= 0.05                # 區間內曾經跌到追繳斷頭
                        g = 1 + L * pr - (L - 1) * 0.065 * 20 / 250 - 0.006 * L
                        g = np.where(wiped, 0.03, np.maximum(g, 0.03))
                        eq[m] *= g
                    alive &= eq > 1e-3
                P(f"{k:>8}{L:>7.1f}x{yrs:>5}{(eq >= 100).mean():>13.2%}{(eq >= 10).mean():>12.1%}{np.median(eq):>9.2f}x{(eq <= 0.5).mean():>12.0%}{(eq <= 0.1).mean():>14.0%}")
    P("\n對照：穩定複利要幾年才 100 倍？ 年化 15% → 33 年；30%（營收策略回測值）→ 17.6 年；59%（多策略＋停損 15%＋1.5 倍槓桿的回測值）→ 9.9 年；100% → 6.6 年；150% → 5 年")


def main(argv):
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    w = argv[0] if argv else "layers"
    {"layers": do_layers, "bear": do_bear, "rich": do_rich}[w](P)
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / f"ta_combo_{w}.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
