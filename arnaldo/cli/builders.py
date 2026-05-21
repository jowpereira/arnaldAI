"""Construtores de preview de resposta para a CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .formatting import compact_block, parse_markdown_sections
from .utils import safe_read_jsonl


def build_agent_response_preview(result: Any, *, max_chars: int = 2200) -> str:
    files = dict(getattr(result, "files", {}) or {})
    selected: list[str] = []
    step_preview = build_latest_step_preview(files)
    if step_preview:
        selected.append(step_preview)

    artifact_preview = build_artifact_preview(files)
    if artifact_preview:
        selected.append(artifact_preview)

    preview = "\n\n".join(part for part in selected if part).strip()
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + "..."
    return preview


def build_chat_response(result: Any, *, max_chars: int = 1200) -> str:
    files = dict(getattr(result, "files", {}) or {})
    artifact_path = files.get("artifact")
    if isinstance(artifact_path, Path) and artifact_path.exists():
        try:
            artifact = artifact_path.read_text(encoding="utf-8").strip()
        except Exception:
            artifact = ""
        if artifact:
            sections = parse_markdown_sections(artifact)
            for title, body in sections:
                if title.strip().lower() in {
                    "resposta",
                    "resposta final",
                    "answer",
                    "final answer",
                }:
                    compact = compact_block(body)
                    if compact:
                        return compact[:max_chars]

    step_preview = build_latest_step_preview(files)
    if step_preview:
        lines = []
        for raw in step_preview.splitlines():
            cleaned = raw.strip()
            if cleaned.startswith("- "):
                lines.append(cleaned[2:].strip())
        if lines:
            joined = "\n".join(lines[:3]).strip()
            if joined:
                return joined[:max_chars]
        compact_step = compact_block(step_preview)
        if compact_step:
            return compact_step[:max_chars]

    artifact_preview = build_artifact_preview(files)
    if artifact_preview:
        return artifact_preview[:max_chars]
    return ""


def build_latest_step_preview(files: dict[str, Any]) -> str:
    evidence_rows = safe_read_jsonl(files.get("evidence"))
    for row in reversed(evidence_rows):
        record_type = str(row.get("record_type", "")).strip()
        if record_type not in {"step_completed", "step_fallback", "step_failed"}:
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        result = payload.get("result")
        if isinstance(result, dict):
            step_lines: list[str] = []
            status = str(result.get("status", "")).strip()
            if status:
                step_lines.append(f"status: {status}")
            sections = result.get("sections")
            if isinstance(sections, list):
                for section in sections[:3]:
                    if isinstance(section, str) and section.strip():
                        step_lines.append(section.strip())
            evidence = result.get("evidence")
            if isinstance(evidence, list) and evidence:
                evidence_text = ", ".join(
                    item.strip() for item in evidence[:2] if isinstance(item, str) and item.strip()
                )
                if evidence_text:
                    step_lines.append(f"evidence: {evidence_text}")
            uncertainties = result.get("uncertainties")
            if isinstance(uncertainties, list) and uncertainties:
                uncertainty_text = ", ".join(
                    item.strip()
                    for item in uncertainties[:2]
                    if isinstance(item, str) and item.strip()
                )
                if uncertainty_text:
                    step_lines.append(f"uncertainties: {uncertainty_text}")
            if step_lines:
                return "Output do Synapse:\n" + "\n".join(f"- {line}" for line in step_lines)
        error = str(payload.get("error", "")).strip()
        if error:
            return "Output do Synapse:\n- error: " + error
    return ""


def build_artifact_preview(files: dict[str, Any]) -> str:
    artifact_path = files.get("artifact")
    if not isinstance(artifact_path, Path) or not artifact_path.exists():
        return ""
    try:
        artifact = artifact_path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if not artifact:
        return ""

    sections = parse_markdown_sections(artifact)
    preferred_titles = [
        "resposta",
        "resposta final",
        "final answer",
        "answer",
        "summary",
        "goal",
        "step outputs",
        "next actions",
    ]
    selected: list[str] = []
    seen_titles: set[str] = set()
    for wanted in preferred_titles:
        for title, body in sections:
            normalized = title.strip().lower()
            if normalized != wanted:
                continue
            if normalized in seen_titles:
                continue
            compact_body = compact_block(body)
            if not compact_body:
                continue
            seen_titles.add(normalized)
            selected.append(f"{title}:\n{compact_body}")
            break

    if not selected:
        first_non_empty = ""
        for _, body in sections:
            compact_body = compact_block(body)
            if compact_body:
                first_non_empty = compact_body
                break
        if first_non_empty:
            selected.append(first_non_empty)

    if not selected:
        selected.append(compact_block(artifact))

    return "\n\n".join(part for part in selected if part).strip()
