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
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def ask(prompt: str, system: str = "", max_tokens: int = 2000) -> str | None:
    if not enabled():
        return None
    try:
        msg = _get().messages.create(
            model=config.AI_MODEL, max_tokens=max_tokens,
            system=system or "你是台灣股市資料分析助理，只根據提供的資料回答，使用繁體中文。",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    except Exception as e:  # noqa: BLE001
        log.warning("AI 呼叫失敗：%s", e)
        return None


def ask_json(prompt: str, **kw):
    """要求模型輸出 JSON；擷取第一個 JSON 區塊並解析"""
    txt = ask(prompt + "\n\n只輸出 JSON，不要其他文字。", **kw)
    if not txt:
        return None
    m = re.search(r"(\{.*\}|\[.*\])", txt, re.S)
    try:
        return json.loads(m.group(1)) if m else None
    except json.JSONDecodeError:
        log.warning("AI 回傳非 JSON：%s", txt[:200])
        return None
