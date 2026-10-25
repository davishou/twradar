"""股票名稱旁的小走勢圖：近 160 個交易日的還原收盤價，壓縮成短字串給前端畫。

每檔一筆：
  v  走勢：每個交易日一個字元（64 階，0＝區間最低、63＝區間最高）
  d  起始日；e 結束日
  a  起點還原價；b 最後收盤（還原價以最後一天為準，所以 b＝當天實際收盤）
  h  區間最高、l 區間最低（還原價）
  u  最大漲幅倍數＝區間內「某天價格 ÷ 它之前的最低價」的最大值（例如 5.2 代表曾從低點漲到 5.2 倍）
  w  最大跌幅％＝區間內「某天價格 ÷ 它之前的最高價 − 1」的最小值（例如 -62 代表曾從高點跌 62%）
  k  漲停日在序列中的位置

還原：除權息、減資等造成的參考價 ≠ 前一日收盤，把之前的價格乘上（參考價 ÷ 前收），避免假缺口。
不呼叫 AI、不抓網路，只讀 data/history。

python -m pipeline.spark        產生 site/data/spark.json（部署時產生，不進 git）
"""
from __future__ import annotations

import logging
import sys
from datetime import date

from . import config, store
from .util import limit_up, write_json

log = logging.getLogger(__name__)
N = 160
ALPHA = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
OUT = config.OUT_DIR / "spark.json"


def _encode(ps: list[float], lo: float, hi: float) -> str:
    span = hi - lo
    return "".join(ALPHA[0 if span <= 0 else min(63, round((p - lo) / span * 63))] for p in ps)


def record(rows: list[tuple[date, float, float | None, bool]]) -> dict | None:
    """rows：[(日期, 收盤, 前收/參考價, 是否漲停)]，舊→新，只含有成交的日子"""
    if len(rows) < 2:
        return None
    adj = [0.0] * len(rows)
    f = 1.0
    for i in range(len(rows) - 1, -1, -1):
        adj[i] = rows[i][1] * f
        if i > 0:
            ref, prev = rows[i][2], rows[i - 1][1]
            if ref and prev and abs(ref / prev - 1) > 0.0005 and 0.1 < ref / prev < 10:
                f *= ref / prev          # 除權息、減資：之前的價格乘上 參考價÷前收
    lo, hi = min(adj), max(adj)
    run_lo, run_hi, up, dn = adj[0], adj[0], 1.0, 0.0
    for p in adj:
        run_lo, run_hi = min(run_lo, p), max(run_hi, p)
        up = max(up, p / run_lo if run_lo > 0 else 1.0)
        dn = min(dn, p / run_hi - 1 if run_hi > 0 else 0.0)
    r = lambda x: round(x, 2 if x < 100 else 1)  # noqa: E731
    return {"v": _encode(adj, lo, hi), "d": rows[0][0].isoformat(), "e": rows[-1][0].isoformat(),
            "a": r(adj[0]), "b": rows[-1][1], "h": r(hi), "l": r(lo), "u": round(up, 2), "w": round(dn * 100, 1),
            "k": [i for i, x in enumerate(rows) if x[3]]}


def build(end: date | None = None, codes: set[str] | None = None, n: int = N) -> dict[str, dict]:
    """end（含）往前 n 個交易日；codes 給了就只算這些股票"""
    days = store.days_before(end, n) if end else list(store.trading_days())[-n:]
    series: dict[str, list] = {}
    for d in days:
        for c, q in store.load_day(d).items():
            if codes is not None and c not in codes:
                continue
            if not q.get("close") or not q.get("volume"):
                continue
            ref = q.get("prev_close")
            series.setdefault(c, []).append((d, q["close"], ref, bool(ref) and q["close"] >= limit_up(ref) - 1e-9))
    out = {}
    for c, rows in series.items():
        if not rows or rows[-1][0] != days[-1]:   # 最後一天沒成交（停牌）就不畫，避免誤導
            continue
        rec = record(rows)
        if rec:
            out[c] = rec
    return out


def write(end: date | None = None) -> int:
    data = build(end)
    ds = store.trading_days()
    write_json(OUT, {"date": (end or (ds[-1] if ds else date.today())).isoformat(), "n": N, "s": data})
    return len(data)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("小走勢圖：%d 檔", write())
    return 0


if __name__ == "__main__":
    sys.exit(main())
