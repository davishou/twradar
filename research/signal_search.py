"""漲停股訊號搜尋：有沒有「勝率與超額報酬都穩定贏大盤」的條件？

做法（避免把運氣當成訊號）：
  1. 資料切兩段：前段 2021-10 ~ 2024-06 用來「找」，後段 2024-07 以後用來「驗證」。
  2. 每個特徵依前段資料切 5 等分（或是／否），算每一組的勝率（贏大盤比例）與超額報酬中位數。
  3. 前段表現最好的單一條件，兩兩組合再看一次。
  4. 只有「前段、後段都」勝率 > 50% 且超額中位數 > 0、各段至少 100 次，才算候選訊號。
進場：只用漲停日資料的條件 → 隔日開盤進場（排除隔日開盤就漲停、買不到的）；
      要用隔日資料的條件（原網站量比、隔日開盤跳空、隔日漲跌）→ 隔日收盤進場（排除隔日鎖漲停）。

python -m pipeline.backtest signals [持有天數，預設 20]
"""
from __future__ import annotations

import itertools

from pipeline import backtest as bt

SPLIT = "2024-07-01"
# (欄位, 說明, 是否需要隔日資料)
NUMERIC = [
    ("A", "均量比", False), ("run20", "前20日漲幅", False), ("run60", "前60日漲幅", False),
    ("hi120", "距120日高點", False), ("value_e", "成交金額(億)", False), ("price", "股價", False),
    ("mkt_n", "全市場漲停家數", False), ("mkt20", "大盤前20日漲幅", False), ("ind_n", "同產業漲停家數", False),
    ("f", "外資買超占量%", False), ("fin_chg", "融資5日增減%", False), ("short_ratio", "券資比%", False),
    ("B", "量比(隔日÷漲停日)", True), ("gap_next", "隔日開盤跳空%", True), ("next_ret", "隔日漲跌%", True),
]
BINARY = [
    ("one_price", "一字漲停", lambda e: e["one_price"], False),
    ("streak2", "連板(≥2)", lambda e: e["streak"] >= 2, False),
    ("first", "首板", lambda e: e["streak"] == 1, False),
    ("newhigh", "創120日新高", lambda e: e["hi120"] >= 1, False),
    ("trust", "投信買超", lambda e: e["t"] > 0, False),
    ("foreign", "外資買超", lambda e: e["f"] > 0, False),
    ("allbuy", "外資投信都買", lambda e: (e["f"] > 0) & (e["t"] > 0), False),
    ("notice", "前10日曾列注意股", lambda e: e["notice10"] > 0, False),
    ("tpex", "上櫃", lambda e: e["market"] == "TPEX", False),
    ("twse", "上市", lambda e: e["market"] == "TWSE", False),
    ("mktup", "大盤前20日上漲", lambda e: e["mkt20"] > 0, False),
]


def _st(s, ret):
    x = s[ret].dropna()
    return len(x), (x > 0).mean() if len(x) else float("nan"), x.median() if len(x) else float("nan"), \
        x.mean() if len(x) else float("nan")


def build_conditions(ev):
    """回傳 [(名稱, 布林遮罩, 需要隔日)]；數值特徵依前段資料五等分"""
    pd = bt._pd()[0]
    train = ev["date"] < SPLIT
    conds = []
    for col, name, nxt in NUMERIC:
        x = ev[col]
        qs = x[train].quantile([0.2, 0.4, 0.6, 0.8]).values
        if len(set(qs)) < 4:                  # 太多 0（例如外資買超）就改用 0 切
            edges = [-float("inf"), 0, float("inf")] if (x[train] == 0).mean() > 0.3 else None
            if edges:
                for lo, hi, lab in ((-float("inf"), -1e-9, "<0"), (-1e-9, 1e-9, "=0"), (1e-9, float("inf"), ">0")):
                    conds.append((f"{name} {lab}", (x > lo) & (x <= hi), nxt))
                continue
        edges = [-float("inf"), *qs, float("inf")]
        for k in range(5):
            lo, hi = edges[k], edges[k + 1]
            lab = f"第{k + 1}組({_fmt(lo)}~{_fmt(hi)})"
            conds.append((f"{name} {lab}", (x > lo) & (x <= hi), nxt))
    for key, name, f, nxt in BINARY:
        raw = f(ev)
        known = raw.notna()
        m = raw.where(known, False).astype(bool)
        conds.append((name, m, nxt))
        conds.append((f"非{name}", ~m & known, nxt))
    return conds


def _fmt(v):
    if v in (float("inf"), -float("inf")):
        return "∞" if v > 0 else "-∞"
    return f"{v:.2f}" if abs(v) < 10 else f"{v:.0f}"


def evaluate(ev, conds, h: int):
    pd = bt._pd()[0]
    train = ev["date"] < SPLIT
    rows = []
    for name, m, nxt in conds:
        ret = f"xc{h}" if nxt else f"xo{h}"
        buyable = ~ev["next_is_lu"] if nxt else ~ev["next_open_lu"]
        mm = m & buyable
        a = _st(ev[mm & train], ret)
        b = _st(ev[mm & ~train], ret)
        rows.append({"條件": name, "進場": "隔日收" if nxt else "隔日開", "前段次數": a[0], "前段勝率": a[1],
                     "前段超額中位": a[2], "前段超額平均": a[3], "後段次數": b[0], "後段勝率": b[1],
                     "後段超額中位": b[2], "後段超額平均": b[3]})
    return pd.DataFrame(rows)


def baseline(ev, h):
    train = ev["date"] < SPLIT
    out = []
    for nxt in (False, True):
        ret = f"xc{h}" if nxt else f"xo{h}"
        buy = ~ev["next_is_lu"] if nxt else ~ev["next_open_lu"]
        a, b = _st(ev[buy & train], ret), _st(ev[buy & ~train], ret)
        out.append(f"全部漲停股（{'隔日收' if nxt else '隔日開'}進場）：前段 勝率 {a[1]:.0%} 超額中位 {a[2]:+.1%}｜"
                   f"後段 勝率 {b[1]:.0%} 超額中位 {b[2]:+.1%}")
    return "\n".join(out)


def fmt(df):
    d = df.copy()
    for c in d.columns:
        if "勝率" in c:
            d[c] = d[c].map(lambda v: f"{v:.0%}")
        elif "超額" in c:
            d[c] = d[c].map(lambda v: f"{v:+.1%}")
    return d.to_string(index=False)


def passed(df, minn=100):
    return df[(df["前段次數"] >= minn) & (df["後段次數"] >= minn) & (df["前段勝率"] > 0.5) & (df["後段勝率"] > 0.5)
              & (df["前段超額中位"] > 0) & (df["後段超額中位"] > 0)]


def run(h: int = 20, ev=None) -> str:
    ev = bt.limitup_events() if ev is None else ev
    conds = build_conditions(ev)
    single = evaluate(ev, conds, h)
    out = [f"持有 {h} 個交易日；前段 < {SPLIT} ≤ 後段；共 {len(ev)} 次漲停", baseline(ev, h), "",
           f"=== 單一條件（{len(conds)} 個），依前段超額中位排序，前 15 名 ===",
           fmt(single[single["前段次數"] >= 100].sort_values("前段超額中位", ascending=False).head(15)), "",
           "=== 單一條件：前段最差 8 名（反向警訊） ===",
           fmt(single[single["前段次數"] >= 100].sort_values("前段超額中位").head(8))]
    # 兩兩組合：只取前段前 12 名、同一進場方式、不同特徵
    top = single[single["前段次數"] >= 300].sort_values("前段超額中位", ascending=False).head(12)["條件"].tolist()
    cm = {n: (m, nxt) for n, m, nxt in conds}
    pairs = []
    for a, b in itertools.combinations(top, 2):
        if a.split(" ")[0] == b.split(" ")[0] or cm[a][1] != cm[b][1]:
            continue
        pairs.append((f"{a} ＋ {b}", cm[a][0] & cm[b][0], cm[a][1]))
    combo = evaluate(ev, pairs, h)
    out += ["", f"=== 兩兩組合（{len(pairs)} 個），依前段超額中位排序，前 15 名 ===",
            fmt(combo[combo["前段次數"] >= 100].sort_values("前段超額中位", ascending=False).head(15))]
    ok = passed(single)
    ok2 = passed(combo)
    out += ["", f"=== 前後兩段都通過（勝率>50%、超額中位>0、各≥100 次）：單一 {len(ok)} 個、組合 {len(ok2)} 個 ==="]
    if len(ok) or len(ok2):
        out.append(fmt(bt._pd()[0].concat([ok, ok2])))
    return "\n".join(out)


def main(argv):
    h = int(argv[0]) if argv else 20
    print(run(h))
