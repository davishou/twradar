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


# 官方產業別名稱：AI 給這些就等於沒分出題材（多半是當時缺業務資料）
OFFICIAL = {"半導體", "電腦週邊", "光電", "通信網路", "電子零組件", "電子通路", "資訊服務", "其他電子", "生技醫療", "鋼鐵",
            "航運", "建材營造", "金融保險", "電機機械", "化學", "塑膠", "紡織纖維", "食品", "汽車", "觀光餐旅", "綠能環保",
            "數位雲端", "貿易百貨", "電器電纜", "其他", "水泥", "造紙", "橡膠", "玻璃陶瓷", "油電燃氣", "居家生活", "運動休閒",
            "文化創意", "農業科技", "產業待確認", "證券金融"}
WEAK_WORDS = ("資料不足", "官方產業別", "僅依", "僅有官方", "未提供", "無法判斷")
# 給 AI 參考的細分題材（台股常見的炒作與產業循環主題）
HINTS = ("被動元件(MLCC/電容/電阻/電感)、CCL銅箔基板、PCB、玻纖布銅箔、IC載板、光通訊/CPO矽光子、散熱、電源/BBU、"
         "機殼滑軌、伺服器代工、AI伺服器、記憶體、IC設計、晶圓代工、半導體設備、半導體廠務、先進封裝、封測、矽晶圓、"
         "網通交換器、低軌衛星、機器人、重電電網、軍工無人機、金屬材料(鎢鈷稀土)、銅價、鋼鐵、塑化、生技新藥、醫材、"
         "營建資產、航運、觀光、電動車、儲能電池、綠電、光學鏡頭、面板、LED、連接器線材、遊戲、電商")


def is_weak(entry: dict | None) -> bool:
    """AI 分類結果是否只是官方產業別（沒有真正分出題材）"""
    if not entry:
        return False
    return entry.get("theme") in OFFICIAL or any(w in (entry.get("reason") or "") for w in WEAK_WORDS)


def prefetch_business(fetch, codes: list[str], minutes: float = 10) -> int:
    """把還沒有『主要經營業務』的公司補抓進快取（族群分類用），每次最多 minutes 分鐘。不呼叫 AI"""
    cache = store.state("business", {}) or {}
    t0, n = time.time(), 0
    for c in codes:
        if (cache.get(c) or {}).get("text"):
            continue
        if time.time() - t0 > minutes * 60:
            break
        cache[c] = {"text": fetch(c), "t": date.today().isoformat()}
        n += 1
        time.sleep(1.5)
        if n % 50 == 0:
            store.save_state("business", cache)
    store.save_state("business", cache)
    return n


def _ai_prompt(lines: str, known: str, why: str) -> str:
    return (f"以下是{why}的台股，附上公司主要業務。請把每檔歸入一個『題材族群』，要比官方產業別更細，看得出它跟哪個產業循環或題材連動。\n"
            f"參考題材：{HINTS}。\n已有族群：{known}。\n"
            "規則：① 依主要業務判斷，選最核心、營收占比最大的產品；② 不要用官方產業別（如電子零組件、半導體、光電、其他電子）"
            "當題材，除非業務真的無法再細分；③ 都不適合時自創 2~6 字題材名並給一個 emoji；④ 不可編造業務。\n"
            f"{lines}\n\n格式：{{\"代號\": {{\"theme\": \"族群\", \"emoji\": \"只有新族群才填\", \"reason\": \"20 字內理由\"}}}}")


def reclassify_weak(names: dict[str, str], industries: dict[str, str], batch: int = 50, limit: int = 1500) -> dict:
    """把 themes.json 裡『AI 給了官方產業別』的股票，用已抓到的主要業務重新分類（需要 AI）。
    回傳 {"done": 重分類檔數, "changed": 換族群檔數, "left": 還缺業務資料的檔數}"""
    if not ai.enabled():
        return {"done": 0, "changed": 0, "left": 0, "error": "沒有 AI 金鑰"}
    js = _load_file()
    themes = js.get("themes", {})
    added = js.get("_ai_added", {}) or {}
    biz = store.state("business", {}) or {}
    weak = [c for c, a in added.items() if is_weak(a) and a.get("v", 1) < 2]
    ready = [c for c in weak if (biz.get(c) or {}).get("text")][:limit]
    done = changed = 0
    for i in range(0, len(ready), batch):
        chunk = ready[i:i + batch]
        lines = "\n".join(f"{c} {names.get(c) or added[c].get('name', '')}（產業：{industries.get(c, '')}）；主要業務：{biz[c]['text'][:180]}"
                          for c in chunk)
        res = ai.ask_json(_ai_prompt(lines, "、".join(t for t in themes if t not in OFFICIAL), "近期曾漲停"),
                          tag="reclassify", max_tokens=6000)
        if not isinstance(res, dict):
            continue
        today = date.today().isoformat()
        for c in chunk:
            r = res.get(c)
            if not (isinstance(r, dict) and r.get("theme")):
                continue
            t = str(r["theme"]).strip()[:10]
            old_t = added[c].get("theme")
            for v in themes.values():                       # 從舊族群拿掉
                if c in v.get("codes", []):
                    v["codes"].remove(c)
            th = themes.setdefault(t, {"emoji": str(r.get("emoji") or "📈")[:4], "codes": [], "keywords": []})
            th.setdefault("codes", []).append(c)
            added[c] = {"theme": t, "name": added[c].get("name") or names.get(c, ""), "date": today,
                        "reason": str(r.get("reason", ""))[:80], "v": 2, "was": old_t}
            done += 1
            changed += t != old_t
        js["themes"], js["_ai_added"] = {k: v for k, v in themes.items() if v.get("codes") or v.get("keywords")}, added
        _save_file(js)
    log.info("族群重分類：%d 檔（換族群 %d），還有 %d 檔缺業務資料", done, changed, len(weak) - len(ready))
    return {"done": done, "changed": changed, "left": len(weak) - len(ready)}


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
        res = ai.ask_json(_ai_prompt(lines, known, "今日漲停") + "\n若附有今日重大訊息，可參考訊息內容判斷題材。",
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
