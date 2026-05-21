"""Operações de memória do kernel — episodic chain e bridges."""

from __future__ import annotations

from arnaldo.contracts import new_id
from arnaldo.graph import EdgeKind, GraphEdge, MemoryNode, NodeKind
from arnaldo.memory import MemoryStore


def link_episodic_chain(memory: MemoryStore, current_run_id: str, session_id: str) -> None:
    """Cria edge TEMPORAL_BEFORE entre episodic memories consecutivas da sessão."""
    graph = memory.load_graph()
    # Verifica se o current_run_id existe no grafo
    if graph.get_node(current_run_id) is None:
        return

    previous_id: str | None = None
    previous_ts: str | None = None
    for node in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False):
        if not isinstance(node, MemoryNode):
            continue
        payload = node.payload if isinstance(node.payload, dict) else {}
        if payload.get("session_id") != session_id:
            continue
        if node.id == current_run_id:
            continue
        if not payload.get("run_id"):
            continue
        recorded = str(node.bitemp.recorded_at)
        if previous_ts is None or recorded > previous_ts:
            previous_ts = recorded
            previous_id = node.id

    if previous_id:
        edge = GraphEdge(
            id=new_id("edge"),
            source_id=previous_id,
            target_id=current_run_id,
            kind=EdgeKind.TEMPORAL_BEFORE,
            weight=0.8,
        )
        try:
            graph.add_edge(edge)
        except KeyError:
            pass
