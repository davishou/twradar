"""漲停股研究用 2004 起的完整資料重跑：超額（贏大盤）與絕對報酬兩種角度

python -m research.limitup_abs
"""
from __future__ import annotations

import pandas as pd

from pipeline import backtest as bt
from research import portfolio as pf
from research import signal_search as ss


def main():
    ev = bt.limitup_events()
    print(f"漲停事件 {len(ev)} 次，{ev['date'].min().date()} ~ {ev['date'].max().date()}；前後段切在 {ss.SPLIT}")
    for h in (20, 60):
        print(f"\n################ 超額報酬（贏大盤）版本，持有 {h} 日 ################")
        print(ss.run(h, ev))
        ea = ev.copy()
        for p in ("c", "o"):
            ea[f"x{p}{h}"] = ea[f"r{p}{h}"]
        print(f"\n################ 絕對報酬版本（勝率＝賺錢機率，未扣成本），持有 {h} 日 ################")
        print(ss.run(h, ea))
    # 資金曲線：全部漲停股、之前唯一通過的「投信買超＋大盤前20日下跌」、大盤跌深版本、反向警訊
    groups = {
        "全部漲停股（隔日收盤買、排除隔日鎖漲停）": ~ev["next_is_lu"],
        "投信買超＋大盤前20日下跌": ~ev["next_is_lu"] & (ev["t"] > 0) & (ev["mkt20"] < 0),
        "投信買超＋大盤前20日跌 3% 以上": ~ev["next_is_lu"] & (ev["t"] > 0) & (ev["mkt20"] <= -0.03),
        "大盤前20日跌 3% 以上（不看法人）": ~ev["next_is_lu"] & (ev["mkt20"] <= -0.03),
        "警訊：隔日跳空 > 6%": ~ev["next_is_lu"] & (ev["gap_next"] > 6),
        "警訊：連板 ≥ 2": ~ev["next_is_lu"] & (ev["streak"] >= 2),
    }
    print("\n################ 照訊號買的資金曲線（隔日收盤買、資金 10 份、扣成本） ################")
    for name, m in groups.items():
        e = pf.events_at_next_close(ev.loc[m.fillna(False), ["code", "date"]].rename(columns={"date": "d0"}), when="d0")
        for hold in (20, 60):
            print(pf.fmt(pf.simulate(e, hold, 10), name))
        r = pf.simulate(e, 20, 10)
        print("   每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in r["yearly"].items()))
    r = pf.simulate(pd.DataFrame(columns=["code", "date"]), 20, 10)
    print("   加權指數每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in r["yearly_taiex"].items()))


if __name__ == "__main__":
    main()
