"""Utilidades de I/O e contagem para a CLI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def safe_read_json(path: Any) -> dict[str, Any]:
    if not isinstance(path, Path) or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def safe_read_jsonl(path: Any) -> list[dict[str, Any]]:
    if not isinstance(path, Path) or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def safe_pop_due_proactive_messages(kernel: Any, session_id: str) -> list[str]:
    handler = getattr(kernel, "pop_due_proactive_messages", None)
    if not callable(handler):
        return []
    try:
        rows = handler(session_id, limit=2)
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    messages = []
    for item in rows:
        text = str(item).strip()
        if text:
            messages.append(text)
    return messages


def safe_pending_proactive_count(kernel: Any, session_id: str) -> int:
    handler = getattr(kernel, "pending_proactive_count", None)
    if not callable(handler):
        return 0
    try:
        value = handler(session_id)
    except Exception:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        label = str(item.get(key, "")).strip()
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    return counts


def sorted_counts(counts: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def duration_from_trace(trace_rows: list[dict[str, Any]]) -> float | None:
    timestamps: list[datetime] = []
    for item in trace_rows:
        raw = str(item.get("created_at", "")).strip()
        if not raw:
            continue
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            timestamps.append(datetime.fromisoformat(raw))
        except ValueError:
            continue
    if len(timestamps) < 2:
        return None
    timestamps.sort()
    duration = (timestamps[-1] - timestamps[0]).total_seconds()
    return duration if duration >= 0 else None


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def list_run_dir_names(output_dir: Path) -> set[str]:
    if not output_dir.exists():
        return set()
    return {
        path.name for path in output_dir.iterdir() if path.is_dir() and path.name.startswith("run_")
    }


def discover_new_run_dir(output_dir: Path, known_run_dirs: set[str]) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = [
        path
        for path in output_dir.iterdir()
        if path.is_dir() and path.name.startswith("run_") and path.name not in known_run_dirs
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    selected = candidates[0]
    known_run_dirs.add(selected.name)
    return selected
