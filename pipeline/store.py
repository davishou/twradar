"""本地歷史資料庫：每天一個 JSON 快照，自動累積，供量比、6 日漲跌、30/60/90 日門檻計算。"""
from __future__ import annotations

from datetime import date
from functools import lru_cache

from . import config
from .util import parse_date, read_json, write_json

_FIELDS = ["code", "name", "market", "open", "high", "low", "close", "change", "prev_close", "volume", "value", "trades", "avg"]


def save_day(d: date, quotes: list[dict]) -> None:
    rows = [[q.get(f) for f in _FIELDS] for q in quotes]
    write_json(config.HISTORY_DIR / f"{d.isoformat()}.json", {"date": d.isoformat(), "fields": _FIELDS, "rows": rows})
    load_day.cache_clear()
    trading_days.cache_clear()


@lru_cache(maxsize=256)
def load_day(d: date) -> dict[str, dict]:
    js = read_json(config.HISTORY_DIR / f"{d.isoformat()}.json")
    if not js:
        return {}
    f = js["fields"]
    return {r[0]: dict(zip(f, r)) for r in js["rows"]}


@lru_cache(maxsize=4)
def trading_days() -> tuple[date, ...]:
    if not config.HISTORY_DIR.exists():
        return ()
    ds = [parse_date(p.stem) for p in config.HISTORY_DIR.glob("*.json")]
    return tuple(sorted(d for d in ds if d))


def days_before(d: date, n: int, include: bool = True) -> list[date]:
    """d（含）之前最近 n 個交易日，舊→新"""
    ds = [x for x in trading_days() if (x <= d if include else x < d)]
    return ds[-n:]


def prev_day(d: date) -> date | None:
    ds = days_before(d, 1, include=False)
    return ds[0] if ds else None


def next_day(d: date) -> date | None:
    for x in trading_days():
        if x > d:
            return x
    return None


def closes(code: str, d: date, n: int) -> list[float | None]:
    return [load_day(x).get(code, {}).get("close") for x in days_before(d, n)]


def avg_volume(code: str, d: date, n: int = 5) -> float | None:
    """d 之前（不含 d）n 日均量"""
    vs = [load_day(x).get(code, {}).get("volume") for x in days_before(d, n, include=False)]
    vs = [v for v in vs if v]
    return sum(vs) / len(vs) if vs else None


def market_avg_change(d_from: date, d_to: date) -> float:
    """兩日間全體股票收盤漲跌幅平均（%），用於『與全體平均差幅』"""
    a, b = load_day(d_from), load_day(d_to)
    xs = [(b[c]["close"] / a[c]["close"] - 1) * 100 for c in b if c in a and a[c]["close"] and b[c]["close"]]
    return sum(xs) / len(xs) if xs else 0.0


def state(name: str, default=None):
    return read_json(config.STATE_DIR / f"{name}.json", default)


def save_state(name: str, obj) -> None:
    write_json(config.STATE_DIR / f"{name}.json", obj)


KEEP_DAYS = 260   # data/history 只留近 260 個交易日（更舊的在 data/archive 長期資料庫）


def prune(keep: int = KEEP_DAYS) -> int:
    ds = trading_days()
    old = ds[:-keep] if len(ds) > keep else ()
    for d in old:
        (config.HISTORY_DIR / f"{d.isoformat()}.json").unlink(missing_ok=True)
    if old:
        load_day.cache_clear()
        trading_days.cache_clear()
    return len(old)
