"""Eventos de telemetria para mutações no grafo cognitivo."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventKind(Enum):
    """Tipos de evento no grafo — I1 compliance (tipagem obrigatória)."""

    NODE_ADDED = "node_added"
    NODE_REMOVED = "node_removed"
    EDGE_ADDED = "edge_added"
    EDGE_REMOVED = "edge_removed"
    ACTIVATION = "activation"
    HEBBIAN = "hebbian"
    DECAY_SWEPT = "decay_swept"
    SUBGRAPH_ATTACHED = "subgraph_attached"
    SUBGRAPH_DETACHED = "subgraph_detached"
    WEIGHT_UPDATED = "weight_updated"
    STATUS_CHANGED = "status_changed"
    CONSOLIDATION = "consolidation"


@dataclass(slots=True)
class GraphEvent:
    """Telemetria mínima de mutação no grafo, alimenta Evidence Ledger."""

    kind: EventKind | str
    target_id: str
    at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            try:
                self.kind = EventKind(self.kind)
            except ValueError:
                pass  # Permite extensão futura sem quebrar
