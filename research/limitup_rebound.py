"""漲停研究新發現的檢查：股價離 120 日高點跌 38% 以上，又在『全市場大漲停日』漲停（跌深＋普漲反彈）

事件集中在少數大反彈的日子，所以同時看「以交易日為單位」的結果與資金曲線
python -m research.limitup_rebound
"""
from __future__ import annotations

from pipeline import backtest as bt
from research import portfolio as pf


def main():
    ev = bt.limitup_events()
    base = ~ev["next_open_lu"] & ~ev["next_is_lu"]
    groups = {
        "跌深（離120日高點≤0.62）＋全市場漲停≥115 家": base & (ev["hi120"] <= 0.62) & (ev["mkt_n"] >= 115),
        "跌深＋同產業漲停≥10 家": base & (ev["hi120"] <= 0.62) & (ev["ind_n"] >= 10),
        "跌深（不看大盤）": base & (ev["hi120"] <= 0.62),
        "全市場漲停≥115 家（不看跌深）": base & (ev["mkt_n"] >= 115),
    }
    for name, m in groups.items():
        e = ev[m.fillna(False)]
        days = e.groupby("date")["xc20"].median().dropna()
        print(f"\n== {name}：{len(e)} 次、{e['date'].nunique()} 個交易日 ==")
        print(f"  以交易日為單位：20 日超額中位數 > 0 的天數比例 {(days > 0).mean():.0%}（共 {len(days)} 天）；"
              f"最常出現的日子：{', '.join(str(d.date()) for d in e['date'].value_counts().head(5).index)}")
        x = pf.events_at_next_close(e[["code", "date"]].rename(columns={"date": "d0"}), when="d0")
        for hold in (20, 60):
            print(pf.fmt(pf.simulate(x, hold, 10), "  10份"))
            print(pf.fmt(pf.simulate(x, hold, None), "  全買"))
        r = pf.simulate(x, 20, None)
        print("   全買持有20日 每年：" + "  ".join(f"{y[2:]} {v:+.0%}" for y, v in r["yearly"].items()))


if __name__ == "__main__":
    main()
