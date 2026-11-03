"""上櫃全額交割打入／恢復（從重大訊息整理）：python -m research.fulldel_tpex 重大訊息資料夾
新打入＝主旨有「變更交易方法／全額交割」且沒有「繼續、仍、維持、取消、澄清」；恢復＝主旨有「恢復…普通交割／交易方法」。
生效日：內文「自 X 年 X 月 X 日起」，抓不到就用公告日的下一個交易日。進出場同 research.fulldel_bt。
注意：重大訊息掃描仍有約三成年份未完成，樣本不完整。"""
import glob
import re
import sys

import pandas as pd

from research import event_bt as eb
from research.tender_bt import ROC, _d


def main(argv):
    raw = pd.concat([pd.read_csv(f, dtype=str) for f in glob.glob(f"{argv[0]}/material_*.csv")])
    t = raw[(raw.market == "TPEX") & raw.code.str.fullmatch(r"\d{4}", na=False)].copy()
    t["subject"] = t.subject.fillna("").str.replace(r"\s+", "", regex=True)
    ins = t.subject.str.contains("變更交易方法|全額交割") & ~t.subject.str.contains("繼續|仍|維持|取消|澄清|恢復")
    rec = t.subject.str.contains(r"恢復.{0,10}(?:普通交割|交易方法)", regex=True)
    rows = []
    for m, evt in ((ins, "打入"), (rec, "恢復")):
        for r in t[m].itertuples():
            b = re.sub(r"\s+", "", str(r.body))
            x = re.search(r"自" + ROC + r"起", r.subject + b)
            eff = _d(*x.groups()) if x else None
            rows.append({"code": r.code, "event": evt, "ann": pd.Timestamp(r.date), "eff": pd.Timestamp(eff) if eff else None})
    E = pd.DataFrame(rows).drop_duplicates(["code", "event", "ann"])
    M = eb.mats()
    days = M["adj"].index
    out = []
    E["i"] = [days.searchsorted(e if e is not None and not pd.isna(e) else a + pd.Timedelta(days=1)) for e, a in zip(E.eff, E.ann)]
    E = E[(E.i < len(days)) & E.code.isin(M["adj"].columns)].drop_duplicates(["code", "event", "i"])
    E = E.sort_values(["code", "event", "i"])
    E = E[E.groupby(["code", "event"]).i.diff().fillna(999) > 30]
    D = lambda i: days[max(0, min(i, len(days) - 1))]  # noqa: E731
    for evt, side in (("打入", -1), ("恢復", 1)):
        e1 = E[E.event == evt]
        out.append(f"上櫃 {evt}：{len(e1)} 筆（{days[e1.i.min()].year}~{days[e1.i.max()].year}）")
        for n in (5, 20, 60):
            tt = pd.DataFrame({"code": e1.code.to_numpy(), "d0": [D(i - 1) for i in e1.i], "f0": "close",
                               "d1": [D(i + n - 1) for i in e1.i], "f1": "close", "side": side})
            out.append(eb.fmt(eb.run(tt, slots=10, slip=0.003, label=f"上櫃 {evt} 生效前一天收盤{'放空' if side < 0 else '買進'} → 第{n}天 10份")).split("\n")[0])
    print("\n".join(out))
    (eb.pf.OUT / "fulldel_tpex.txt").write_text("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
