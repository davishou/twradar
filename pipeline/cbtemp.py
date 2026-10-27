"""CB 溫度計：全市場可轉債的「平均轉換價值」換算成鄭詩翰的「CB 整體市場委買均價」刻度。

鄭詩翰（年輕人的投資夢）用 XQ 自寫表追蹤全部 CB 的委買均價：121 正常、112 低迷、108~110 極端恐慌、
2025/4/9 關稅崩盤 98。我們沒有委買價，但平均轉換價值（標的股價 ÷ 轉換價 × 100）和他的數字高度相關：
    換算均價 ≈ A × 平均轉換價值 + B     （用他公布的 8 個數字擬合，r = 0.97，誤差約 ±3 元）

每天收盤後由 cb 工作呼叫 update(d)：讀當天的 cbq／cbb 長期資料庫檔，算平均轉換價值，存進
data/state/cb_temp.json 的序列，並輸出 site/data/cb_temp.json 給可轉債頁的溫度計卡片。
回測統計（各溫度區間之後的大盤表現、恐慌事件）由 research/cb_market.py 算好後存進同一個 state。

python -m pipeline.cbtemp rebuild    用長期資料庫重建整段序列（2017 起，需完整 checkout）
python -m pipeline.cbtemp            用現有序列重新輸出前端檔
"""
from __future__ import annotations

import logging
import sys
from datetime import date, timedelta

from . import archive, config, store
from .util import write_json

log = logging.getLogger(__name__)
STATE = "cb_temp"
OUT = config.OUT_DIR / "cb_temp.json"
A, B = 0.655, 49.3          # 換算係數（research/cb_market.py 擬合）

ZONES = [   # (上限, key, 名稱, 說明)
    (105, "x", "極端恐慌", "比 2025/4 關稅崩盤後幾天還便宜；過去之後 60 天大盤平均 +22%"),
    (110, "p", "恐慌", "鄭詩翰開始分批加碼的區間（波段最多 6 成）"),
    (113, "l", "低迷", "像 2023/10、2025/1 的低迷水位"),
    (121, "n", "正常", "市場正常平均水位（他說約 121）"),
    (1e9, "h", "偏熱", "高於正常水位；創兩年新高時他會降部位"),
]
# 他在 FB 公布過的委買均價（畫在圖上對照）
HIS = [("2025-01-17", 112.5), ("2025-02-20", 121), ("2025-04-09", 98), ("2025-08-11", 113), ("2026-01-09", 113.7),
       ("2026-07-14", 123.1), ("2026-07-29", 108.1), ("2026-08-03", 116.6)]


def _num(v):
    try:
        return None if v in ("", None) else float(v)
    except (TypeError, ValueError):
        return None


def day_stat(ds: str) -> dict | None:
    """某天全市場 CB：平均轉換價值、檔數、平均價格、價格 <110 占比（與 research/cb_market.py 同定義）"""
    q = {r["code"]: r for r in archive.read("cbq", ds)}
    b = {r["code"]: r for r in archive.read("cbb", ds)}
    if not q or not b:
        return None
    prices, convs = [], []
    for code, r in q.items():
        px = _num(r.get("ref_next")) or _num(r.get("close"))
        if not px or not 30 < px < 2000:
            continue
        prices.append(px)
        br = b.get(code) or {}
        sp, cp = _num(br.get("stock_price")), _num(br.get("conv_price"))
        if sp and cp:
            cv = sp / cp * 100
            if 1 < cv < 2000:
                convs.append(cv)
    if len(convs) <= 20:
        return None
    return {"conv": round(sum(convs) / len(convs), 2), "n": len(convs), "avg": round(sum(prices) / len(prices), 2),
            "lt110": round(sum(p < 110 for p in prices) / len(prices), 3)}


def _state() -> dict:
    st = store.state(STATE, {}) or {}
    st.setdefault("series", {})
    return st


def zone(v: float) -> dict:
    for hi, key, name, desc in ZONES:
        if v < hi:
            return {"key": key, "name": name, "desc": desc}
    return {"key": "h", "name": "偏熱", "desc": ZONES[-1][3]}


def write_site(st: dict | None = None) -> dict | None:
    st = st or _state()
    ser = sorted(st["series"].items())
    if not ser:
        return None
    ds = [d for d, _ in ser]
    vals = [round(A * x[0] + B, 1) for _, x in ser]
    last_d, last_v = ds[-1], vals[-1]
    two = vals[-500:]
    pct = round(sum(v <= last_v for v in two) / len(two) * 100) if len(two) >= 120 else None
    # 週資料（每週最後一個交易日）給長期圖；近 260 日給短期圖
    weekly, wk = [], None
    for d, v in zip(ds, vals):
        k = date.fromisoformat(d).isocalendar()[:2]
        if k != wk:
            weekly.append([d, v])
            wk = k
        else:
            weekly[-1] = [d, v]
    prev5 = vals[-6] if len(vals) > 5 else None
    res = {"date": last_d, "value": last_v, "conv": ser[-1][1][0], "n": ser[-1][1][1], "avg": ser[-1][1][2],
           "lt110": ser[-1][1][3], "zone": zone(last_v), "pct2y": pct,
           "high2y": len(two) >= 250 and last_v >= max(two), "low2y": len(two) >= 250 and last_v <= min(two),
           "chg5": round(last_v - prev5, 1) if prev5 is not None else None,
           "coef": {"a": A, "b": B, "r": 0.97}, "zones": [[hi if hi < 1e8 else None, k, n] for hi, k, n, _ in ZONES],
           "weekly": weekly, "daily": [[d, v] for d, v in zip(ds[-260:], vals[-260:])],
           "his": HIS, **{k: st.get(k) for k in ("buckets", "episodes", "highs", "base", "stats_range", "stats_updated")}}
    write_json(OUT, res)
    return res


def update(d: date, back: int = 10) -> dict | None:
    """算 d（含）往前 back 個日曆天內還沒算過的日子，輸出前端檔"""
    st = _state()
    for i in range(back, -1, -1):
        ds = (d - timedelta(days=i)).isoformat()
        if ds in st["series"]:
            continue
        s = day_stat(ds)
        if s:
            st["series"][ds] = [s["conv"], s["n"], s["avg"], s["lt110"]]
    store.save_state(STATE, st)
    res = write_site(st)
    if res:
        log.info("CB 溫度計 %s：換算均價 %.1f（%s）", res["date"], res["value"], res["zone"]["name"])
    return res


def rebuild() -> int:
    st = _state()
    days = archive.days("cbb")
    for ds in days:
        s = day_stat(ds)
        if s:
            st["series"][ds] = [s["conv"], s["n"], s["avg"], s["lt110"]]
    store.save_state(STATE, st)
    write_site(st)
    return len(st["series"])


def save_stats(stats: dict) -> None:
    """research/cb_market.py 回測完呼叫：存各溫度區間之後的大盤表現"""
    st = _state()
    st.update(stats)
    store.save_state(STATE, st)
    write_site(st)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if sys.argv[1:2] == ["rebuild"]:
        log.info("CB 溫度計序列：%d 天", rebuild())
    else:
        r = write_site()
        log.info("CB 溫度計：%s", r and (r["date"], r["value"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
