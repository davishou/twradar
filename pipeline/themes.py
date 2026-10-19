"""族群分類與漲停原因。

分類順序：themes.json 指定（codes）→ 關鍵字 → AI（讀營業項目＋當日重大訊息）→ 官方產業別。
AI 判斷的結果會寫回 themes.json：股票代號加進該族群的 codes，並記在 _ai_added，
下次直接沿用，也方便人工檢查。想改分類，直接把代號移到別的族群，再從 _ai_added 刪掉即可。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date

from . import ai, config, store
from .util import read_json

log = logging.getLogger(__name__)
THEMES_FILE = config.ROOT / "themes.json"

IND_EMOJI = {
    "半導體": "🔬", "電腦週邊": "🖨️", "光電": "💡", "通信網路": "📡", "電子零組件": "🔌", "電子通路": "📦",
    "資訊服務": "💻", "其他電子": "🔧", "生技醫療": "🧬", "鋼鐵": "🔩", "航運": "🚢", "建材營造": "🏗️",
    "金融保險": "🏦", "電機機械": "⚙️", "化學": "⚗️", "塑膠": "🧪", "紡織纖維": "🧵", "食品": "🍜",
    "汽車": "🚗", "觀光餐旅": "🏨", "綠能環保": "🌱", "數位雲端": "☁️", "貿易百貨": "🛍️", "電器電纜": "🔋",
}


def _load_file() -> dict:
    return read_json(THEMES_FILE, {}) or {}


def load_themes() -> dict:
    return _load_file().get("themes", {})


def _save_file(js: dict) -> None:
    """一個族群一行，維持原本好讀好改的格式"""
    lines = ["{"]
    keys = [k for k in js if k != "themes"]
    for k in keys:
        lines.append(f"  {json.dumps(k, ensure_ascii=False)}: {_dump_block(js[k])},")
    lines.append('  "themes": {')
    items = list(js.get("themes", {}).items())
    for i, (t, v) in enumerate(items):
        lines.append(f"    {json.dumps(t, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}{',' if i < len(items) - 1 else ''}")
    lines.append("  }")
    lines.append("}")
    THEMES_FILE.write_text("\n".join(lines) + "\n", "utf-8")


def _dump_block(v) -> str:
    if isinstance(v, dict) and v and all(isinstance(x, dict) for x in v.values()):
        inner = ",\n".join(f"    {json.dumps(k, ensure_ascii=False)}: {json.dumps(x, ensure_ascii=False)}" for k, x in v.items())
        return "{\n" + inner + "\n  }"
    return json.dumps(v, ensure_ascii=False)


def emoji(theme: str) -> str:
    t = load_themes().get(theme)
    return (t or {}).get("emoji") or IND_EMOJI.get(theme, "📈")


# ------------------------------------------------------------------ 營業項目

def businesses(codes: list[str], fetch=None) -> dict[str, str]:
    """{code: 主要經營業務}，快取在 data/state/business.json；抓不到的 7 天後再試"""
    cache = store.state("business", {}) or {}
    today = date.today().isoformat()
    changed = False
    for c in codes:
        hit = cache.get(c)
        if hit and (hit.get("text") or hit.get("t", "") > (date.fromordinal(date.today().toordinal() - 7)).isoformat()):
            continue
        if not fetch:
            continue
        txt = fetch(c)
        cache[c] = {"text": txt, "t": today}
        changed = True
        time.sleep(1.5)
    if changed:
        store.save_state("business", cache)
    return {c: (cache.get(c) or {}).get("text", "") for c in codes}


# ------------------------------------------------------------------ 分類

def classify(stocks: list[dict], context: dict[str, list[str]] | None = None,
             biz: dict[str, str] | None = None) -> dict[str, dict]:
    """stocks: [{code,name,industry}]；context: {code: [當日公告主旨]}；biz: {code: 主要經營業務}
    回傳 {code: {"theme": str, "source": "manual|ai|keyword|industry", "reason": str}}"""
    js = _load_file()
    themes = js.get("themes", {})
    added = js.get("_ai_added", {}) or {}
    context = context or {}
    biz = biz or {}
    cache = store.state("theme_cache", {}) or {}
    out: dict[str, dict] = {}
    pending = []
    for s in stocks:
        c = s["code"]
        hit = next((t for t, v in themes.items() if c in v.get("codes", [])), None)
        if hit:
            a = added.get(c)
            out[c] = {"theme": hit, "source": "ai" if a and a.get("theme") == hit else "manual",
                      "reason": (a or {}).get("reason") or "themes.json 指定"}
            continue
        text = s["name"] + " " + " ".join(context.get(c, []))
        hit = next((t for t, v in themes.items() if any(k and k in text for k in v.get("keywords", []))), None)
        if hit:
            out[c] = {"theme": hit, "source": "keyword", "reason": "名稱/公告關鍵字"}
            continue
        if not ai.enabled() and c in cache:
            out[c] = cache[c]
            continue
        pending.append(s)

    if pending and ai.enabled():
        lines = "\n".join(
            f"{s['code']} {s['name']}（產業：{s.get('industry', '')}）"
            f"{'；主要業務：' + biz[s['code']][:150] if biz.get(s['code']) else ''}"
            f"{'；今日公告：' + '／'.join(context.get(s['code'], [])[:3]) if context.get(s['code']) else ''}"
            for s in pending)
        known = "、".join(themes)
        res = ai.ask_json(
            "以下是今日漲停的台股，附上公司主要業務與今日重大訊息。請把每檔歸入一個『題材族群』。\n"
            f"優先使用這些既有族群：{known}。\n"
            "都不適合時才自創 2~6 字的題材名（例如『玻纖』『光學鏡頭』），同時給一個代表的 emoji。\n"
            "不要用『其他』這種籠統名稱；資料不足時用官方產業別，並在 reason 註明。\n"
            f"{lines}\n\n格式：{{\"代號\": {{\"theme\": \"族群\", \"emoji\": \"只有新族群才填\", \"reason\": \"20 字內理由\"}}}}",
            tag="classify", max_tokens=6000)
        if isinstance(res, dict):
            today = date.today().isoformat()
            for s in pending:
                r = res.get(s["code"])
                if not (isinstance(r, dict) and r.get("theme")):
                    continue
                t = str(r["theme"]).strip()[:10]
                reason = str(r.get("reason", ""))[:80]
                out[s["code"]] = {"theme": t, "source": "ai", "reason": reason}
                th = themes.setdefault(t, {"emoji": str(r.get("emoji") or "📈")[:4], "codes": [], "keywords": []})
                if s["code"] not in th.setdefault("codes", []):
                    th["codes"].append(s["code"])
                added[s["code"]] = {"theme": t, "name": s["name"], "date": today, "reason": reason}
            js["themes"] = themes
            js["_ai_added"] = added
            _save_file(js)
            log.info("AI 新分類 %d 檔，已寫回 themes.json", sum(1 for s in pending if out.get(s["code"], {}).get("source") == "ai"))
    for s in pending:
        out.setdefault(s["code"], {"theme": s.get("industry") or "其他", "source": "industry", "reason": "官方產業別"})
    return out


# ------------------------------------------------------------------ 漲停原因

def _short_biz(text: str, industry: str) -> str:
    t = (text or "").strip()
    if not t:
        return f"{industry}業" if industry else ""
    for sep in ("。", "；", ";"):
        t = t.split(sep)[0]
    return t[:40] + ("…" if len(t) > 40 else "")


def explain(stocks: list[dict], context: dict[str, list[str]], biz: dict[str, str], use_ai: bool = True) -> dict[str, str]:
    """每檔一句漲停原因。有 AI 時依當日重大訊息與業務撰寫；否則用規則組句。"""
    count = {}
    for s in stocks:
        count[s["theme"]] = count.get(s["theme"], 0) + 1
    rule = {}
    for s in stocks:
        subj = (context.get(s["code"]) or [""])[0]
        parts = [_short_biz(biz.get(s["code"], ""), s.get("industry", ""))]
        parts.append(f"今日公告：{subj[:40]}" if subj else "今日無重大訊息")
        if count[s["theme"]] > 1:
            parts.append(f"同族群 {count[s['theme']]} 檔漲停")
        rule[s["code"]] = "，".join(p for p in parts if p) + "。"
    if not (use_ai and ai.enabled() and stocks):
        return rule
    lines = "\n".join(
        f"{s['code']} {s['name']}｜族群：{s['theme']}（今日同族群 {count[s['theme']]} 檔）"
        f"｜業務：{(biz.get(s['code']) or s.get('industry', ''))[:120]}"
        f"｜今日重大訊息：{'／'.join(context.get(s['code'], [])[:3]) or '無'}"
        for s in stocks)
    res = ai.ask_json(
        "以下是今日漲停的台股。請為每檔寫一句 50 字內的漲停原因。\n"
        "規則：有今日重大訊息就依訊息說明（例如營收創新高、接獲訂單）；沒有訊息就寫主要業務，"
        "同族群多檔漲停時寫『族群連動』。只能根據提供的資料，不可編造新聞、數字或客戶名稱。\n"
        f"{lines}\n\n格式：{{\"代號\": \"原因\"}}", tag="why", max_tokens=6000)
    if isinstance(res, dict):
        for k, v in res.items():
            if k in rule and isinstance(v, str) and v.strip():
                rule[k] = v.strip()[:80]
    return rule
