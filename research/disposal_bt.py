"""處置股策略回測：python -m research.disposal_bt

資料：data/archive/punish（上市 2004 起；上櫃依回補進度）。公布日＝announce（盤後公布），處置期間 start~end。
S1 第二次處置（或 20 分鐘以上撮合）放空：
   a. 公布當天收盤放空（＝事先預測到會被處置；處置條件是公開規則，可以預先算）
   b. 處置第一天開盤放空（公布後才動作）
   出場：隔天開盤、隔天收盤、處置最後一天收盤、進場後 5／10 個交易日收盤
   濾網：公布當天「不是一字漲停」（書上的條件：還鎖死很多張就不敢放空）
S1' 第一次處置對照。
S2 處置最後一天收盤買，解除後第 1／5 天收盤賣。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from pipeline import backtest as bt
from research import event_bt as eb


def load():
    import glob
    fs = sorted(glob.glob(str(bt.ARCHIVE / "punish" / "*" / "*.csv.gz")))
    df = pd.concat([pd.read_csv(f, dtype=str) for f in fs], ignore_index=True)
    df = df[df["code"].str.fullmatch(r"\d{4}")]
    for c in ("announce", "start", "end"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["minutes"] = pd.to_numeric(df["minutes"], errors="coerce")
    df["times"] = pd.to_numeric(df["times"], errors="coerce")
    df["second"] = (df["times"] >= 2) | (df["minutes"] >= 20)
    return df.dropna(subset=["announce", "start", "end"]).drop_duplicates(["code", "start"])


def main(argv):
    out = []
    p = lambda s: (print(s), out.append(s))  # noqa: E731
    df = load()
    M = eb.mats()
    days = M["adj"].index
    C, L, LU = M["close"], M["low"], M["lu"]
    one = (C >= LU - 1e-9) & (L >= LU - 1e-9)
    di = {d: i for i, d in enumerate(days)}

    def on_or_after(d):
        i = days.searchsorted(d)
        return days[i] if i < len(days) else None

    rows = []
    for r in df.itertuples(index=False):
        a = on_or_after(r.announce)
        s = on_or_after(r.start)
        e = days[days.searchsorted(r.end, side="right") - 1] if r.end >= days[0] else None
        if a is None or s is None or e is None or r.code not in C.columns or s <= a:
            continue
        ia, is_, ie = di[a], di[s], di[e]
        if ie < is_:
            continue
        rows.append({"code": r.code, "market": r.market, "a": a, "s": s, "e": e, "ia": ia, "is": is_, "ie": ie,
                     "second": bool(r.second), "one": bool(one.at[a, r.code]) if a in one.index else False})
    ev = pd.DataFrame(rows)
    p(f"處置事件 {len(ev)} 筆（第二次 {ev.second.sum()}）；市場 {ev.market.value_counts().to_dict()}；{ev.a.min().date()}~{ev.a.max().date()}")

    def D(i):
        return days[min(i, len(days) - 1)]
    for sec, nm in ((True, "第二次處置"), (False, "第一次處置")):
        e0 = ev[(ev.second == sec)]
        for flt, fn in ((False, "全部"), (True, "排除公布日一字漲停")):
            e1 = e0[~e0.one] if flt else e0
            for entry in ("公布日收盤空", "處置首日開盤空"):
                for ex in ("隔天開盤", "隔天收盤", "處置最後一天收盤", "5天", "10天"):
                    if entry == "公布日收盤空":
                        d0, f0, base = [D(i) for i in e1.ia], "close", e1.ia.to_numpy()
                    else:
                        d0, f0, base = [D(i) for i in e1["is"]], "open", e1["is"].to_numpy()
                    if ex == "隔天開盤":
                        d1, f1 = [D(i + 1) for i in base], "open"
                    elif ex == "隔天收盤":
                        d1, f1 = [D(i + 1) for i in base], "close"
                    elif ex == "處置最後一天收盤":
                        d1, f1 = [D(i) for i in e1.ie], "close"
                    else:
                        n = int(ex[:-1])
                        d1, f1 = [D(i + n) for i in base], "close"
                    t = pd.DataFrame({"code": e1.code.to_numpy(), "d0": d0, "f0": f0, "d1": d1, "f1": f1, "side": -1})
                    r = eb.run(t, slots=10, slip=0.003, label=f"{nm} {fn} {entry} → {ex}")
                    p(eb.fmt(r))
    # S2：處置最後一天收盤買
    for sec, nm in ((True, "第二次處置"), (False, "第一次處置"), (None, "全部處置")):
        e0 = ev if sec is None else ev[ev.second == sec]
        for n in (1, 5, 10):
            t = pd.DataFrame({"code": e0.code.to_numpy(), "d0": [D(i) for i in e0.ie], "f0": "close",
                              "d1": [D(i + n) for i in e0.ie], "f1": "close", "side": 1})
            p(eb.fmt(eb.run(t, slots=10, slip=0.003, label=f"解除前買 {nm} 處置最後一天收盤買 → 解除後第{n}天收盤")))
        t = pd.DataFrame({"code": e0.code.to_numpy(), "d0": [D(i) for i in e0.ie], "f0": "close",
                          "d1": [D(i + 1) for i in e0.ie], "f1": "open", "side": 1})
        p(eb.fmt(eb.run(t, slots=10, slip=0.003, label=f"解除前買 {nm} → 解除當天開盤賣")))
    (eb.pf.OUT / "disposal_bt.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
