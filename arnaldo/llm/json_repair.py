"""Reparo e decodificação tolerante de JSON retornado por modelos LLM."""

from __future__ import annotations

import json
from typing import Any


def decode_json_object(content: str) -> Any:
    """Decodifica JSON com tolerância a ruído comum de modelos.

    Estratégia: parse direto → remove fences → extrai objeto balanceado → corrige control chars.
    """
    cleaned = str(content or "").strip()
    if not cleaned:
        raise json.JSONDecodeError("empty JSON content", cleaned, 0)

    candidates = _json_decode_candidates(cleaned)
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            normalized = _escape_control_chars_in_json_strings(candidate)
            if normalized == candidate:
                continue
            try:
                return json.loads(normalized)
            except json.JSONDecodeError as normalized_exc:
                last_error = normalized_exc
                continue
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("unable to decode JSON object", cleaned, 0)


def _json_decode_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def _push(value: str) -> None:
        normalized = value.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    _push(text)
    without_fence = _strip_markdown_code_fence(text)
    _push(without_fence)

    for base in (text, without_fence):
        extracted = _extract_first_balanced_json_object(base)
        if extracted:
            _push(extracted)

    return candidates


def _strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 3:
        return stripped
    if not lines[-1].strip().startswith("```"):
        return stripped
    body = "\n".join(lines[1:-1]).strip()
    return body or stripped


def _extract_first_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    in_string = False
    escaped = False
    depth = 0
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _escape_control_chars_in_json_strings(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    changed = False

    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if ch == "\n":
                out.append("\\n")
                changed = True
                continue
            if ch == "\r":
                out.append("\\r")
                changed = True
                continue
            if ch == "\t":
                out.append("\\t")
                changed = True
                continue
            out.append(ch)
            continue

        out.append(ch)
        if ch == '"':
            in_string = True
            escaped = False

    if not changed:
        return text
    return "".join(out)


def looks_like_json_object(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return "{" in stripped and "}" in stripped and stripped.find("{") < stripped.rfind("}")
