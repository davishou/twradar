"""多策略組合：一筆資金同時做主力（營收加速）＋短線事件策略。python -m research.multi_strat [btdata 資料夾]

做法：資金分 K 份（每份＝當時總資金 ÷ K），每筆交易用一份；份數滿了，新訊號跳過。
同一天的訊號依優先順序搶份數：短線事件先（持有短、每日期望高），主力營收最後（同一天內依「最接近一年高點」排）。
期間 2013-02 起（主力營收資料從 2013 起），手續費看 FEE_DISC（建議 0.3），每邊滑價 0.3%。
做不做得到的打折（敏感度）：
  漲停隔日沖：只有 fill 比例的訊號買得到（隨機），且每筆再扣 penalty（排到的往往是隔天會開低的）
  全額交割放空：只有 fill 比例借得到券（隨機）
"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research import disposal_bt, event_bt as eb, exdiv, robust_check as rc, fin_signals as fs, portfolio as pf
from research.fulldel_bt import events_from_snaps
from research.tender_bt import ROC, _d

START = "2013-02-01"


def D(days, i):
    return days[max(0, min(int(i), len(days) - 1))]


def core_trades(days):
    near, liq = rc.strength()
    r, rs = fs.revenue()
    e = pf.events_at_next_close(r.loc[rs["rev_accel"].fillna(False), ["code", "deadline"]])
    e = e[e["date"] >= START].copy()
    e["score"], e["liq"] = rc.lookup(near, e), rc.lookup(liq, e)
    e = e[(e["liq"].fillna(0) >= 1e8) & ~rc.excl_mask(e)]
    di = {d: i for i, d in enumerate(days)}
    e = e[e.date.isin(di)]
    return pd.DataFrame({"code": e.code, "d0": e.date, "f0": "close", "d1": [D(days, di[d] + 60) for d in e.date], "f1": "close",
                         "side": 1, "score": e["score"].fillna(-1).to_numpy(), "label": "主力：營收加速"})


def exdiv_trades(days, tx):
    ev, _ = exdiv.events(1e8)
    txo, txc = tx["open"].reindex(days), tx["close"].reindex(days)
    a = ev[ev.y >= 0.06]
    d0 = [days[i - 1] for i in a.i]
    A = pd.DataFrame({"code": a.code.to_numpy(), "d0": d0, "f0": "close", "d1": a.ex.to_numpy(), "f1": "open", "side": 1,
                      "hedge": -(txo.reindex(a.ex).to_numpy() / txc.reindex(d0).to_numpy() - 1) - 0.00005, "label": "除權息前一天買"})
    b = ev[ev.y >= 0.04]
    d0 = [days[i - 11] for i in b.i]
    d1 = [days[i - 1] for i in b.i]
    B = pd.DataFrame({"code": b.code.to_numpy(), "d0": d0, "f0": "close", "d1": d1, "f1": "close", "side": 1,
                      "hedge": -(txc.reindex(d1).to_numpy() / txc.reindex(d0).to_numpy() - 1) - 0.0001, "label": "除權息前10天買"})
    return [A, B]


def disposal_trades(days):
    df = disposal_bt.load()
    M = eb.mats()
    C, L, LU = M["close"], M["low"], M["lu"]
    one = (C >= LU - 1e-9) & (L >= LU - 1e-9)
    rows = []
    for r in df[df.second].itertuples(index=False):
        i = days.searchsorted(r.announce)
        if i >= len(days) - 6 or r.code not in C.columns or days[i] >= r.start:
            continue
        if bool(one.iat[i, C.columns.get_loc(r.code)]):
            continue
        rows.append({"code": r.code, "d0": days[i], "f0": "close", "d1": D(days, i + 5), "f1": "close", "side": -1, "label": "第二次處置前放空"})
    return pd.DataFrame(rows)


def dumpbuy_trades(days):
    M = eb.mats()
    C, O, H, L, R = (M[k] for k in ("close", "open", "high", "low", "ref"))
    lim = np.where(days >= pd.Timestamp("2015-06-01"), 0.10, 0.07)[:, None]
    ld = R.to_numpy() * (1 - lim)
    arr = (H.to_numpy() <= L.to_numpy() + 1e-9) & (C.to_numpy() <= ld * 1.006) & np.isfinite(C.to_numpy())
    cnt = np.zeros(arr.shape, dtype=np.int16)
    for i in range(len(arr)):
        cnt[i] = np.where(arr[i], (cnt[i - 1] + 1) if i else 1, 0)
    prev3 = np.vstack([np.zeros((1, arr.shape[1]), bool), cnt[:-1] >= 3])
    buy = prev3 & ~arr & np.isfinite(C.to_numpy()) & (O.to_numpy() >= R.to_numpy() * 0.999)
    ii, jj = np.where(buy)
    return pd.DataFrame({"code": C.columns.to_numpy()[jj], "d0": [days[i] for i in ii], "f0": "close",
                         "d1": [D(days, i + 20) for i in ii], "f1": "close", "side": 1, "label": "跌停打開進貨型買"})


def fulldel_trades(days, src: Path):
    ev = events_from_snaps(src / "twse_full_snaps.json")
    ev = ev[ev.event == "打入"]
    rows = [(r.code, days.searchsorted(r.date)) for r in ev.itertuples()]
    raw = pd.concat([pd.read_csv(f, dtype=str) for f in glob.glob(str(src / "mat" / "material_*.csv"))])
    t = raw[(raw.market == "TPEX") & raw.code.str.fullmatch(r"\d{4}", na=False)]
    sj = t.subject.fillna("").str.replace(r"\s+", "", regex=True)
    ins = sj.str.contains("變更交易方法|全額交割") & ~sj.str.contains("繼續|仍|維持|取消|澄清|恢復")
    seen = {}
    for r, s in zip(t[ins].itertuples(), sj[ins]):
        x = re.search(r"自" + ROC + r"起", s + re.sub(r"\s+", "", str(r.body)))
        eff = _d(*x.groups()) if x else None
        i = days.searchsorted(pd.Timestamp(eff) if eff else pd.Timestamp(r.date) + pd.Timedelta(days=1))
        if r.code in seen and abs(i - seen[r.code]) < 30:
            continue
        seen[r.code] = i
        rows.append((r.code, i))
    cols = eb.mats()["adj"].columns
    rows = [(c, i) for c, i in rows if 1 <= i < len(days) - 1 and c in cols]
    return pd.DataFrame({"code": [c for c, _ in rows], "d0": [days[i - 1] for _, i in rows], "f0": "close",
                         "d1": [D(days, i + 19) for _, i in rows], "f1": "close", "side": -1, "label": "打入全額交割放空"})


def limitup_trades(days):
    M = eb.mats()
    C, L, LU = M["close"], M["low"], M["lu"]
    is_lu = (C >= LU - 1e-9) & LU.notna()
    one = is_lu & (L >= LU - 1e-9)
    val20 = M["value"].rolling(20, min_periods=10).mean().shift(1)
    sig = is_lu & is_lu.shift(1, fill_value=False) & (val20 >= 1e8)        # 連續第 2 根以上（一字或盤中鎖）
    st = sig.stack()
    st = st[st]
    di = {d: i for i, d in enumerate(days)}
    d0 = st.index.get_level_values(0)
    return pd.DataFrame({"code": st.index.get_level_values(1), "d0": d0, "f0": "close", "d1": [D(days, di[d] + 1) for d in d0],
                         "f1": "open", "side": 1, "label": "連續漲停隔日沖"})


def main(argv):
    src = Path(argv[0]) if argv else Path("/tmp/btdata")
    M = eb.mats()
    days = M["adj"].index
    tx = eb.taiex()
    core = core_trades(days)
    ev = {
        "除權息": exdiv_trades(days, tx),
        "處置": [disposal_trades(days)],
        "跌停進貨": [dumpbuy_trades(days)],
        "全額交割": [fulldel_trades(days, src)],
        "漲停": [limitup_trades(days)],
    }
    out = []
    p = lambda s: (print(s), out.append(s))  # noqa: E731

    def build(keys, fill_lu=1.0, pen_lu=0.0, fill_fd=1.0, seed=0):
        parts = [core]
        for k in keys:
            for t in ev[k]:
                t = t[t.d0 >= START].copy()
                if k == "漲停":
                    t = t.sample(frac=fill_lu, random_state=seed)
                    t["hedge"] = -pen_lu
                if k == "全額交割":
                    t = t.sample(frac=fill_fd, random_state=seed)
                t["score"] = 100.0
                parts.append(t)
        return pd.concat(parts, ignore_index=True)

    def show(tr, K, lab):
        r = eb.run(tr, slots=K, slip=0.003, start=START, label=lab)
        p(eb.fmt(r))
        p("     各策略：" + "；".join(f"{k} {v['n']} 筆 期望 {v['mean']:+.1%} 勝率 {v['win']:.0%} 貢獻約 {v['n'] * v['mean'] / K:+.0%}"
                                    for k, v in sorted(r["by"].items(), key=lambda kv: -kv[1]["n"] * kv[1]["mean"])))
        return r

    p("== 單獨主力 ==")
    show(build([]), 20, "主力 營收加速 20 份")
    safe = ["除權息", "處置", "跌停進貨"]
    for K in (20, 25, 30):
        p(f"\n== 主力＋可搭配（除權息、第二次處置、跌停進貨）K={K} ==")
        show(build(safe), K, f"主力＋可搭配 {K} 份")
    p("\n== 再加：打入全額交割放空（借得到券比例）==")
    for f in (1.0, 0.5, 0.25):
        show(build(safe + ["全額交割"], fill_fd=f), 25, f"＋全額交割 借券成功 {f:.0%}")
    p("\n== 再加：連續漲停隔日沖（買得到比例、排到時每筆再扣）==")
    for f, pen in ((1.0, 0.0), (0.3, 0.0), (0.3, 0.01), (0.3, 0.02), (0.1, 0.02)):
        show(build(safe + ["全額交割", "漲停"], fill_lu=f, pen_lu=pen, fill_fd=0.5), 25, f"＋漲停 買得到 {f:.0%} 每筆扣 {pen:.0%}（全額交割 50%）")
    (eb.pf.OUT / "multi_strat.txt").write_text("\n".join(out))
    return 0


if __name__ == "__main__" and not (len(sys.argv) > 1 and sys.argv[1] in ("kelly", "levstop")):
    sys.exit(main(sys.argv[1:]))


# ---------------------------------------------------------------- 凱利公式
def tender_trades(days):
    E = pd.read_csv(eb.pf.OUT / "tender_events.csv", dtype={"code": str})
    E = E[E.full.astype(str).eq("True") & (E.ratio >= 0.97)]
    return pd.DataFrame({"code": E.code, "d0": [days[int(i)] for i in E.i], "f0": "close",
                         "d1": [D(days, int(i) + 2) for i in E.i], "f1": "close", "side": -1, "label": "公開收購截止前放空"})


def run_sized(tr, mode, base=0.04, frac=1.0, min_n=30, slip=0.003, start=START, cap_one=1.0,
              lev=1.0, fin_rate=0.065, stop=None, stop_core_only=False):
    """每筆部位＝當時總資金 × f。mode='equal'：f=base；mode='kelly'：f＝frac×(勝率−敗率÷盈虧比)，
    勝率、盈虧比只用『進場日之前已經出場』的同策略交易估計（避免偷看），不到 min_n 筆先用 base。
    所有部位合計最多 100% 資金（不融資），不夠就只買剩下的（<1% 跳過）。"""
    M = eb.mats()
    C, O = M["adj"], M["adj_open"]
    days = C.index[C.index >= pd.Timestamp(start)]
    di = {d: i for i, d in enumerate(days)}
    col = {c: i for i, c in enumerate(C.columns)}
    Ca, Oa = C.loc[days].to_numpy(), O.loc[days].to_numpy()
    if "hedge" not in tr:
        tr = tr.assign(hedge=0.0)
    t = tr[tr.code.isin(col) & tr.d0.isin(di) & tr.d1.isin(di)].sort_values(["d0", "score"], ascending=[True, False], kind="stable")
    n = len(days)
    contrib = np.zeros(n)
    expo = np.zeros(n + 1)
    hist: dict = {}          # label -> list of (exit_i, ret)
    open_w = []              # (exit_i, w)
    trades, fs_used = [], {}
    for row in t.itertuples(index=False):
        i, k, j = di[row.d0], di[row.d1], col[row.code]
        if k < i or (k == i and row.f0 == row.f1):
            continue
        p0 = Oa[i, j] if row.f0 == "open" else Ca[i, j]
        p1 = Oa[k, j] if row.f1 == "open" else Ca[k, j]
        if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0):
            continue
        # 停損：收盤時這筆累計虧損 ≥ stop，隔天開盤出場
        if stop and (not stop_core_only or str(row.label).startswith("主力")):
            gg = 1.0
            x0 = i + 1 if row.f0 == "close" else i
            prev = p0
            for x in range(x0, k):
                cx = Ca[x, j]
                if np.isfinite(cx):
                    gg *= 1 + np.clip(cx / prev - 1, -0.11, 0.11)
                    prev = cx
                if row.side * (gg - 1) <= -stop:
                    k = x + 1
                    p1 = Oa[k, j] if np.isfinite(Oa[k, j]) else Ca[k, j]
                    row = row._replace(f1="open")
                    break
            if not np.isfinite(p1):
                continue
        open_w = [(e, w) for e, w in open_w if e >= i]
        room = lev - sum(w for _, w in open_w)
        if mode == "equal":
            f = base * lev
        else:
            h = [r for e, r in hist.get(row.label, []) if e < i]
            if len(h) < min_n:
                f = base
            else:
                h = np.array(h)
                p = (h > 0).mean()
                R = h[h > 0].mean() / -h[h <= 0].mean() if (h <= 0).any() and (h > 0).any() else 1
                f = max(0.0, frac * (p - (1 - p) / R))
        if mode != "equal":
            f *= lev
        f = min(f, cap_one * lev, room)
        if f < 0.01:
            continue
        s = row.side
        buy_c, sell_c = eb.FEE + slip, eb.FEE + eb.TAX + slip + (eb.SHORT_FEE if s < 0 else 0)
        if row.f0 == "close":
            idx = list(range(i + 1, k + 1))
            path = [p0] + [Ca[x, j] for x in range(i + 1, k)] + [p1]
        else:
            idx = list(range(i, k + 1))
            path = [p0] + [Ca[x, j] for x in range(i, k)] + [p1]
        path = pd.Series(path, dtype=float).ffill().to_numpy()
        rets = np.clip(path[1:] / path[:-1] - 1, -0.11, 0.11)
        hgd = row.hedge if np.isfinite(row.hedge) else 0.0
        for x, rr in zip(idx, rets):
            contrib[x] += f * s * rr
        contrib[k] += f * hgd
        contrib[i] -= f * (buy_c if s > 0 else sell_c)
        contrib[k] -= f * (sell_c if s > 0 else buy_c)
        expo[i] += f
        expo[k + 1] -= f
        g = float(np.prod(1 + rets))
        ret = (((g * (1 - sell_c)) / (1 + buy_c) - 1) if s > 0 else ((1 - sell_c) - g * (1 + buy_c))) + hgd
        hist.setdefault(row.label, []).append((k, ret))
        open_w.append((k, f))
        trades.append(ret)
        fs_used.setdefault(row.label, []).append(f)
    ex = np.cumsum(expo)[:n]
    contrib -= np.maximum(0, ex - 1) * fin_rate / 250          # 超過自有資金的部分付融資利息（融券放空另有保證金，這裡一律以利息估）
    eq = pd.Series(np.cumprod(1 + contrib), index=days)
    yrs = (days[-1] - days[0]).days / 365.25
    yearly = eq.groupby(eq.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    mid = days[0] + (days[-1] - days[0]) / 2
    seg = lambda a, b: (lambda s: (s.iloc[-1] / s.iloc[0]) ** (365.25 / (s.index[-1] - s.index[0]).days) - 1)(eq[(eq.index >= a) & (eq.index <= b)])  # noqa: E731
    return {"cagr": eq.iloc[-1] ** (1 / yrs) - 1, "mdd": (eq / eq.cummax() - 1).min(), "early": seg(days[0], mid), "late": seg(mid, days[-1]),
            "trades": len(trades), "expo": float(ex.mean()), "minv": float(eq.min()), "yearly": yearly,
            "vol": float(np.log1p(contrib).std() * np.sqrt(250)), "f": {k: float(np.mean(v)) for k, v in fs_used.items()}}


def kelly_main(argv):
    src = Path(argv[0]) if argv else Path("/tmp/btdata")
    M = eb.mats()
    days = M["adj"].index
    tx = eb.taiex()
    parts = [core_trades(days)]
    rng = 0
    for t in exdiv_trades(days, tx) + [disposal_trades(days), tender_trades(days)]:
        parts.append(t.assign(score=100.0))
    fd = fulldel_trades(days, src).sample(frac=0.5, random_state=rng).assign(score=100.0)
    lu = limitup_trades(days).sample(frac=0.3, random_state=rng).assign(score=100.0, hedge=-0.01)
    parts += [fd, lu]
    tr = pd.concat(parts, ignore_index=True)
    tr = tr[tr.d0 >= START]
    out = []
    for nm, kw in (("平均分 25 份（每筆 4%）", dict(mode="equal", base=0.04)),
                   ("凱利（全凱利）", dict(mode="kelly", frac=1.0)),
                   ("半凱利", dict(mode="kelly", frac=0.5)),
                   ("凱利，單筆最多 10%", dict(mode="kelly", frac=1.0, cap_one=0.10)),
                   ("半凱利，單筆最多 10%", dict(mode="kelly", frac=0.5, cap_one=0.10)),
                   ("四分之一凱利", dict(mode="kelly", frac=0.25))):
        r = run_sized(tr, **kw)
        out.append(f"{nm}｜年化 {r['cagr']:+.1%} 最大回落 {r['mdd']:+.1%} 年波動 {r['vol']:.0%} 前段 {r['early']:+.1%} 後段 {r['late']:+.1%} "
                   f"交易 {r['trades']} 平均資金在場 {r['expo']:.0%}")
        out.append("     平均每筆部位：" + "；".join(f"{k} {v:.1%}" for k, v in r["f"].items()))
        out.append("     每年：" + "  ".join(f"{str(y)[2:]} {v:+.0%}" for y, v in r["yearly"].items()))
        print("\n".join(out[-3:]), flush=True)
    (eb.pf.OUT / "multi_kelly.txt").write_text("\n".join(out))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "kelly":
    kelly_main(sys.argv[2:])


def levstop_main(argv):
    src = Path(argv[0]) if argv else Path("/tmp/btdata")
    M = eb.mats()
    days = M["adj"].index
    tx = eb.taiex()
    parts = [core_trades(days)]
    for t in exdiv_trades(days, tx) + [disposal_trades(days), tender_trades(days)]:
        parts.append(t.assign(score=100.0))
    parts += [fulldel_trades(days, src).sample(frac=0.5, random_state=0).assign(score=100.0),
              limitup_trades(days).sample(frac=0.3, random_state=0).assign(score=100.0, hedge=-0.01)]
    tr = pd.concat(parts, ignore_index=True)
    tr = tr[tr.d0 >= START]
    out = []
    if argv[1:2] == ["extra"]:
        cases = [(f"停損 8%（全部）＋槓桿 {L}x", dict(lev=L, stop=0.08)) for L in (1.3, 1.5, 2.0)]
        cases += [(f"停損 5%（全部）＋槓桿 {L}x", dict(lev=L, stop=0.05)) for L in (1.5, 2.0)]
        cases += [("停損 8%（全部）＋槓桿 1.5x、融資利率 8%", dict(lev=1.5, stop=0.08, fin_rate=0.08))]
    else:
        cases = [("平均分 4%（基準）", {})]
        cases += [(f"槓桿 {L}x", dict(lev=L)) for L in (1.3, 1.5, 2.0)]
        cases += [(f"停損 {s_:.0%}（全部策略）", dict(stop=s_)) for s_ in (0.05, 0.08, 0.10, 0.15, 0.20)]
        cases += [(f"停損 {s_:.0%}（只有主力營收）", dict(stop=s_, stop_core_only=True)) for s_ in (0.08, 0.10, 0.15, 0.20)]
        cases += [("槓桿 1.5x＋主力停損 15%", dict(lev=1.5, stop=0.15, stop_core_only=True)),
                  ("槓桿 1.5x＋主力停損 10%", dict(lev=1.5, stop=0.10, stop_core_only=True)),
                  ("槓桿 2x＋主力停損 15%", dict(lev=2.0, stop=0.15, stop_core_only=True))]
    for nm, kw in cases:
        r = run_sized(tr, mode="equal", base=0.04, **kw)
        bad = min(r["yearly"].values)
        out.append(f"{nm}｜年化 {r['cagr']:+.1%} 最大回落 {r['mdd']:+.1%} 年波動 {r['vol']:.0%} 前段 {r['early']:+.1%} 後段 {r['late']:+.1%} "
                   f"最差一年 {bad:+.0%} 平均曝險 {r['expo']:.0%} 交易 {r['trades']}")
        out.append("     每年：" + "  ".join(f"{str(y)[2:]} {v:+.0%}" for y, v in r["yearly"].items()))
        print("\n".join(out[-2:]), flush=True)
    (eb.pf.OUT / ("multi_levstop_extra.txt" if argv[1:2] == ["extra"] else "multi_levstop.txt")).write_text("\n".join(out))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "levstop":
    levstop_main(sys.argv[2:])
