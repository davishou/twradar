"""最佳策略（營收年增加速＋挑最接近一年高點）的進場時點與出場規則（2026-11-03）

一、進場時點上限測試
   沒有每家公司實際公布營收的日期，所以假設「月底後第 D 天就拿到完整營收」（D = 1、3、5、7、10）。
   D < 10 會偷看到還沒公布的公司，是樂觀上限：如果連上限都只多一點，就不值得去補真實公布日。
二、出場規則（進場一樣是 10 日後第一個交易日收盤；出場＝觸發那天的隔天收盤）
   固定天數   20／40／60／90／120／250 日
   停損       從買價跌 10／15／20% 就賣（最多抱 60／120 日）
   移動停利   從持有期間最高點回落 15／20／25／30% 就賣（最多抱 120／250 日）
   均線       收盤跌破 20／60 日均線就賣（至少抱 10 日，最多 250 日）
   營收       之後每月營收公布期限：年增 < 0%／< 20%／不再加速（比上月低）就賣（最多 250 日）
   贏家續抱   60 日時賺錢就續抱、改用移動停利 20%（最多 250 日）；賠錢就賣
   組合       停損 15%＋移動停利 20%／營收年增 < 0＋停損 15%
同一檔還在手上時不重複買。成交 ≥1 億、排除營建金融、20 份、扣成本＋每邊滑價 0.3%，2013/2 起。

python -m research.exit_rules
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research import fin_signals as fs
from research import portfolio as pf
from research.robust_check import excl_mask, lookup, strength

SLIP = 0.003
START = "2013-02-01"
OUT = Path(__file__).parent / "results" / "exit_rules.json"


def curve(eq):
    def seg(a, b):
        s = eq[(eq.index >= a) & (eq.index <= b)]
        y = (s.index[-1] - s.index[0]).days / 365.25
        return float((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1)
    y = (eq.index[-1] - eq.index[0]).days / 365.25
    return {"cagr": float(eq.iloc[-1] ** (1 / y) - 1), "mdd": float((eq / eq.cummax() - 1).min()),
            "early": seg("2013-01-01", "2019-12-31"), "late": seg("2020-01-01", "2030-01-01")}


def events(near, liq, r, rs, day: int = 10):
    m = rs["rev_accel"].fillna(False)
    ev = r.loc[m, ["code", "ym"]].copy()
    ev["deadline"] = (ev["ym"] + 1).dt.to_timestamp() + pd.Timedelta(days=day - 1)
    e = pf.events_at_next_close(ev[["code", "deadline"]])
    e = e[e["date"] >= START].copy()
    e["score"], e["liq"] = lookup(near, e), lookup(liq, e)
    e = e[e["liq"].fillna(0) >= 1e8]
    return e[~excl_mask(e)].assign(score=lambda x: x["score"].fillna(-1))[["code", "date", "score"]].reset_index(drop=True)


class Exits:
    """幫每筆事件算持有天數（出場＝觸發日隔天收盤）"""

    def __init__(self, r):
        px, *_ = pf.prices()
        self.days = px.index
        self.col = {c: k for k, c in enumerate(px.columns)}
        self.a = px.to_numpy()
        self.ma = {n: px.rolling(n, min_periods=n).mean().to_numpy() for n in (20, 60)}
        # 營收：每檔每月的「檢查日」（公布期限後第一個交易日）與年增、前一月年增
        rr = r[["code", "ym", "yoy", "yoy_1"]].dropna(subset=["yoy"]).copy()
        dl = (rr["ym"] + 1).dt.to_timestamp() + pd.Timedelta(days=9)
        rr["ci"] = self.days.searchsorted(dl.values, side="right")
        self.rev = {c: (g["ci"].to_numpy(), g["yoy"].to_numpy(), g["yoy_1"].to_numpy()) for c, g in rr.groupby("code")}

    def holds(self, e: pd.DataFrame, rule) -> np.ndarray:
        n = len(self.days)
        di = {d: k for k, d in enumerate(self.days)}
        out = np.empty(len(e), dtype=int)
        for k, (d, c) in enumerate(zip(e["date"], e["code"])):
            i, j = di[d], self.col.get(c)
            if j is None:
                out[k] = 60
                continue
            out[k] = max(1, min(rule(self, i, j, c), n - 1 - i))
        return out


def fixed(N):
    return lambda X, i, j, c: N


def _first(cond: np.ndarray, start: int = 0):
    w = np.where(cond[start:])[0]
    return None if len(w) == 0 else int(w[0]) + start


def stop(x, maxh):
    def f(X, i, j, c):
        seg = X.a[i:i + maxh + 1, j] / X.a[i, j] - 1
        t = _first(seg <= -x, 1)
        return maxh if t is None else t + 1
    return f


def trail(x, maxh, sl=None):
    def f(X, i, j, c):
        p = X.a[i:i + maxh + 1, j]
        dd = p / np.fmax.accumulate(np.nan_to_num(p, nan=0)) - 1
        cond = dd <= -x
        if sl is not None:
            cond |= (p / p[0] - 1) <= -sl
        t = _first(cond, 1)
        return maxh if t is None else t + 1
    return f


def ma_exit(nma, maxh=250, minh=10):
    def f(X, i, j, c):
        p, m = X.a[i:i + maxh + 1, j], X.ma[nma][i:i + maxh + 1, j]
        t = _first(p < m, minh)
        return maxh if t is None else t + 1
    return f


def rev_exit(kind, maxh=250, sl=None):
    def f(X, i, j, c):
        lim = maxh
        if sl is not None:
            t = _first(X.a[i:i + maxh + 1, j] / X.a[i, j] - 1 <= -sl, 1)
            if t is not None:
                lim = t + 1
        if c not in X.rev:
            return lim
        ci, yoy, yoy1 = X.rev[c]
        for a, y, y1 in zip(ci, yoy, yoy1):
            if a <= i or a - i >= lim:
                continue
            bad = (y < 0) if kind == "neg" else (y < 20) if kind == "lt20" else (y1 == y1 and y < y1)
            if bad:
                return a - i            # 檢查日收盤賣
        return lim
    return f


def winner(maxh=250, x=0.2):
    def f(X, i, j, c):
        if i + 60 >= len(X.days) or not (X.a[i + 60, j] > X.a[i, j]):
            return 60
        p = X.a[i:i + maxh + 1, j]
        dd = p / np.fmax.accumulate(np.nan_to_num(p, nan=0)) - 1
        t = _first(dd <= -x, 61)
        return maxh if t is None else t + 1
    return f


RULES = {
    "固定 20 日": fixed(20), "固定 40 日": fixed(40), "固定 60 日（原本）": fixed(60), "固定 90 日": fixed(90),
    "固定 120 日": fixed(120), "固定 250 日": fixed(250),
    "停損 10%（最多 60 日）": stop(0.10, 60), "停損 15%（最多 60 日）": stop(0.15, 60), "停損 20%（最多 60 日）": stop(0.20, 60),
    "停損 15%（最多 120 日）": stop(0.15, 120),
    "移動停利 15%（最多 120 日）": trail(0.15, 120), "移動停利 20%（最多 120 日）": trail(0.20, 120),
    "移動停利 20%（最多 250 日）": trail(0.20, 250), "移動停利 25%（最多 250 日）": trail(0.25, 250), "移動停利 30%（最多 250 日）": trail(0.30, 250),
    "跌破 20 日線（最多 250 日）": ma_exit(20), "跌破 60 日線（最多 250 日）": ma_exit(60),
    "營收年增 < 0 才賣（最多 250 日）": rev_exit("neg"), "營收年增 < 20% 才賣（最多 250 日）": rev_exit("lt20"),
    "營收不再加速就賣（最多 250 日）": rev_exit("decel"),
    "贏家續抱：60 日賺錢改移動停利 20%": winner(),
    "停損 15%＋移動停利 20%（最多 250 日）": trail(0.20, 250, sl=0.15),
    "營收年增 < 0＋停損 15%（最多 250 日）": rev_exit("neg", sl=0.15),
    "營收年增 < 20%＋停損 15%（最多 250 日）": rev_exit("lt20", sl=0.15),
}


def run(e, holds, label, out):
    x = e.assign(hold=holds)
    res = pf.simulate(x, 60, 20, start=START, slip=SLIP, skip_held=True)
    c = curve(res["_eq"])
    t = res["trade"]
    hd = float(np.mean(holds))
    print(f"{label:<34} 年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（前 {c['early']:+.1%}／後 {c['late']:+.1%}）"
          f"｜交易 {res['n_trades']} 每筆 {t['mean']:+.1%} 中位 {t['med']:+.1%} 賺錢 {t['win']:.0%} 盈虧比 {t['payoff']}｜平均持有 {hd:.0f} 日｜持股 {res['invested']:.0%}", flush=True)
    out[label] = {**c, "n": res["n_trades"], "trade": t, "avg_hold": hd, "invested": res["invested"], "yearly": res["yearly"]}
    return res


def main():
    near, liq = strength()
    r, rs = fs.revenue()
    X = Exits(r)
    out = {"entry": {}, "exit": {}}
    print("== 一、進場時點（樂觀上限：D < 10 會偷看到還沒公布的公司），出場固定 60 日 ==")
    for day in (1, 3, 5, 7, 10):
        e = events(near, liq, r, rs, day)
        run(e, X.holds(e, fixed(60)), f"月底後第 {day} 天拿到營收", out["entry"])
    print("\n== 二、出場規則（進場：10 日後第一個交易日） ==")
    e = events(near, liq, r, rs, 10)
    for lab, rule in RULES.items():
        res = run(e, X.holds(e, rule), lab, out["exit"])
        if lab in ("固定 60 日（原本）", "移動停利 20%（最多 250 日）", "營收年增 < 0＋停損 15%（最多 250 日）", "贏家續抱：60 日賺錢改移動停利 20%"):
            print("     每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))



def refill_events(e: pd.DataFrame) -> pd.DataFrame:
    """候補：同一批名單在下一批進場日之前，每天都可以補進空出來的份數（照原本排名）"""
    px, *_ = pf.prices()
    days = px.index
    ent = sorted(e["date"].unique())
    nxt = {d: (ent[k + 1] if k + 1 < len(ent) else days[-1]) for k, d in enumerate(ent)}
    rows = []
    for d, g in e.groupby("date"):
        i0, i1 = days.get_loc(d), days.get_loc(nxt[d])
        for i in range(i0, i1):
            rows.append(g.assign(date=days[i]))
    return pd.concat(rows, ignore_index=True)


def main_refill():
    near, liq = strength()
    r, rs = fs.revenue()
    X = Exits(r)
    e = events(near, liq, r, rs, 10)
    ef = refill_events(e)
    out = {}
    print("== 三、出場後用同一批名單候補（賣出後 20 日內不買回同一檔） ==")
    for lab in ("固定 60 日（原本）", "固定 90 日", "停損 15%（最多 60 日）", "停損 20%（最多 60 日）", "移動停利 20%（最多 120 日）",
                "移動停利 25%（最多 250 日）", "跌破 60 日線（最多 250 日）", "停損 15%＋移動停利 20%（最多 250 日）", "贏家續抱：60 日賺錢改移動停利 20%",
                "營收年增 < 20% 才賣（最多 250 日）"):
        x = ef.assign(hold=X.holds(ef, RULES[lab]))
        res = pf.simulate(x, 60, 20, start=START, slip=SLIP, skip_held=True, cooldown=20)
        c = curve(res["_eq"])
        t = res["trade"]
        print(f"候補｜{lab:<30} 年化 {c['cagr']:+.1%} 回落 {c['mdd']:+.0%}（前 {c['early']:+.1%}／後 {c['late']:+.1%}）"
              f"｜交易 {res['n_trades']} 每筆 {t['mean']:+.1%} 賺錢 {t['win']:.0%} 盈虧比 {t['payoff']}｜持股 {res['invested']:.0%}", flush=True)
        out[lab] = {**c, "n": res["n_trades"], "trade": t, "invested": res["invested"], "yearly": res["yearly"]}
        if lab.startswith("停損 20%") or lab.startswith("固定 60"):
            print("     每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
    d = json.loads(OUT.read_text()) if OUT.exists() else {}
    d["refill"] = out
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    import sys
    main_refill() if "refill" in sys.argv[1:] else main()
