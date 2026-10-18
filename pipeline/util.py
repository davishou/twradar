"""共用小工具：數字解析、台股跳動單位與漲跌停價、民國日期、容錯取欄位。"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Iterable

# ---------- 數字 ----------

def num(v: Any, default: float | None = None) -> float | None:
    """'1,234.5' / '+0.5' / '<p style=color:red>+</p>' / '--' → float"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v) if not (isinstance(v, float) and math.isnan(v)) else default
    s = re.sub(r"<[^>]+>", "", str(v)).replace(",", "").replace("％", "").replace("%", "").strip()
    s = s.replace("X", "").replace("除權息", "").replace("除息", "").replace("除權", "")
    if s in ("", "-", "--", "---", "----", "N/A", "null", "除牌"):
        return default
    try:
        return float(s)
    except ValueError:
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        return float(m.group()) if m else default


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or not b:
        return None
    return round((a / b - 1) * 100, 2)

# ---------- 跳動單位 / 漲跌停 ----------

_TICKS = [(10, Decimal("0.01")), (50, Decimal("0.05")), (100, Decimal("0.1")),
          (500, Decimal("0.5")), (1000, Decimal("1")), (float("inf"), Decimal("5"))]


def tick(price: float) -> Decimal:
    for limit, t in _TICKS:
        if price < limit:
            return t
    return Decimal("5")


def _round_to_tick(x: Decimal, mode) -> Decimal:
    t = tick(float(x))
    q = (x / t).to_integral_value(rounding=mode) * t
    # 落在不同級距時重新以該級距再對齊一次
    t2 = tick(float(q))
    if t2 != t:
        q = (x / t2).to_integral_value(rounding=mode) * t2
    return q


def limit_up(prev_close: float) -> float:
    """漲停價：前收 ×1.1 後向下取到合法跳動單位"""
    return float(_round_to_tick(Decimal(str(prev_close)) * Decimal("1.1"), ROUND_FLOOR))


def limit_down(prev_close: float) -> float:
    """跌停價：前收 ×0.9 後向上取到合法跳動單位"""
    return float(_round_to_tick(Decimal(str(prev_close)) * Decimal("0.9"), ROUND_CEILING))


def price_up_to_tick(x: float) -> float:
    return float(_round_to_tick(Decimal(str(x)), ROUND_CEILING))


def price_down_to_tick(x: float) -> float:
    return float(_round_to_tick(Decimal(str(x)), ROUND_FLOOR))

# ---------- 日期 ----------

def parse_date(s: Any) -> date | None:
    """支援 2026-10-16、20261016、1151016、115/10/16、2026/10/16"""
    if s is None:
        return None
    if isinstance(s, date):
        return s
    t = re.sub(r"[^\d/\-]", "", str(s))
    m = re.fullmatch(r"(\d{2,4})[/\-](\d{1,2})[/\-](\d{1,2})", t)
    if m:
        y, mo, d = map(int, m.groups())
    elif re.fullmatch(r"\d{8}", t):
        y, mo, d = int(t[:4]), int(t[4:6]), int(t[6:])
    elif re.fullmatch(r"\d{7}", t):
        y, mo, d = int(t[:3]), int(t[3:5]), int(t[5:])
    else:
        return None
    if y < 1911:
        y += 1911
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def roc(d: date, sep: str = "/") -> str:
    return f"{d.year - 1911}{sep}{d.month:02d}{sep}{d.day:02d}"


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def next_weekday(d: date, holidays: Iterable[date] = ()) -> date:
    hs = set(holidays)
    n = d + timedelta(days=1)
    while n.weekday() >= 5 or n in hs:
        n += timedelta(days=1)
    return n


def now_tw() -> datetime:
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)

# ---------- 欄位 ----------

def pick(row: dict, *keys: str, contains: bool = True, default=None):
    """依序找欄位；先精確比對，再找『包含』該字串的欄位（交易所常改欄名）。"""
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    if contains:
        for k in keys:
            for rk, rv in row.items():
                if k in str(rk) and rv not in (None, ""):
                    return rv
    return default


def table_rows(payload: dict, must_have: str | None = None) -> list[dict]:
    """把 TWSE/TPEx 的 {fields:[...], data:[[...]]} 或 {tables:[...]} 轉成 list[dict]"""
    tables = []
    if isinstance(payload, list):
        return payload
    if "tables" in payload and isinstance(payload["tables"], list):
        tables = payload["tables"]
    else:
        tables = [payload]
    out: list[dict] = []
    for t in tables:
        fields = [str(f).strip() for f in (t.get("fields") or t.get("fields1") or [])]
        data = t.get("data") or t.get("aaData") or []
        if not fields or not data:
            continue
        if must_have and not any(must_have in f for f in fields):
            continue
        for r in data:
            if isinstance(r, dict):
                out.append(r)
            else:
                out.append({fields[i]: r[i] for i in range(min(len(fields), len(r)))})
    return out


def is_common_stock(code: str) -> bool:
    """普通股：4 碼數字（排除 ETF 00 開頭、權證等）"""
    return bool(re.fullmatch(r"[1-9]\d{3}", code or ""))

# ---------- 檔案 ----------

def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(p: Path, obj) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str), "utf-8")
    tmp.replace(p)
