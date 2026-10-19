"""盤後氣氛評論（AI 或規則版）與盤前 LINE 轉貼文字。"""
from __future__ import annotations

from datetime import date

from . import ai, config
from .disposal import COND_NAME, describe
from .util import now_tw, read_json, write_json

OUT = config.OUT_DIR


def _facts(daily: dict, nextday: dict | None) -> str:
    g = daily["groups"]
    lines = [f"日期 {daily['date']}：漲停 {daily['count']} 檔（上市 {daily['twse']}、上櫃 {daily['tpex']}），"
             f"共 {daily['n_groups']} 個族群，前四大族群占 {daily['top4_share']}%；全市場上漲 {daily['market_up']} 家、下跌 {daily['market_down']} 家。"]
    for x in g[:8]:
        names = "、".join(s["name"] for s in daily["stocks"] if s["theme"] == x["theme"])[:60]
        lines.append(f"- {x['theme']}：{x['count']} 檔，族群連續 {x['streak']} 天出現漲停（{names}）")
    streak = [s for s in daily["stocks"] if s["streak"] >= 2]
    if streak:
        lines.append("連板：" + "、".join(f"{s['name']}{s['streak']}連板" for s in streak[:8]))
    if nextday:
        s = nextday["summary"]
        lines.append(f"前一日漲停股今日表現：開盤平均 {s['open_avg']}%、收盤平均 {s['close_avg']}%，收盤勝率 {s['close_win']}%，續漲停 {s['cont']} 檔。")
    return "\n".join(lines)


def commentary(daily: dict, nextday: dict | None) -> dict:
    facts = _facts(daily, nextday)
    text = ai.ask(
        "根據以下台股盤後資料，寫一段 180~260 字的『今日盤面主軸』評論：點出資金主線族群、集中或分散程度、"
        "連板與隔日表現代表的追價氣氛。只能使用資料中的事實，不要預測股價，不要給買賣建議。\n\n" + facts,
        max_tokens=2000, tag="commentary")
    src = "ai"
    if not text:
        src = "rule"
        g = daily["groups"]
        lead = "、".join(x["theme"] for x in g[:2]) or "無明顯主流"
        conc = "熱點集中" if daily["top4_share"] >= 50 else "題材分散"
        text = (f"今日漲停 {daily['count']} 檔，由{lead}領頭，前四大族群合計 {daily['top4_share']}%，{conc}。"
                f"上市 {daily['twse']} 檔、上櫃 {daily['tpex']} 檔。")
        if g:
            long_ = max(g, key=lambda x: x["streak"])
            if long_["streak"] >= 2:
                text += f"{long_['theme']}族群已連續 {long_['streak']} 個交易日有個股漲停，資金延續性較強。"
        if nextday:
            s = nextday["summary"]
            mood = "追價意願偏強" if (s["close_avg"] or 0) > 2 else ("追價意願普通" if (s["close_avg"] or 0) > 0 else "追高後易遭獲利了結")
            text += f"前一日漲停股今日收盤平均 {s['close_avg']}%、勝率 {s['close_win']}%，續漲停 {s['cont']} 檔，{mood}。"
    res = {"date": daily["date"], "source": src, "text": text.strip(), "facts": facts,
           "generated": now_tw().strftime("%Y-%m-%d %H:%M")}
    write_json(OUT / "commentary" / f"{daily['date']}.json", res)
    idx = read_json(OUT / "commentary" / "index.json", []) or []
    idx = [x for x in idx if x["date"] != daily["date"]] + [{"date": daily["date"], "excerpt": res["text"][:80]}]
    write_json(OUT / "commentary" / "index.json", sorted(idx, key=lambda x: x["date"], reverse=True)[:250])
    return res


def line_copy() -> dict:
    disp = read_json(OUT / "disposal.json", {}) or {}
    ann = {k: (read_json(OUT / "announce" / f"{k}.json", {}) or {}).get("items", []) for k in ("att", "fin", "rev", "treasury")}
    T = (disp.get("target") or "")[5:].replace("-", "/")
    m1 = disp.get("minus1", [])
    new = {k: [x for x in v if x.get("new") or not x.get("traded", True)] for k, v in ann.items()}
    rev_note = [x for x in new["rev"] if x.get("has_note")]
    rev_plain = [x for x in new["rev"] if not x.get("has_note")]
    L = [f"{config.SITE_NAME} 盤前 LINE 轉貼版", config.SITE_URL, "",
         f"適用交易日：{T}", f"生成時間：{now_tw().strftime('%m/%d %H:%M')}",
         f"摘要：差1次就處置 {len(m1)} 檔、自結 {len(new['att'])}、季報 {len(new['fin'])}、"
         f"營收 {len(new['rev'])}、庫藏 {len(new['treasury'])}", "", "【處置預測】"]
    L += [f"{i}. {c['name']}({c['code']})｜{COND_NAME[c['main']]}｜第{c['times']}次\n   條件：{describe(c)}"
          for i, c in enumerate(m1, 1)] or ["無"]
    if disp.get("releases"):
        L += ["", "【處置出關】"] + [f"{d[5:].replace('-', '/')}：" + "、".join(f"{p['name']}({p['code']})" for p in ps)
                                for d, ps in sorted(disp["releases"].items())]
    L += ["", "【自結速報｜評分排序】"]
    L += [f"{i}. {a['name']}({a['code']})｜{a['score']:+d}｜{a['period']} EPS {a['eps']}，上季月均 {a['last_q_monthly']}"
          for i, a in enumerate(sorted(new["att"], key=lambda x: -x["score"])[:10], 1)] or ["無新自結資料"]
    L += ["", "【季報速報｜評分排序】"]
    L += [f"{i}. {a['name']}({a['code']})｜{a['score']:+d}｜{a['period']} EPS {a['eps']}，上季 {a['eps_prev_q']}"
          for i, a in enumerate(sorted(new["fin"], key=lambda x: -x["score"])[:10], 1)] or ["無新季報資料"]
    L += ["", "【營收速報｜有備註】"]
    L += [f"{i}. {r['name']}({r['code']})｜YoY {r['yoy']}%｜{r['note']}" for i, r in enumerate(rev_note[:10], 1)] or ["無"]
    L += ["", "【營收速報｜無備註】"]
    L += [f"{i}. {r['name']}({r['code']})｜YoY {r['yoy']}%、MoM {r['mom']}%"
          for i, r in enumerate(sorted(rev_plain, key=lambda x: -(x['yoy'] or 0))[:10], 1)] or ["無"]
    L += ["", "【庫藏股】"]
    L += [f"{i}. {t['name']}({t['code']})｜{t['lots'] or '—'}張｜{t['low']}~{t['high']}元"
          for i, t in enumerate(new["treasury"][:10], 1)] or ["無新庫藏股公告"]
    L += ["", "本資訊由程式自動整理，僅供參考，不構成投資建議；請以證交所、櫃買中心與公開資訊觀測站公告為準。"]
    text = "\n".join(L)
    write_json(OUT / "line.json", {"target": disp.get("target"), "text": text, "generated": now_tw().isoformat(timespec="minutes")})
    return {"text": text}


def touch_meta(job: str, d: date | None = None) -> None:
    meta = read_json(OUT / "meta.json", {}) or {}
    meta.setdefault("jobs", {})[job] = now_tw().strftime("%Y-%m-%d %H:%M")
    if d:
        meta.setdefault("dates", {})[job] = d.isoformat()
    meta["site_name"] = config.SITE_NAME
    if job != "mock":
        meta.pop("mock", None)
    daily_dir = OUT / "daily"
    meta["daily_dates"] = sorted((f.stem for f in daily_dir.glob("*.json")), reverse=True) if daily_dir.exists() else []
    nd = OUT / "nextday"
    meta["nextday_dates"] = sorted((f.stem for f in nd.glob("*.json")), reverse=True) if nd.exists() else []
    write_json(OUT / "meta.json", meta)
