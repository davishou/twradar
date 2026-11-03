"""全額交割（變更交易方法）打入與恢復：python -m research.fulldel_bt [twse_full_events.csv]

資料：tools/backfill_bt.py twse_full（證交所 fullDelivery/TWT85U 每週快照，名單有變再逐日補）→ 事件日＝第一天出現在（或消失於）名單的交易日。
公告通常在生效前 1～2 個交易日的盤後，所以「生效前一天收盤」是公告後第一個能動作的時間點（保守）。
打入：
  a. 生效前一天收盤放空（公告後）→ 生效後 1／5／20 天收盤回補（※打入後不能融券，既有空單能否留到回補要看券商；結果當作股價方向參考）
  b. 生效前 3 天收盤放空（＝財報一出來就判斷會被打入，書上的做法）→ 同上
  c. 對照：生效前一天收盤買進
恢復：生效前一天收盤買進（公告後），持有 5／20／60 天。
法規分期（淨值條件）：2026 年現行＝淨值低於股本 1/2（每股 10 元面額＝5 元）打入、低於 3/10 加分盤；
淨值回到 1/2 以上且較前期增加（部分情況要求最近 2 期、淨值逾 3 億）才恢復。2020/4/1 起退場機制：變更交易滿 3 年未改善就停止買賣。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from research import event_bt as eb


def main(argv):
    path = Path(argv[0]) if argv else Path("/tmp/btdata/twse_full_events.csv")
    ev = pd.read_csv(path, dtype={"code": str}, parse_dates=["date", "prev"])
    ev = ev[ev.code.str.fullmatch(r"\d{4}")]
    M = eb.mats()
    days, C = M["adj"].index, M["close"]
    out = [f"事件 {len(ev)} 筆：{ev.event.value_counts().to_dict()}；{ev.date.min().date()}~{ev.date.max().date()}"]
    # 快照間隔超過 7 天的事件日期不準，標記
    ev["gap"] = (ev.date - ev.prev).dt.days
    out.append(f"日期精準（前一張快照在 4 天內）：{(ev.gap <= 4).mean():.0%}")

    def idx(d):
        i = days.searchsorted(d)
        return i if i < len(days) else None

    def D(i):
        return days[max(0, min(i, len(days) - 1))]
    rows = []
    for r in ev.itertuples(index=False):
        i = idx(r.date)
        if i is None or i < 5 or r.code not in C.columns:
            continue
        rows.append({"code": r.code, "event": r.event, "i": i, "gap": r.gap, "year": r.date.year})
    E = pd.DataFrame(rows)
    for evt, side_list in (("打入", ((-1, 1, "公告後（生效前一天收盤）放空"), (-1, 3, "生效前 3 天收盤放空"), (1, 1, "對照：生效前一天收盤買"))),
                           ("恢復", ((1, 1, "公告後（生效前一天收盤）買進"), (1, 3, "生效前 3 天收盤買進")))):
        e1 = E[(E.event == evt) & (E.gap <= 10)]
        out.append(f"\n===== {evt}：{len(e1)} 筆 =====")
        for side, k, nm in side_list:
            for n in (1, 5, 20, 60):
                t = pd.DataFrame({"code": e1.code.to_numpy(), "d0": [D(i - k) for i in e1.i], "f0": "close",
                                  "d1": [D(i + n - 1) for i in e1.i], "f1": "close", "side": side})
                for slots, lab in ((10, "10份"), (None, "每筆都做")):
                    out.append(eb.fmt(eb.run(t, slots=slots, slip=0.003, label=f"{evt} {nm} → 生效後第{n}天收盤 {lab}")))
        # 分期
        for a, b in ((2004, 2012), (2013, 2019), (2020, 2026)):
            e2 = e1[e1.year.between(a, b)]
            if len(e2) < 5:
                continue
            side, k = (-1, 1) if evt == "打入" else (1, 1)
            t = pd.DataFrame({"code": e2.code.to_numpy(), "d0": [D(i - k) for i in e2.i], "f0": "close",
                              "d1": [D(i + 19) for i in e2.i], "f1": "close", "side": side})
            out.append(eb.fmt(eb.run(t, slots=None, slip=0.003, label=f"{evt} {a}~{b} 公告後進場 持有20天 每筆都做")))
    print("\n".join(x for x in out if "每年" not in x))
    (eb.pf.OUT / "fulldel_bt.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
