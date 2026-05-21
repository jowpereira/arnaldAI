"""Construção de requests e parsing de responses para Azure OpenAI."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .config import (
    API_STYLE_RESPONSES,
    API_STYLE_V1,
    TierConfig,
)
from .response_parser import (
    extract_chat_refusal,
    extract_message_content_text,
    extract_tool_call_arguments,
)


def build_url(tier_cfg: TierConfig, *, endpoint: str, api_version: str) -> str:
    """Constrói a URL apropriada por estilo de API."""
    effective_api_version = tier_cfg.api_version or api_version

    if tier_cfg.api_style == API_STYLE_RESPONSES:
        base = (tier_cfg.base_url or "").rstrip("/")
        if not base:
            raise ValueError(f"Tier '{tier_cfg.name}' (api_style=responses) precisa de base_url")
        if tier_cfg.api_version:
            return f"{base}/responses?api-version={tier_cfg.api_version}"
        return f"{base}/responses"

    if tier_cfg.api_style == API_STYLE_V1:
        base = (tier_cfg.base_url or "").rstrip("/")
        if not base:
            raise ValueError(f"Tier '{tier_cfg.name}' (api_style=v1) precisa de base_url")
        if tier_cfg.api_version:
            return f"{base}/chat/completions?api-version={tier_cfg.api_version}"
        return f"{base}/chat/completions"

    return (
        f"{(tier_cfg.base_url or endpoint).rstrip('/')}"
        f"/openai/deployments/{tier_cfg.model}/chat/completions"
        f"?api-version={effective_api_version}"
    )


def build_body(
    *,
    tier_cfg: TierConfig,
    messages: List[Dict[str, str]],
    temperature: Optional[float],
    max_tokens: Optional[int],
    response_format: Optional[Dict[str, Any]],
    reasoning_effort: Optional[str],
    reasoning_summary: Optional[str],
    extra: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Constrói o body da requisição para Chat Completions ou Responses API."""
    effective_max_tokens = max_tokens if max_tokens is not None else tier_cfg.default_max_tokens

    if tier_cfg.api_style == API_STYLE_RESPONSES:
        body: Dict[str, Any] = {
            "model": tier_cfg.model,
            "input": _messages_to_responses_input(messages),
            "max_output_tokens": effective_max_tokens,
        }
        if tier_cfg.supports_reasoning:
            reasoning_block: Dict[str, str] = {}
            effort = reasoning_effort or tier_cfg.default_reasoning_effort
            if effort:
                reasoning_block["effort"] = effort
            summary = reasoning_summary or tier_cfg.default_reasoning_summary
            if summary:
                reasoning_block["summary"] = summary
            if reasoning_block:
                body["reasoning"] = reasoning_block
        if response_format is not None:
            body["text"] = {"format": response_format}
        if extra:
            body.update(extra)
        return body

    body = {"messages": messages}
    if tier_cfg.uses_max_completion_tokens:
        body["max_completion_tokens"] = effective_max_tokens
        if not tier_cfg.supports_reasoning:
            body["temperature"] = (
                temperature if temperature is not None else tier_cfg.default_temperature
            )
    else:
        body["max_tokens"] = effective_max_tokens
        body["temperature"] = (
            temperature if temperature is not None else tier_cfg.default_temperature
        )

    if tier_cfg.api_style == API_STYLE_V1:
        body["model"] = tier_cfg.model

    if tier_cfg.supports_reasoning:
        effort = reasoning_effort or tier_cfg.default_reasoning_effort
        if effort:
            body["reasoning_effort"] = effort
        summary = reasoning_summary or tier_cfg.default_reasoning_summary
        if summary:
            body["reasoning_summary"] = summary

    if response_format is not None:
        body["response_format"] = response_format
    if extra:
        body.update(extra)
    return body


def _messages_to_responses_input(messages: List[Dict[str, str]]) -> Any:
    """Converte messages do Chat Completions para input da Responses API."""
    if not messages:
        return ""
    if len(messages) == 1 and messages[0].get("role") == "user":
        return messages[0].get("content", "")
    items = []
    for msg in messages:
        role = str(msg.get("role", "user")).strip() or "user"
        if role not in {"system", "developer", "user", "assistant"}:
            role = "user"
        content = msg.get("content", "")
        if isinstance(content, list):
            text = "\n".join(str(part) for part in content if str(part).strip())
        else:
            text = str(content)
        items.append(
            {
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": text}],
            }
        )
    return items


def parse_response(
    payload: Dict[str, Any],
    tier: str,
    tier_cfg: TierConfig,
) -> Dict[str, Any]:
    """Parseia resposta da API, retornando dict normalizado para LLMResponse."""
    if tier_cfg.api_style == API_STYLE_RESPONSES:
        return _parse_responses_api(payload, tier, tier_cfg)

    choices = payload.get("choices") or []
    if not choices:
        raise ValueError(f"Azure OpenAI retornou sem choices: {payload}")

    choice = choices[0]
    message = choice.get("message", {})
    content = extract_message_content_text(message.get("content", ""))
    refusal = extract_chat_refusal(message)
    if not content:
        parsed_payload = message.get("parsed")
        if isinstance(parsed_payload, (dict, list)):
            content = json.dumps(parsed_payload, ensure_ascii=False)
    if not content:
        content = extract_tool_call_arguments(message.get("tool_calls"))

    reasoning_summary = None
    if tier_cfg.supports_reasoning:
        reasoning_summary = (
            message.get("reasoning_summary")
            or choice.get("reasoning_summary")
            or (choice.get("reasoning", {}) or {}).get("summary")
        )

    return {
        "content": content,
        "tier": tier,
        "deployment": tier_cfg.model,
        "model": payload.get("model", tier_cfg.model),
        "finish_reason": choice.get("finish_reason", "stop"),
        "usage": payload.get("usage", {}),
        "reasoning_summary": reasoning_summary,
        "refusal": refusal,
        "raw": payload,
    }


def _parse_responses_api(
    payload: Dict[str, Any],
    tier: str,
    tier_cfg: TierConfig,
) -> Dict[str, Any]:
    """Parser para formato da Responses API."""
    status = payload.get("status", "")
    output_items = payload.get("output", []) or []
    if not output_items:
        raise ValueError(f"Responses API retornou sem output (status={status}): {payload}")

    content_chunks: list[str] = []
    refusal: str | None = None
    for item in output_items:
        if item.get("type") == "refusal":
            refusal = str(item.get("refusal", "")).strip() or refusal
            continue
        if item.get("type") != "message":
            continue
        for chunk in item.get("content", []) or []:
            chunk_type = chunk.get("type")
            if chunk_type in ("output_text", "text"):
                text = str(chunk.get("text", ""))
                if text:
                    content_chunks.append(text)
            elif chunk_type == "refusal":
                refusal = str(chunk.get("refusal", "")).strip() or refusal

    content_text = "\n".join(content_chunks).strip()

    raw_usage = payload.get("usage", {}) or {}
    normalized_usage = {
        "prompt_tokens": raw_usage.get("input_tokens", 0),
        "completion_tokens": raw_usage.get("output_tokens", 0),
        "total_tokens": raw_usage.get("total_tokens", 0),
    }
    out_details = raw_usage.get("output_tokens_details", {}) or {}
    if out_details.get("reasoning_tokens"):
        normalized_usage["reasoning_tokens"] = out_details["reasoning_tokens"]

    reasoning_block = payload.get("reasoning", {}) or {}
    reasoning_summary = reasoning_block.get("summary")

    return {
        "content": content_text,
        "tier": tier,
        "deployment": tier_cfg.model,
        "model": payload.get("model", tier_cfg.model),
        "finish_reason": status or "completed",
        "usage": normalized_usage,
        "reasoning_summary": reasoning_summary,
        "refusal": refusal,
        "raw": payload,
    }
