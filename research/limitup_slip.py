"""投信買超＋大盤前 20 日下跌的漲停股：加滑價、排除營建金融、成交門檻再測（2026-11-03）

漲停股隔日收盤買（排除隔日鎖漲停），資金 10 份、持有 20／60 日；投信資料 2012/5 起。
滑價：每邊 0／0.3％／0.5％；漲停股隔天常大幅跳動，0.5％ 比較貼近實際。

python -m research.limitup_slip
"""
from __future__ import annotations

from pipeline import backtest as bt
from research import portfolio as pf
from research.robust_check import excl_mask, lookup, strength


def main():
    ev = bt.limitup_events()
    _, liq = strength()
    groups = {
        "投信買超＋大盤前20日下跌": (ev["t"] > 0) & (ev["mkt20"] < 0),
        "投信買超＋大盤前20日跌 3% 以上": (ev["t"] > 0) & (ev["mkt20"] <= -0.03),
    }
    for name, m in groups.items():
        e0 = pf.events_at_next_close(ev.loc[(~ev["next_is_lu"] & m).fillna(False), ["code", "date"]].rename(columns={"date": "d0"}), when="d0")
        e0 = e0[e0["date"] >= "2012-06-01"]
        e0["liq"] = lookup(liq, e0)
        e0["excl"] = excl_mask(e0)
        print(f"\n===== {name}（{len(e0)} 次，2012/6 起） =====")
        for lab, e in (("全部", e0), ("排除營建金融＋成交≥1億", e0[~e0["excl"] & (e0["liq"].fillna(0) >= 1e8)])):
            for slip in (0, 0.003, 0.005):
                for hold in (20, 60):
                    x = e[["code", "date"]]
                    res = pf.simulate(x, hold, 10, start="2012-06-01", slip=slip)
                    a = pf.simulate(x, hold, 10, start="2012-06-01", end="2018-12-31", slip=slip)["curve"]
                    b = pf.simulate(x, hold, 10, start="2019-01-01", slip=slip)["curve"]
                    print(pf.fmt(res, f"{lab} 滑價{slip:.1%}") + f"｜前段12~18 {a['cagr']:+.1%}/{a['mdd']:+.0%}｜後段19~26 {b['cagr']:+.1%}/{b['mdd']:+.0%}")
                    if hold == 60 and slip == 0.003:
                        print("     每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly"].items()))
    print("     加權：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in res["yearly_taiex"].items()))


if __name__ == "__main__":
    main()
