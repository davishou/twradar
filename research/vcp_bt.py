"""波動收縮＋量縮後帶量突破（VCP／布林壓縮）回測（2026-11-10）

共同條件：訊號日收盤後才知道 → **隔一個交易日收盤買**；隔天一字漲停（買不到）不買；
          前一天 20 日均成交 ≥ 1 億、排除營建金融、每邊滑價 0.3%、20 份資金、同一檔在手上不重複買。
          同一天訊號超過空位時挑「最接近一年高點」的。手續費用環境變數 FEE_DISC（使用者實際 3 折）。

一、單獨做（2005 起；另列 2013 起以便和營收策略比）
  A 帶量突破          收盤創 60 日新高＋量 ≥ 前 20 日均量 2 倍
  B A＋突破前收縮     再要求前一天布林寬度在自己一年內最窄 25%
  C 布林壓縮突破      前一天布林最窄 20%，今天收盤站上（前一天的）布林上軌、收紅、量 ≥ 2 倍
  D VCP              前一天：前 120 日漲 ≥30%、離一年高點 <15%、振幅收縮 <0.8、量縮 <0.75；今天創 20 日新高＋量 ≥ 1.5 倍
  E 對照：只有強勢    前一天離一年高點 <5%，今天創 20 日新高（不看量、不看收縮）
  各測 持有 20／60 日、停損 8%／15%（最多 60 日）、移動停利 15%（最多 120 日）。

二、加在營收策略上（2013/2 起，基準＝營收年增加速＋挑最接近一年高點、持有 60 日）
  F1 進場日前一天要在收縮中（布林最窄 50%）／F2 要不在收縮中
  F3 排序改成「越收縮越前面」
  G  營收加速名單當股票池（公布後 20 個交易日內有效），等到帶量突破（A）才買
  H  同上，等到 VCP（D）或布林壓縮突破（C）才買

python -m research.vcp_bt
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

SLIP, SLOTS = 0.003, 20


def signals(f) -> dict:
    px = f["px"]
    p1 = lambda m: m.shift(1)  # noqa: E731
    ma20 = px.rolling(20, min_periods=15).mean()
    upper = ma20 + 2 * px.rolling(20, min_periods=15).std()
    up_day = f["r"] > 0
    A = f["hi60"] & (f["vx"] >= 2)
    B = A & (p1(f["bbw_pct"]) < 0.25)
    C = (p1(f["bbw_pct"]) < 0.20) & (px > p1(upper)) & up_day & (f["vx"] >= 2)
    D = ((p1(f["ret120"]) >= 0.3) & (p1(f["near"]) >= 0.85) & (p1(f["rng"]) < 0.8) & (p1(f["vdry"]) < 0.75)
         & f["hi20"] & (f["vx"] >= 1.5))
    E = (p1(f["near"]) >= 0.95) & f["hi20"]
    return {"A 帶量突破": A, "B 帶量突破＋突破前布林最窄25%": B, "C 布林壓縮突破": C, "D VCP": D, "E 對照：只有強勢（近高點＋20日新高）": E}


def to_events(sig: pd.DataFrame, f, minliq=1e8) -> pd.DataFrame:
    """訊號日 t → 進場日 t+1 收盤；流動性、排序用 t 當天收盤資料；t+1 一字漲停不買"""
    q = bt.load_quotes()[["date", "code", "high", "low", "is_lu"]]
    lock = q[q["is_lu"] & (q["high"] <= q["low"] + 1e-9)]
    locked = set(zip(lock["date"], lock["code"]))
    days = sig.index
    s = sig.fillna(False).astype(bool)
    ii, jj = np.where(s.to_numpy())
    ok = ii + 1 < len(days)
    ii, jj = ii[ok], jj[ok]
    e = pd.DataFrame({"code": sig.columns.to_numpy()[jj], "date": days[ii + 1],
                      "score": f["near"].to_numpy()[ii, jj], "liq": f["val20"].to_numpy()[ii, jj]})
    e = e[(e["liq"] >= minliq) & e["score"].notna()]
    e = e[~excl_mask(e)]
    e = e[[(d, c) not in locked for d, c in zip(e["date"], e["code"])]]
    return e[["code", "date", "score"]].reset_index(drop=True)


def run(e, holds, label, start, P, yearly=False):
    x = e.assign(hold=holds)
    res = pf.simulate(x, 60, SLOTS, start=start, slip=SLIP, skip_held=True)
    eq = res["_eq"]

    def seg(a, b):
        s = eq[(eq.index >= a) & (eq.index <= b)]
        if len(s) < 250:
            return float("nan")
        y = (s.index[-1] - s.index[0]).days / 365.25
        return float((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1)
    c, t, tx = res["curve"], res["trade"], res["taiex"]
    if not res["n_trades"]:
        P(f"{label:<40} 沒有交易")
        return res
    P(f"{label:<40} 年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（05~12 {seg('2005', '2012-12-31'):+.1%}／13~19 {seg('2013', '2019-12-31'):+.1%}／20~26 {seg('2020', '2030'):+.1%}）"
      f"｜{res['n_trades']} 筆 每筆 {t['mean']:+.1%} 中位 {t['med']:+.1%} 賺錢 {t['win']:.0%} 盈虧比 {t['payoff']} 大賺≥30% {t['big']:.0%}"
      f"｜持股 {res['invested']:.0%}｜加權 {tx['cagr']:+.1%}/{tx['mdd']:+.0%}")
    if yearly:
        P("     每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
    return res


def main(argv):
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    f = sq.feats()
    r, rs = fs.revenue()
    X = ex.Exits(r)
    S = signals(f)
    rules = {"持有20日": ex.fixed(20), "持有60日": ex.fixed(60), "停損8%（最多60日）": ex.stop(0.08, 60),
             "停損15%（最多60日）": ex.stop(0.15, 60), "移動停利15%（最多120日）": ex.trail(0.15, 120)}
    P(f"手續費折數 {pf.FEE_DISC:g}、每邊滑價 {SLIP:.1%}、{SLOTS} 份、成交 ≥1 億、排除營建金融、隔日收盤買")
    P("\n===== 一、單獨做 =====")
    EV = {}
    for name, sig in S.items():
        e = to_events(sig, f)
        EV[name] = e
        e05 = e[e["date"] >= "2005-03-01"]
        P(f"\n--- {name}：2005 起 {len(e05):,} 個訊號（平均每月 {len(e05) / 260:.0f} 個） ---")
        for lab, rule in rules.items():
            run(e05, X.holds(e05, rule), f"{lab}", "2005-03-01", P, yearly=(lab == "持有60日"))
        e13 = e[e["date"] >= "2013-02-01"]
        run(e13, X.holds(e13, ex.fixed(60)), "［2013/2 起］持有60日", "2013-02-01", P)

    P("\n===== 二、加在營收策略上（2013/2 起） =====")
    near1, bb1 = f["near"].shift(1), f["bbw_pct"].shift(1)
    liq1 = f["val20"].shift(1)
    base = ex.events(near1, liq1, r, rs, 10)
    base["bb"] = [bb1.at[d, c] if c in bb1.columns else np.nan for d, c in zip(base["date"], base["code"])]
    h60 = lambda e: X.holds(e, ex.fixed(60))  # noqa: E731
    run(base, h60(base), "基準：營收加速＋挑最接近高點", "2013-02-01", P, yearly=True)
    e = base[base["bb"] < 0.5]
    run(e, h60(e), f"F1 只買收縮中（布林最窄50%，占 {len(e) / len(base):.0%}）", "2013-02-01", P)
    e = base[base["bb"] >= 0.5]
    run(e, h60(e), f"F2 只買不在收縮中（占 {len(e) / len(base):.0%}）", "2013-02-01", P)
    e = base.assign(score=-base["bb"].fillna(1))
    run(e, h60(e), "F3 排序改成越收縮越前面", "2013-02-01", P)
    e = base.assign(score=base["bb"].fillna(0))
    run(e, h60(e), "F3' 排序改成布林越寬越前面", "2013-02-01", P)
    # 股票池：營收加速生效後 20 個交易日內
    R = sq.revenue_state(f["px"].index, f["px"].columns)
    pool = (R["accel"] > 0) & (R["age"].to_numpy()[:, None] <= 20)
    for nm, key in (("G 股票池＋A 帶量突破才買", ["A 帶量突破"]), ("H 股票池＋C 或 D（收縮後突破）才買", ["C 布林壓縮突破", "D VCP"]),
                    ("G' 股票池＋B（突破前收縮）才買", ["B 帶量突破＋突破前布林最窄25%"])):
        sig = None
        for k in key:
            sig = S[k] if sig is None else (sig | S[k])
        e = to_events(sig & pool, f)
        e = e[e["date"] >= "2013-02-01"]
        P(f"  {nm}：{len(e)} 個訊號")
        for lab in ("持有60日", "停損15%（最多60日）"):
            run(e, X.holds(e, rules[lab]), f"{nm} {lab}", "2013-02-01", P, yearly=(lab == "持有60日"))
    # 一半資金基準、一半資金等突破（看有沒有互補）
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / "vcp_bt.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
