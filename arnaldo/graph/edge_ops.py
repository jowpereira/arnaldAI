"""Operações idempotentes sobre arestas do grafo cognitivo."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .edges import EdgeKind, GraphEdge

logger = logging.getLogger("arnaldo.graph.edge_ops")

if TYPE_CHECKING:
    from .store import CognitiveGraph


def ensure_edge(
    graph: CognitiveGraph,
    *,
    source_id: str,
    target_id: str,
    kind: EdgeKind,
    weight: float,
) -> None:
    """Cria ou atualiza aresta — idempotente, com guard de existência."""
    if not (graph.has_node(source_id) and graph.has_node(target_id)):
        logger.debug("ensure_edge skipped: missing node(s) %s→%s", source_id, target_id)
        return
    clamped = max(0.0, min(1.0, float(weight)))
    for edge in graph.iter_edges_from(source_id, kinds=[kind], active_only=False):
        if edge.target_id == target_id:
            if abs(edge.weight - clamped) > 1e-9:
                graph.add_edge(edge.with_weight(clamped))
            return
    graph.add_edge(
        GraphEdge.connect(source_id=source_id, target_id=target_id, kind=kind, weight=clamped)
    )
