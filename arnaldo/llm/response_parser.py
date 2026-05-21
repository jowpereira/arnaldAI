"""Funções auxiliares para parsing de respostas LLM Azure OpenAI."""

from __future__ import annotations

import json
from typing import Any, Dict


def extract_message_content_text(content: Any) -> str:
    """Normaliza `message.content` em string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "output_text"}:
                    text = item.get("text", "")
                    if isinstance(text, dict):
                        value = text.get("value", "")
                        if value:
                            chunks.append(str(value))
                    elif text:
                        chunks.append(str(text))
                    continue
                nested = item.get("text")
                if isinstance(nested, dict):
                    value = nested.get("value", "")
                    if value:
                        chunks.append(str(value))
        return "\n".join(chunks).strip()
    return str(content or "")


def extract_chat_refusal(message: Dict[str, Any]) -> str | None:
    """Extrai refusal da mensagem (formato Chat Completions)."""
    refusal = message.get("refusal")
    if isinstance(refusal, str):
        stripped = refusal.strip()
        if stripped:
            return stripped
    content = message.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "refusal":
            continue
        raw = item.get("refusal")
        if not raw:
            continue
        stripped = str(raw).strip()
        if stripped:
            return stripped
    return None


def extract_tool_call_arguments(tool_calls: Any) -> str:
    """Extrai argumentos da primeira tool call."""
    if not isinstance(tool_calls, list):
        return ""
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        arguments = function.get("arguments")
        if arguments is None:
            continue
        text = str(arguments).strip()
        if text:
            return text
    return ""


def is_transient_llm_error(error: Exception) -> bool:
    """Verifica se o erro LLM é transitório (retry-safe)."""
    status = getattr(error, "status", None)
    if status in {408, 409, 429, 500, 502, 503, 504}:
        return True
    message = str(error).lower()
    transient_markers = (
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connection closed",
        "remote end closed connection",
        "network error",
    )
    return any(marker in message for marker in transient_markers)


def is_length_finish_reason(finish_reason: str) -> bool:
    """Verifica se o finish_reason indica truncamento por comprimento."""
    normalized = str(finish_reason or "").strip().lower()
    return normalized in {"length", "max_tokens", "max_output_tokens", "incomplete"}


def coerce_positive_int(value: Any) -> int | None:
    """Converte valor para int positivo ou None."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def next_max_tokens(
    current: int | None,
    *,
    tier_default: int,
    hard_cap: int,
) -> int:
    """Calcula próximo max_tokens para retry (grow by 1.6x)."""
    seed = current if current is not None else max(256, int(tier_default))
    grown = int(seed * 1.6)
    floor = max(seed + 256, tier_default)
    return min(hard_cap, max(grown, floor))
