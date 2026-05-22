"""Ledger append-only de GraphEvents — I6 Auditabilidade."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .events import GraphEvent

logger = logging.getLogger("arnaldo.graph.event_ledger")


def append_event(ledger_path: Path | None, event: GraphEvent) -> None:
    """Persiste event no ledger JSONL."""
    if ledger_path is None:
        return
    try:
        entry = {
            "kind": event.kind.value if hasattr(event.kind, "value") else str(event.kind),
            "target_id": event.target_id,
            "at": event.at.isoformat() if hasattr(event.at, "isoformat") else str(event.at),
        }
        if event.metadata:
            entry["metadata"] = event.metadata
        with ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except Exception:
        logger.warning("Falha ao persistir evento no ledger: %s", event.target_id, exc_info=True)
