"""券差借券費率：上市＋上櫃合併，每檔聚合總表＋原始明細。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import config
from .util import write_json


def build(d: date, rows: list[dict], quotes: list[dict]) -> dict:
    qm = {q["code"]: q for q in quotes}

    def px(code):
        q = qm.get(code, {})
        return {"close": q.get("close"), "lots_traded": (q.get("volume") or 0) // 1000,
                "chg": round((q["close"] / q["prev_close"] - 1) * 100, 2) if q.get("prev_close") else None}

    g = defaultdict(list)
    for r in rows:
        g[r["code"]].append(r)
    summary = []
    for code, rs in g.items():
        lots = sum(r["lots"] for r in rs)
        wavg = sum(r["rate"] * r["lots"] for r in rs) / lots if lots else sum(r["rate"] for r in rs) / len(rs)
        summary.append({"code": code, "name": rs[0]["name"], "market": rs[0]["market"], **px(code),
                        "lots": round(lots, 1), "avg_rate": round(wavg, 3), "min_rate": min(r["rate"] for r in rs),
                        "max_rate": max(r["rate"] for r in rs), "n": len(rs)})
    summary.sort(key=lambda x: -x["avg_rate"])
    detail = [{**r, **px(r["code"])} for r in sorted(rows, key=lambda r: (r["code"], -r["rate"]))]
    res = {"date": d.isoformat(), "summary": summary, "detail": detail}
    write_json(config.OUT_DIR / "borrow.json", res)
    return res
