"""漲停族群（當日）、隔日表現、統計、個股漲停履歷。"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from . import config, store, themes
from .util import limit_up, parse_date, read_json, write_json

log = logging.getLogger(__name__)
OUT = config.OUT_DIR


def _daily_path(d: date):
    return OUT / "daily" / f"{d.isoformat()}.json"


def load_daily(d: date) -> dict | None:
    return read_json(_daily_path(d))


def daily_dates() -> list[date]:
    p = OUT / "daily"
    return sorted(x for x in (parse_date(f.stem) for f in p.glob("*.json")) if x) if p.exists() else []


def is_limit_up(q: dict) -> bool:
    pc = q.get("prev_close")
    if not pc or pc <= 0 or not q.get("close") or not q.get("volume"):
        return False
    return q["close"] >= limit_up(pc) - 1e-9


def build_daily(d: date, quotes: list[dict], companies: dict, context: dict[str, list[str]], src=None,
                inst: dict | None = None, full: bool = True) -> dict:
    """full=False（補歷史時）：不抓營業項目、不用 AI 寫漲停原因"""
    lus = [q for q in quotes if is_limit_up(q)]
    prev = store.prev_day(d)
    prev_daily = load_daily(prev) if prev else None
    prev_streak = {s["code"]: s["streak"] for s in (prev_daily or {}).get("stocks", [])}
    old = {s["code"]: s for s in (load_daily(d) or {}).get("stocks", [])}  # 重跑同一天時保留已有的法人與原因
    inst = inst or {}

    info = [{"code": q["code"], "name": q["name"], "industry": companies.get(q["code"], {}).get("industry", "")} for q in lus]
    biz: dict[str, str] = {}
    if src is not None and hasattr(src, "theme_of"):
        cls = {q["code"]: {"theme": src.theme_of(q["code"]), "source": "manual", "reason": "模擬資料"} for q in lus}
    else:
        if full:
            biz = themes.businesses([q["code"] for q in lus], getattr(src, "fetch_business", None))
        cls = themes.classify(info, context, biz)

    stocks = []
    for q in lus:
        c = companies.get(q["code"], {})
        av = store.avg_volume(q["code"], d, 5)
        shares = c.get("shares") or 0
        stocks.append({
            "code": q["code"], "name": q["name"], "market": q["market"], "close": q["close"],
            "prev_close": q["prev_close"], "chg": round((q["close"] / q["prev_close"] - 1) * 100, 2),
            "lots": q["volume"] // 1000, "vol_ratio": round(q["volume"] / av, 2) if av else None,
            "value_e": round(q["value"] / 1e8, 2), "turnover": round(q["volume"] / shares * 100, 2) if shares else None,
            "locked": q["high"] == q["close"] and q["low"] != q["high"], "one_price": q["low"] == q["high"],
            "streak": prev_streak.get(q["code"], 0) + 1, "industry": c.get("industry", ""),
            "theme": cls[q["code"]]["theme"], "theme_source": cls[q["code"]]["source"], "reason": cls[q["code"]].get("reason", ""),
            "inst": inst.get(q["code"]) or old.get(q["code"], {}).get("inst"),
        })
    stocks.sort(key=lambda s: (-s["streak"], -s["value_e"]))

    # 漲停原因
    why = themes.explain(stocks, context or {}, biz, use_ai=full)
    for s in stocks:
        o = old.get(s["code"], {})
        s["why"] = why.get(s["code"], "") if (full or not o.get("why")) else o["why"]

    # 族群
    prev_dates = [x for x in daily_dates() if x < d][-30:]
    prev_themes = [{s["theme"] for s in (load_daily(x) or {}).get("stocks", [])} for x in prev_dates]
    g = defaultdict(list)
    for s in stocks:
        g[s["theme"]].append(s)
    groups = []
    for t, ss in g.items():
        streak = 1
        for th in reversed(prev_themes):
            if t in th:
                streak += 1
            else:
                break
        vr = [s["vol_ratio"] for s in ss if s["vol_ratio"]]
        groups.append({"theme": t, "emoji": themes.emoji(t), "count": len(ss), "streak": streak,
                       "codes": [s["code"] for s in ss], "value_e": round(sum(s["value_e"] for s in ss), 2),
                       "avg_vol_ratio": round(sum(vr) / len(vr), 2) if vr else None})
    groups.sort(key=lambda x: (-x["count"], -x["value_e"]))
    top4 = sum(x["count"] for x in groups[:4])
    res = {
        "date": d.isoformat(), "count": len(stocks),
        "twse": sum(s["market"] == "TWSE" for s in stocks), "tpex": sum(s["market"] == "TPEX" for s in stocks),
        "n_groups": len(groups), "top4_share": round(top4 / len(stocks) * 100, 1) if stocks else 0,
        "market_up": sum(q["change"] > 0 for q in quotes), "market_down": sum(q["change"] < 0 for q in quotes),
        "groups": groups, "stocks": stocks,
    }
    write_json(_daily_path(d), res)
    return res


def _tag(ref, o, c, lu_today):
    if c >= lu_today - 1e-9:
        return "續漲停"
    if o > ref:
        return "開高走高" if c > o else "開高走低"
    if o < ref:
        return "開低走高" if c > o else "開低走低"
    return "平開走高" if c > ref else "平開走低"


def build_nextday(d: date, quotes: list[dict]) -> dict | None:
    """前一交易日漲停股，在 d 日的開盤/均價/收盤報酬（以漲停價為基準）"""
    prev = store.prev_day(d)
    pd = load_daily(prev) if prev else None
    if not pd or not pd["stocks"]:
        return None
    qm = {q["code"]: q for q in quotes}
    rows = []
    for s in pd["stocks"]:
        q = qm.get(s["code"])
        if not q or not q.get("open"):
            continue
        ref = s["close"]
        r = lambda p: round((p / ref - 1) * 100, 2) if p else None  # noqa: E731
        rows.append({
            "code": s["code"], "name": s["name"], "market": s["market"], "theme": s["theme"], "ref": ref,
            "vol_ratio": s["vol_ratio"], "streak": s["streak"],
            "open": q["open"], "avg": q["avg"], "close": q["close"], "high": q["high"],
            "ret_open": r(q["open"]), "ret_avg": r(q["avg"]), "ret_close": r(q["close"]), "ret_high": r(q["high"]),
            # 加權：假設 2/3 在開盤賣、1/3 在均價賣的報酬
            "ret_wavg": round((2 * r(q["open"]) + r(q["avg"])) / 3, 2) if q["open"] and q["avg"] else None,
            "tag": _tag(ref, q["open"], q["close"], limit_up(ref)),
        })
    if not rows:
        return None
    mean = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
    win = lambda xs: round(sum(x > 0 for x in xs) / len(xs) * 100, 1) if xs else None  # noqa: E731
    o, a, c = [x["ret_open"] for x in rows], [x["ret_avg"] for x in rows], [x["ret_close"] for x in rows]
    g = defaultdict(list)
    for x in rows:
        g[x["theme"]].append(x)
    dgroups = {gg["theme"]: gg["streak"] for gg in pd["groups"]}
    groups = [{"theme": t, "emoji": themes.emoji(t), "streak": dgroups.get(t, 1), "n": len(xs),
               "win": win([x["ret_close"] for x in xs]), "wins": sum(x["ret_close"] > 0 for x in xs),
               "open": mean([x["ret_open"] for x in xs]), "avg": mean([x["ret_avg"] for x in xs]),
               "close": mean([x["ret_close"] for x in xs])} for t, xs in g.items()]
    groups.sort(key=lambda x: -(x["close"] or 0))
    rows.sort(key=lambda x: -(x["ret_close"] or 0))
    tags = defaultdict(int)
    for x in rows:
        tags[x["tag"]] += 1

    # 與近 20 次平均比較
    hist = [read_json(OUT / "nextday" / f"{x.isoformat()}.json") for x in daily_dates() if x < d][-20:]
    hist = [h for h in hist if h]
    base = {k: mean([h["summary"][k] for h in hist if h["summary"].get(k) is not None]) for k in ("open_win", "avg_win", "close_win")}
    wv = [x["ret_wavg"] for x in rows if x["ret_wavg"] is not None]
    summ = {"n": len(rows), "open_avg": mean(o), "avg_avg": mean(a), "close_avg": mean(c), "wavg_avg": mean(wv),
            "open_win": win(o), "avg_win": win(a), "close_win": win(c), "cont": tags.get("續漲停", 0)}
    for k in ("open_win", "avg_win", "close_win"):
        summ[k + "_vs20"] = round(summ[k] - base[k], 1) if base.get(k) is not None else None
    res = {"limit_date": prev.isoformat(), "date": d.isoformat(), "summary": summ,
           "groups": groups, "stocks": rows, "tags": dict(tags)}
    write_json(OUT / "nextday" / f"{d.isoformat()}.json", res)
    return res


def build_stats(window: int = 60) -> dict:
    ds = daily_dates()[-window:]
    series, theme_agg, stock_hist = [], defaultdict(lambda: {"days": 0, "total": 0, "nd": [], "last": ""}), {}
    nd_by_limit = {}
    p = OUT / "nextday"
    for f in sorted(p.glob("*.json")) if p.exists() else []:
        js = read_json(f)
        if js:
            nd_by_limit[js["limit_date"]] = js
    for d in ds:
        dj = load_daily(d)
        if not dj:
            continue
        nd = nd_by_limit.get(d.isoformat())
        ndm = {x["code"]: x for x in (nd or {}).get("stocks", [])}
        series.append({"date": d.isoformat(), "count": dj["count"], "twse": dj["twse"], "tpex": dj["tpex"],
                       "groups": dj["n_groups"], "top": dj["groups"][0]["theme"] if dj["groups"] else "",
                       "nd_close": (nd or {}).get("summary", {}).get("close_avg"),
                       "nd_win": (nd or {}).get("summary", {}).get("close_win")})
        for gg in dj["groups"]:
            t = theme_agg[gg["theme"]]
            t["days"] += 1
            t["total"] += gg["count"]
            t["last"] = d.isoformat()
            t["emoji"] = gg["emoji"]
        for s in dj["stocks"]:
            n = ndm.get(s["code"])
            if n:
                theme_agg[s["theme"]]["nd"].append(n["ret_close"])
    # 個股履歷用全部歷史
    for d in daily_dates():
        dj = load_daily(d)
        nd = nd_by_limit.get(d.isoformat())
        ndm = {x["code"]: x for x in (nd or {}).get("stocks", [])}
        for s in (dj or {}).get("stocks", []):
            h = stock_hist.setdefault(s["code"], {"name": s["name"], "market": s["market"], "events": []})
            n = ndm.get(s["code"], {})
            h["events"].append({"date": d.isoformat(), "theme": s["theme"], "streak": s["streak"], "close": s["close"],
                                "nd_open": n.get("ret_open"), "nd_close": n.get("ret_close"), "tag": n.get("tag")})
    themes_tbl = []
    for t, v in theme_agg.items():
        nd = v["nd"]
        themes_tbl.append({"theme": t, "emoji": v.get("emoji", "📈"), "days": v["days"], "total": v["total"], "last": v["last"],
                           "nd_n": len(nd), "nd_avg": round(sum(nd) / len(nd), 2) if nd else None,
                           "nd_win": round(sum(x > 0 for x in nd) / len(nd) * 100, 1) if nd else None})
    themes_tbl.sort(key=lambda x: (-x["total"], -x["days"]))
    res = {"window": len(series), "series": series, "themes": themes_tbl,
           "avg_count": round(sum(s["count"] for s in series) / len(series), 1) if series else 0}
    write_json(OUT / "stats.json", res)
    write_json(OUT / "stock_history.json", stock_hist)
    return res
