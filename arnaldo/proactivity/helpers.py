"""Helpers para o ProactivityManager — classificação e parsing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def is_lightweight_chat_turn(task: Any) -> bool:
    """Detecta se o turno é um chat leve que não justifica mensagens proativas."""
    goal = task.goal if isinstance(getattr(task, "goal", None), dict) else {}
    if str(goal.get("type", "")).strip() != "open_ended_execution":
        return False
    context_raw = getattr(task, "context", {})
    context = context_raw if isinstance(context_raw, dict) else {}
    raw = str(context.get("raw_request") or context.get("original_request") or "").strip().lower()
    if not raw:
        return False
    if len(raw.split()) <= 5:
        return True
    return False


def is_generic_uncertainty(question: str) -> bool:
    """Detecta perguntas genéricas que não justificam proatividade."""
    lowered = question.strip().lower()
    generic_markers = (
        "qual artefato final",
        "nivel de profundidade",
        "quais acoes externas",
    )
    return any(marker in lowered for marker in generic_markers)


def parse_dt(raw: Any) -> datetime:
    """Parse ISO datetime com default para datetime.min UTC."""
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc) if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    text = str(raw or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
