"""族群分類：themes.json 固定歸類 → 關鍵字 → AI（快取）→ 官方產業別。"""
from __future__ import annotations

import logging

from . import ai, config, store
from .util import read_json

log = logging.getLogger(__name__)

IND_EMOJI = {
    "半導體": "🔬", "電腦週邊": "🖨️", "光電": "💡", "通信網路": "📡", "電子零組件": "🔌", "電子通路": "📦",
    "資訊服務": "💻", "其他電子": "🔧", "生技醫療": "🧬", "鋼鐵": "🔩", "航運": "🚢", "建材營造": "🏗️",
    "金融保險": "🏦", "電機機械": "⚙️", "化學": "⚗️", "塑膠": "🧪", "紡織纖維": "🧵", "食品": "🍜",
    "汽車": "🚗", "觀光餐旅": "🏨", "綠能環保": "🌱", "數位雲端": "☁️", "貿易百貨": "🛍️", "電器電纜": "🔋",
}


def load_themes() -> dict:
    return (read_json(config.ROOT / "themes.json", {}) or {}).get("themes", {})


def emoji(theme: str) -> str:
    t = load_themes().get(theme)
    return (t or {}).get("emoji") or IND_EMOJI.get(theme, "📈")


def classify(stocks: list[dict], context: dict[str, list[str]] | None = None) -> dict[str, dict]:
    """stocks: [{code,name,industry}]；context: {code: [近期公告主旨]}
    回傳 {code: {"theme": str, "source": "manual|keyword|ai|industry", "reason": str}}"""
    themes = load_themes()
    context = context or {}
    cache = store.state("theme_cache", {}) or {}
    out: dict[str, dict] = {}
    pending = []
    for s in stocks:
        c = s["code"]
        hit = next((t for t, v in themes.items() if c in v.get("codes", [])), None)
        if hit:
            out[c] = {"theme": hit, "source": "manual", "reason": "themes.json 指定"}
            continue
        text = s["name"] + " " + " ".join(context.get(c, []))
        hit = next((t for t, v in themes.items() if any(k and k in text for k in v.get("keywords", []))), None)
        if hit:
            out[c] = {"theme": hit, "source": "keyword", "reason": "名稱/公告關鍵字"}
            continue
        if c in cache:
            out[c] = cache[c]
            continue
        pending.append(s)

    if pending and ai.enabled():
        lines = "\n".join(f"{s['code']} {s['name']}（產業：{s.get('industry', '')}）"
                          f"{'；近期公告：' + '／'.join(context.get(s['code'], [])[:3]) if context.get(s['code']) else ''}"
                          for s in pending)
        known = "、".join(themes)
        res = ai.ask_json(
            "以下是今日漲停的台股。請依據你對這些公司主要業務的了解，把每檔歸入一個『題材族群』"
            f"（盡量使用這些既有名稱：{known}；都不適合時可自創 2~6 字的題材名）。\n"
            "若不確定公司業務，請回傳官方產業別作為族群並在 reason 註明不確定。\n"
            f"{lines}\n\n格式：{{\"代號\": {{\"theme\": \"族群\", \"reason\": \"一句話理由\"}}}}")
        if isinstance(res, dict):
            for s in pending:
                r = res.get(s["code"])
                if isinstance(r, dict) and r.get("theme"):
                    out[s["code"]] = cache[s["code"]] = {"theme": str(r["theme"])[:10], "source": "ai",
                                                         "reason": str(r.get("reason", ""))[:60]}
            store.save_state("theme_cache", cache)
    for s in pending:
        out.setdefault(s["code"], {"theme": s.get("industry") or "其他", "source": "industry", "reason": "官方產業別"})
    return out
