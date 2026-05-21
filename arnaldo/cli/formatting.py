"""Funções de formatação de streaming para a CLI."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def format_trace_stream_line(row: dict[str, Any]) -> str:
    created_at = format_stream_timestamp(row.get("created_at"))
    event_type = str(row.get("event_type", "")).strip() or "trace_event"
    payload = row.get("payload")
    details = summarize_stream_payload(payload if isinstance(payload, dict) else {})
    if details:
        return f"[stream][{created_at}][trace] {event_type} | {details}"
    return f"[stream][{created_at}][trace] {event_type}"


def format_evidence_stream_line(row: dict[str, Any]) -> str:
    created_at = format_stream_timestamp(row.get("created_at"))
    record_type = str(row.get("record_type", "")).strip() or "evidence_record"
    summary = str(row.get("summary", "")).strip()
    payload = row.get("payload")
    details = summarize_stream_payload(payload if isinstance(payload, dict) else {})
    line = f"[stream][{created_at}][evidence] {record_type}"
    if summary:
        line += f" | {summary}"
    if details:
        line += f" | {details}"
    return line


def format_agent_bus_stream_line(row: dict[str, Any]) -> str:
    created_at = format_stream_timestamp(row.get("ts") or row.get("created_at"))
    event = str(row.get("event", "")).strip() or "agent_event"
    details = summarize_stream_payload(row)
    if details:
        return f"[stream][{created_at}][agent] {event} | {details}"
    return f"[stream][{created_at}][agent] {event}"


def format_prompt_stream_header(row: dict[str, Any]) -> str:
    created_at = format_stream_timestamp(row.get("created_at"))
    action = str(row.get("action", "")).strip()
    node_id = str(row.get("node_id", "")).strip()
    tier = str(row.get("tier", "")).strip()
    model = str(row.get("response_model", "")).strip()
    chat_kwargs = row.get("chat_kwargs") if isinstance(row.get("chat_kwargs"), dict) else {}
    max_tokens = int(chat_kwargs.get("max_tokens", 0) or 0)
    timeout = float(chat_kwargs.get("timeout", 0.0) or 0.0)
    details = []
    if action:
        details.append(f"action={action}")
    if tier:
        details.append(f"tier={tier}")
    if model:
        details.append(f"model={model}")
    if max_tokens > 0:
        details.append(f"max_tokens={max_tokens}")
    if timeout > 0:
        details.append(f"timeout={timeout:.1f}s")
    suffix = " | " + ", ".join(details) if details else ""
    return f"[stream][{created_at}][prompt] {node_id or 'synapse'}{suffix}"


def format_prompt_message_lines(row: dict[str, Any]) -> list[str]:
    messages = row.get("messages")
    if not isinstance(messages, list):
        return []
    lines: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = compact_stream_text(str(item.get("content", "")), limit=320)
        if not content:
            continue
        lines.append(f"  [{role}] {content}")
    return lines


def format_stream_timestamp(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return "--:--:--"
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return "--:--:--"
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone()
    return stamp.strftime("%H:%M:%S")


def summarize_stream_payload(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    parts: list[str] = []
    keys = [
        "wave_index",
        "topology",
        "execution_mode",
        "mode",
        "tier",
        "response_model",
        "message_count",
        "step_count",
        "workflow_steps",
        "index",
        "step_id",
        "action",
        "agent_id",
        "node_id",
        "capability_id",
        "status",
        "reason",
        "error",
        "count",
        "completed",
        "size",
    ]
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        rendered = str(value).strip()
        if not rendered:
            continue
        if len(rendered) > 120:
            rendered = rendered[:120].rstrip() + "..."
        parts.append(f"{key}={rendered}")
    if not parts:
        return ""
    return ", ".join(parts)


def compact_stream_text(value: str, *, limit: int = 320) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def parse_markdown_sections(markdown: str) -> list[tuple[str, str]]:
    lines = markdown.splitlines()
    sections: list[tuple[str, str]] = []
    title = ""
    buffer: list[str] = []
    pattern = re.compile(r"^##\s+(.+?)\s*$")
    for line in lines:
        match = pattern.match(line)
        if match:
            if title or buffer:
                sections.append((title, "\n".join(buffer).strip()))
            title = match.group(1).strip()
            buffer = []
            continue
        buffer.append(line)
    if title or buffer:
        sections.append((title, "\n".join(buffer).strip()))
    return sections


def compact_block(value: str) -> str:
    lines = [line.rstrip() for line in value.splitlines()]
    trimmed = [line for line in lines if line.strip()]
    text = "\n".join(trimmed).strip()
    if not text:
        return ""
    if len(text) > 800:
        return text[:800].rstrip() + "..."
    return text
