"""Sinais epistêmicos — tipos de gap e curiosidade."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GapType(str, Enum):
    """Tipos de lacuna de conhecimento detectados pelo brain."""

    NONE = "none"
    GENUINE = "genuine"
    DECAYED = "decayed"
    RETRIEVAL_MISS = "retrieval_miss"


class SignalStatus(str, Enum):
    """Ciclo de vida de um sinal de curiosidade."""

    PENDING = "pending"
    FORAGING = "foraging"
    RESOLVED = "resolved"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class CuriositySignal:
    """Sinal de curiosidade — query + tipo de gap + prioridade."""

    query: str
    gap_type: GapType
    confidence: float
    domain: str = "unknown"
    priority: float = 0.5
    source_request: str = ""
    search_hints: tuple[str, ...] = ()
    related_nodes: tuple[str, ...] = ()
    status: SignalStatus = SignalStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def signal_id(self) -> str:
        """ID determinístico baseado em query + gap_type."""
        digest = hashlib.sha256(f"{self.query}:{self.gap_type.value}".encode()).hexdigest()[:12]
        return f"sig_{digest}"
