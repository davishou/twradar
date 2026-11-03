"""量價近似策略（只有日資料）：python -m research.pv_bt

A. 爆量急拉但收不住 → 放空
   當天成交量 ≥ 前 5 日均量 × K、盤中最高漲 ≥ 5%、收盤沒漲停、且收盤吐回一半以上漲幅（上影線長）。
   收盤放空或隔天開盤放空，持有 1/3/5/10 天。
B. 連續 ≥3 天一價跌停後打開
   進貨型：開盤就不是跌停（開盤 ≥ 平盤，代表跌停賣單在開盤就被一次掃掉）→ 收盤買
   出貨型：開盤仍在跌停、盤中打開、收盤長紅（收盤 ≥ 平盤 +3%）且量大 → 隔天開盤放空
   注意：連續跌停的股票很多是全額交割股，不能融券，放空版本實際上常做不到。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from research import event_bt as eb


def main(argv):
    out = []
    p = lambda s: (print(s), out.append(s))  # noqa: E731
    M = eb.mats()
    C, O, H, L, R, LU, V, VO = (M[k] for k in ("close", "open", "high", "low", "ref", "lu", "value", "volume"))
    days = C.index
    lim = pd.Series(np.where(days >= pd.Timestamp("2015-06-01"), 0.10, 0.07), index=days)
    val20 = V.rolling(20, min_periods=10).mean().shift(1)
    v5 = VO.rolling(5, min_periods=3).mean().shift(1)
    is_lu = (C >= LU - 1e-9) & LU.notna()
    di = {d: i for i, d in enumerate(days)}

    def D(i):
        return days[min(i, len(days) - 1)]

    # ---------- A ----------
    up_hi = H / R - 1
    gave = (H - C) / (H - R).where(H > R)
    for K in (3, 5):
        for mv in (3e7, 1e8):
            sig = (VO >= v5 * K) & (up_hi >= 0.05) & ~is_lu & (gave >= 0.5) & (val20 >= mv)
            st = sig.stack()
            st = st[st]
            idx = [di[d] for d in st.index.get_level_values(0)]
            codes = st.index.get_level_values(1).to_numpy()
            p(f"\n===== A 爆量急拉收不住：量 ≥{K} 倍、成交 ≥{mv/1e8:g} 億，{len(idx)} 次 =====")
            for entry in ("當天收盤空", "隔天開盤空"):
                for n in (1, 3, 5, 10):
                    if entry == "當天收盤空":
                        d0, f0 = [D(i) for i in idx], "close"
                        d1 = [D(i + n) for i in idx]
                    else:
                        d0, f0 = [D(i + 1) for i in idx], "open"
                        d1 = [D(i + n) for i in idx]
                    t = pd.DataFrame({"code": codes, "d0": d0, "f0": f0, "d1": d1, "f1": "close", "side": -1})
                    p(eb.fmt(eb.run(t, slots=10, slip=0.003, label=f"A K{K} {mv/1e8:g}億 {entry} 持有{n}天")))
            # 方向檢查：同樣訊號改做多（看是不是反而會漲）
            t = pd.DataFrame({"code": codes, "d0": [D(i) for i in idx], "f0": "close", "d1": [D(i + 5) for i in idx],
                              "f1": "close", "side": 1})
            p(eb.fmt(eb.run(t, slots=10, slip=0.003, label=f"A K{K} {mv/1e8:g}億 對照：改做多 5 天")))

    # ---------- B ----------
    ld = R * (1 - lim.values[:, None])
    one_ld = (H <= L + 1e-9) & (C <= ld * 1.006) & C.notna()
    run = one_ld.astype(int)
    streak = run.groupby((run == 0).cumsum()).cumsum() if False else None
    arr = one_ld.to_numpy()
    n, m = arr.shape
    cnt = np.zeros_like(arr, dtype=np.int16)
    for i in range(n):
        cnt[i] = np.where(arr[i], (cnt[i - 1] + 1) if i else 1, 0)
    prev3 = np.vstack([np.zeros((1, m), bool), cnt[:-1] >= 3])
    Oa, Ca, Ra, LDa = O.to_numpy(), C.to_numpy(), R.to_numpy(), ld.to_numpy()
    Va = VO.to_numpy()
    opened = prev3 & ~arr & np.isfinite(Ca)
    buy_t = opened & (Oa >= Ra * 0.999)                                   # 進貨型：開盤就回到平盤以上
    vol_ld = pd.DataFrame(np.where(arr, Va, np.nan)).rolling(5, min_periods=1).mean().shift(1).to_numpy()
    sell_t = opened & (Oa <= LDa * 1.006) & (Ca >= Ra * 1.03)            # 出貨型：開在跌停、收長紅
    for nm, mask, side, entry in (("進貨型（開盤就跳回平盤以上）", buy_t, 1, "當天收盤買"),
                                  ("出貨型（跌停打開收長紅）", sell_t, -1, "隔天開盤空"),
                                  ("出貨型 對照：改做多", sell_t, 1, "當天收盤買"),
                                  ("所有跌停打開", opened, 1, "當天收盤買")):
        ii, jj = np.where(mask)
        codes = C.columns.to_numpy()[jj]
        p(f"\n===== B {nm}：{len(ii)} 次 =====")
        for hold in (1, 5, 10, 20):
            if entry == "當天收盤買":
                d0, f0 = [D(i) for i in ii], "close"
            else:
                d0, f0 = [D(i + 1) for i in ii], "open"
            t = pd.DataFrame({"code": codes, "d0": d0, "f0": f0, "d1": [D(i + hold) for i in ii], "f1": "close", "side": side})
            p(eb.fmt(eb.run(t, slots=10, slip=0.003, label=f"B {nm} {entry} 持有{hold}天")))
            p(eb.fmt(eb.run(t, slots=None, slip=0.003, label=f"B {nm} {entry} 持有{hold}天（每筆都做）")))
    (eb.pf.OUT / "pv_bt.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
