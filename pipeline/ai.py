"""選用 AI：設定 ANTHROPIC_API_KEY 後啟用。未設定時所有呼叫回傳 None，程式改用規則版。"""
from __future__ import annotations

import json
import logging
import re

from . import config

log = logging.getLogger(__name__)
_client = None


def enabled() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def _get():
    global _client
    if _client is None:
        import anthropic  # 延遲匯入，未安裝也不影響其他功能
        headers = {"anthropic-workspace-id": config.ANTHROPIC_WORKSPACE_ID} if config.ANTHROPIC_WORKSPACE_ID else None
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, default_headers=headers)
    return _client


_tag = ""


def _status(**kw) -> None:
    """把最近 20 次 AI 呼叫的狀態寫到 data/state/ai_status.json（不含金鑰），方便排查"""
    try:
        from .util import now_tw, read_json, write_json
        p = config.STATE_DIR / "ai_status.json"
        old = read_json(p, {}) or {}
        calls = old.get("calls", []) if isinstance(old.get("calls"), list) else []
        calls.append({"time": now_tw().strftime("%Y-%m-%d %H:%M"), "tag": _tag, **kw})
        write_json(p, {"enabled": enabled(), "model": config.AI_MODEL,
                       "key_prefix": (config.ANTHROPIC_API_KEY[:7] + "…") if config.ANTHROPIC_API_KEY else "",
                       "calls": calls[-20:]})
    except Exception:  # noqa: BLE001
        pass


def ask(prompt: str, system: str = "", max_tokens: int = 2000, tag: str = "") -> str | None:
    global _tag
    if tag:
        _tag = tag
    if not enabled():
        _status(ok=False, error="沒有設定 ANTHROPIC_API_KEY")
        return None
    try:
        msg = _get().messages.create(
            model=config.AI_MODEL, max_tokens=max_tokens,
            system=system or "你是台灣股市資料分析助理，只根據提供的資料回答，使用繁體中文。",
            messages=[{"role": "user", "content": prompt}],
        )
        u = getattr(msg, "usage", None)
        _status(ok=True, stop=getattr(msg, "stop_reason", None),
                input_tokens=getattr(u, "input_tokens", None), output_tokens=getattr(u, "output_tokens", None))
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    except Exception as e:  # noqa: BLE001
        log.warning("AI 呼叫失敗：%s", e)
        _status(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
        return None


def ask_json(prompt: str, tag: str = "", **kw):
    """要求模型輸出 JSON；擷取第一個 JSON 區塊並解析"""
    txt = ask(prompt + "\n\n只輸出 JSON，不要其他文字。", tag=tag or "json", **kw)
    if not txt:
        return None
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M)
    m = re.search(r"(\{.*\}|\[.*\])", txt, re.S)
    try:
        return json.loads(m.group(1)) if m else None
    except json.JSONDecodeError:
        log.warning("AI 回傳非 JSON：%s", txt[:200])
        _status(ok=False, error="回傳不是 JSON", sample=txt[:300])
        return None
