"""股價翻倍時，個股期貨『照淨值調口數』的實際操作流水帳（2026-11-12）
python -m research.stock_double_demo [代號] [起日] [迄日]
小型個股期貨（1 口 100 股）。原始保證金 13.5%、維持 10.35%（級距一，近似）。每月月底照「淨值×槓桿÷契約價值」調口數。
損益用實際股價漲跌（不含股利；個股期貨除息時期交所會調整契約，實際會再多拿到股利）。
注意：資料庫的還原價在除權息當天把那天的漲跌整個抹成 0（參考價欄等於收盤價），所以這裡不用還原價。
成本：每口每邊 30 元手續費＋1 檔滑價（100 元）＋期交稅十萬分之二；每月轉倉一次。"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from pipeline import backtest as bt

IM, MM, MUL = 0.135, 0.1035, 100


def run(code, a, b, L, mode, P=None, start=500_000.0):
    q = bt.load_quotes()
    raw = q[q.code == code].set_index("date")[["close", "low"]].loc[a:b]
    r = raw["close"].pct_change().fillna(0).to_numpy()
    lowr = (raw["low"] / raw["close"]).to_numpy()
    c = raw["close"].to_numpy()
    me = raw.index.to_series().groupby([raw.index.year, raw.index.month]).transform("max") == raw.index
    eq, lots, mx_lev, min_ri, events = start, 0, 0.0, 9.9, 0
    cost = lambda n, px: n * (30 + 100 + 0.00002 * px * MUL)  # noqa: E731
    rows = []
    for i in range(len(c)):
        if lots:
            prev = c[i - 1] * (1 + r[i]) / (c[i] / c[i - 1]) if i else c[i]
            pnl_close = lots * MUL * c[i - 1] * r[i]                    # 以昨天的契約價值 × 還原報酬
            low_ret = (1 + r[i]) * lowr[i] - 1
            worst = eq + lots * MUL * c[i - 1] * low_ret
            ri = worst / (IM * lots * MUL * c[i] * lowr[i])
            min_ri = min(min_ri, ri)
            mx_lev = max(mx_lev, lots * MUL * c[i] * lowr[i] / max(worst, 1))
            if worst < MM * lots * MUL * c[i] * lowr[i]:
                events += 1
            eq += pnl_close
        if i == 0 or (me.iloc[i] and mode == "rebalance"):
            before = lots
            tgt = int(eq * L / (c[i] * MUL))
            if tgt != lots:
                eq -= cost(abs(tgt - lots), c[i])
            if i:
                eq -= cost(2 * min(before, tgt), c[i])                    # 轉倉
            lots = tgt
            if P is not None:
                cv = lots * MUL * c[i]
                act = "進場" if i == 0 else ("不動" if tgt == before else (f"加 {tgt - before} 口" if tgt > before else f"減 {before - tgt} 口"))
                rows.append((raw.index[i].date(), c[i], before, eq, before * MUL * c[i] / eq if before else 0, act, lots, cv, IM * cv, MM * cv, eq / (IM * cv) if cv else 0, min_ri))
                min_ri = 9.9
        elif mode == "fixed" and me.iloc[i]:
            eq -= cost(2 * lots, c[i])
            if P is not None:
                cv = lots * MUL * c[i]
                rows.append((raw.index[i].date(), c[i], lots, eq, cv / eq, "不動", lots, cv, IM * cv, MM * cv, eq / (IM * cv), min_ri))
                min_ri = 9.9
    if P is not None:
        P(f"{'月底':<11}{'股價':>6}｜{'調整前':>4}{'淨值':>11}{'槓桿':>6}｜{'動作':<8}{'調整後':>4}{'契約總值':>11}{'原始保證金':>10}{'維持保證金':>10}{'風險指標':>8}｜這個月最低風險指標")
        for d, px, bf, e, lev, act, lt, cv, im, mm, ri, mri in rows:
            P(f"{str(d):<11}{px:>6.0f}｜{bf:>4}口{e:>10,.0f}{lev:>5.1f}x｜{act:<8}{lt:>4}口{cv:>11,.0f}{im:>10,.0f}{mm:>10,.0f}{ri:>8.0%}｜{(f'{mri:.0%}' if mri < 9 else ''):>6}")
    return eq, c[0], c[-1], events, mx_lev


def main(argv):
    code, a, b = (argv + ["2330", "2023-10-31", "2024-10-31"])[:3]
    out = []
    P = lambda s="": (print(s, flush=True), out.append(s))  # noqa: E731
    P(f"===== {code} 小型個股期貨，{a} ~ {b}，50 萬起步、2 倍槓桿、每月月底照淨值調口數 =====")
    e, p0, p1, ev, mx = run(code, a, b, 2, "rebalance", P)
    P(f"\n股價 {p0:.0f} → {p1:.0f}（{p1 / p0:.2f} 倍）；淨值 50 萬 → {e:,.0f}（{e / 5e5:.2f} 倍）；途中最高實際槓桿 {mx:.1f} 倍；跌破維持 {ev} 次")
    P("\n對照（同一段）：")
    P(f"  現股 50 萬（不含股利）：{5e5 * p1 / p0:,.0f}")
    for L, mode, lab in ((2, "fixed", "2 倍、口數固定不調"), (2, "rebalance", "2 倍、每月調"), (3, "fixed", "3 倍、口數固定不調"), (3, "rebalance", "3 倍、每月調")):
        e, *_ , ev, mx = run(code, a, b, L, mode)
        P(f"  {lab}：{e:,.0f}（{e / 5e5:.2f} 倍；最高實際槓桿 {mx:.1f} 倍、跌破維持 {ev} 次）")
    from research import portfolio as pf
    pf.OUT.mkdir(exist_ok=True)
    (pf.OUT / f"stock_double_{code}.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
