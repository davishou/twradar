"""漲停隔日沖：漲停當天收盤買（假設排得到）、隔天開盤賣。python -m research.limitup_overnight

分組（只有日資料，用開高低收判斷）：
  一字    ：最低價＝漲停價（整天鎖死）
  開盤即漲停：開盤＝漲停價、盤中有打開、收盤又鎖回
  盤中才鎖 ：開盤低於漲停、收盤鎖住
另分：第 1 根漲停 vs 連續第 2 根以上；可選收盤放空等值大盤、隔天開盤回補（用加權指數開盤代替期貨）。
注意：一字漲停實際上很難排到，結果偏樂觀。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from research import event_bt as eb


def events(min_val=3e7):
    M = eb.mats()
    C, O, L, LU, V = M["close"], M["open"], M["low"], M["lu"], M["value"]
    days = C.index
    is_lu = (C >= LU - 1e-9) & LU.notna()
    one = is_lu & (L >= LU - 1e-9)
    open_lu = is_lu & ~one & (O >= LU - 1e-9)
    val20 = V.rolling(20, min_periods=10).mean().shift(1)
    streak = is_lu.astype(int).groupby((~is_lu).cumsum()).cumsum() if False else None
    prev_lu = is_lu.shift(1, fill_value=False)
    st = is_lu.stack()
    st = st[st]
    df = st.reset_index()[["date", "code"]]
    g = np.select([one.stack()[st.index].to_numpy(), open_lu.stack()[st.index].to_numpy()], ["一字", "開盤即漲停"], "盤中才鎖")
    df["grp"] = g
    df["first"] = ~prev_lu.stack()[st.index].to_numpy()
    df["val"] = val20.stack().reindex(st.index).to_numpy()
    df = df[df["val"] >= min_val]
    nx = {d: days[i + 1] for i, d in enumerate(days[:-1])}
    df["d1"] = df["date"].map(nx)
    return df.dropna(subset=["d1"]), days


def main(argv):
    out = []
    p = lambda s: (print(s), out.append(s))  # noqa: E731
    tx = eb.taiex()
    for mv in (3e7, 1e8):
        ev, days = events(mv)
        txo, txc = tx["open"].reindex(days), tx["close"].reindex(days)
        hedge = -(txo.reindex(ev.d1).to_numpy() / txc.reindex(ev.date).to_numpy() - 1) - 0.00005
        p(f"\n===== 成交值門檻 {mv/1e8:g} 億：漲停 {len(ev)} 次 =====")
        base = pd.DataFrame({"code": ev.code.to_numpy(), "d0": ev.date.to_numpy(), "f0": "close", "d1": ev.d1.to_numpy(),
                             "f1": "open", "side": 1})
        for grp in ("一字", "開盤即漲停", "盤中才鎖", "全部"):
            for fst in ("第1根", "連續", "不分"):
                m = np.ones(len(ev), bool)
                if grp != "全部":
                    m &= (ev.grp == grp).to_numpy()
                if fst == "第1根":
                    m &= ev["first"].to_numpy()
                elif fst == "連續":
                    m &= ~ev["first"].to_numpy()
                t = base[m].copy()
                raw = (eb.mats()["adj_open"].stack().reindex(pd.MultiIndex.from_arrays([t.d1, t.code])).to_numpy() /
                       eb.mats()["adj"].stack().reindex(pd.MultiIndex.from_arrays([t.d0, t.code])).to_numpy() - 1)
                raw = raw[np.isfinite(raw)]
                p(f"[{grp} {fst}] {m.sum()} 次：隔天開盤（未扣成本）平均 {raw.mean():+.2%} 中位 {np.median(raw):+.2%} 開高比例 {(raw > 0).mean():.0%}")
                if grp == "全部" and fst != "不分":
                    continue
                for hg in (False, True):
                    tt = t.assign(hedge=hedge[m] if hg else 0.0)
                    for slip in (0.001, 0.003):
                        p(eb.fmt(eb.run(tt, slots=10, slip=slip, label=f"  {grp} {fst} {'避險' if hg else '不避險'} 10份 滑價{slip:.1%}")))
    (eb.pf.OUT / "limitup_overnight.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
