"""Funções compartilhadas de tracing e evidência para runtimes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from arnaldo.contracts import EvidenceRecord, RuntimeEvent, new_id, to_dict, utc_now
from arnaldo.storage import RunStore


def trace(store: RunStore, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    """Registra evento de trace no store."""
    event = RuntimeEvent(
        id=new_id("event"),
        run_id=run_id,
        created_at=utc_now(),
        event_type=event_type,
        payload=payload,
    )
    store.append_jsonl("trace.jsonl", to_dict(event))


def evidence(
    store: RunStore,
    run_id: str,
    task_id: str,
    record_type: str,
    summary: str,
    payload: Dict[str, Any],
) -> None:
    """Registra evidência no store."""
    record = EvidenceRecord(
        id=new_id("evidence"),
        run_id=run_id,
        task_id=task_id,
        created_at=utc_now(),
        record_type=record_type,
        summary=summary,
        payload=payload,
    )
    store.append_jsonl("evidence.jsonl", to_dict(record))


def resolve_sandbox_dir(raw_path: Any) -> Path | None:
    """Resolve e cria diretório de sandbox se especificado."""
    if not raw_path:
        return None
    path = Path(str(raw_path))
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_step_artifact(
    artifacts_path: Path | None,
    *,
    index: int,
    action: str,
    payload: Dict[str, Any],
) -> Path | None:
    """Escreve artefato de step no filesystem."""
    if artifacts_path is None:
        return None
    safe_action = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in action)
    path = artifacts_path / ("step-%02d-%s.json" % (index, safe_action))
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return path
