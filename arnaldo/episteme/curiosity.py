"""Motor de curiosidade — prioriza sinais de busca."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from .signals import CuriositySignal, GapType

if TYPE_CHECKING:
    from arnaldo.graph.store import CognitiveGraph

logger = logging.getLogger("arnaldo.episteme")

# Mapa de urgência por GapType
_URGENCY: dict[GapType, float] = {
    GapType.GENUINE: 1.0,
    GapType.DECAYED: 0.7,
    GapType.RETRIEVAL_MISS: 0.3,
    GapType.NONE: 0.0,
}


class CuriosityEngine:
    """Filtra e prioriza sinais de curiosidade."""

    def __init__(
        self,
        *,
        min_priority: float = 0.3,
        max_signals_per_run: int = 3,
    ) -> None:
        self.min_priority = min_priority
        self.max_signals_per_run = max_signals_per_run

    # ── Prioridade contextual ────────────────────────────────────────

    def compute_priority(
        self,
        signal: CuriositySignal,
        graph: CognitiveGraph,
    ) -> float:
        """Calcula prioridade: domain_relevance*0.5 + urgency*0.3 + staleness*0.2."""
        from arnaldo.graph.nodes import NodeKind, NodeStatus

        domain = signal.domain or "unknown"
        domain_nodes = [
            n
            for n in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False)
            if str(n.domain or "unknown") == domain
        ]
        total_memory = sum(1 for _ in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False))

        # domain_relevance: 0 nós no domínio = alta relevância (1.0) para buscar
        if total_memory == 0:
            domain_relevance = 1.0
        else:
            proportion = len(domain_nodes) / total_memory
            domain_relevance = 1.0 - proportion

        urgency = _URGENCY.get(signal.gap_type, 0.0)

        # staleness: proporção de STALE+ARCHIVED no domínio
        if not domain_nodes:
            staleness = 0.0
        else:
            stale_count = sum(
                1 for n in domain_nodes if n.status in (NodeStatus.STALE, NodeStatus.ARCHIVED)
            )
            staleness = stale_count / len(domain_nodes)

        return domain_relevance * 0.5 + urgency * 0.3 + staleness * 0.2

    # ── Priorização ──────────────────────────────────────────────────

    def prioritize(
        self,
        signals: list[CuriositySignal],
        graph: CognitiveGraph | None = None,
    ) -> list[CuriositySignal]:
        """Ordena sinais por prioridade e filtra abaixo do mínimo."""
        if graph is not None:
            signals = [
                replace(signal, priority=self.compute_priority(signal, graph)) for signal in signals
            ]
        filtered = [s for s in signals if s.priority >= self.min_priority]
        filtered.sort(key=lambda s: s.priority, reverse=True)
        return filtered[: self.max_signals_per_run]

    def should_forage(self, signal: CuriositySignal, *, has_web_search: bool) -> bool:
        """Decide se deve buscar externamente para este sinal."""
        if signal.gap_type == GapType.RETRIEVAL_MISS:
            return False
        if signal.gap_type == GapType.DECAYED:
            return has_web_search and signal.priority >= 0.5
        return has_web_search
