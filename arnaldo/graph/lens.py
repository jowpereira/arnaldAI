"""GraphLens — views lógicas sobre o grafo cognitivo.

Expõe Agent Layer e Memory Layer como views zero-copy
sobre o CognitiveGraph unificado.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from .edges import EdgeKind, GraphEdge
from .nodes import NodeKind

if TYPE_CHECKING:
    from .node_types import GraphNode
    from .store import CognitiveGraph

# Kinds que pertencem a cada layer
_AGENT_KINDS = frozenset({NodeKind.SYNAPSE, NodeKind.CAPABILITY})
_MEMORY_KINDS = frozenset({NodeKind.MEMORY})


class GraphLens:
    """Views lógicas sobre o CognitiveGraph — sem cópia, sem overhead."""

    __slots__ = ("_graph",)

    def __init__(self, graph: CognitiveGraph) -> None:
        self._graph = graph

    # ── Node views ──

    def agent_nodes(self, *, active_only: bool = True) -> Iterator[GraphNode]:
        """Itera SynapseNode + CapabilityNode."""
        for kind in _AGENT_KINDS:
            yield from self._graph.iter_nodes(kind=kind, active_only=active_only)

    def memory_nodes(self, *, active_only: bool = True) -> Iterator[GraphNode]:
        """Itera MemoryNode."""
        yield from self._graph.iter_nodes(kind=NodeKind.MEMORY, active_only=active_only)

    # ── Edge views ──

    def agent_edges(self) -> Iterator[GraphEdge]:
        """Edges intra-Agent Layer."""
        for edge in self._graph.iter_edges():
            if edge.kind.is_agent_internal:
                yield edge

    def memory_edges(self) -> Iterator[GraphEdge]:
        """Edges intra-Memory Layer."""
        for edge in self._graph.iter_edges():
            if edge.kind.is_memory_internal:
                yield edge

    def cross_layer_edges(self) -> Iterator[GraphEdge]:
        """Edges RECALLS e INFORMS (Agent ↔ Memory)."""
        for edge in self._graph.iter_edges():
            if edge.kind.is_cross_layer:
                yield edge

    # ── Contadores ──

    @property
    def agent_node_count(self) -> int:
        return sum(len(self._graph._by_kind.get(k, set())) for k in _AGENT_KINDS)

    @property
    def memory_node_count(self) -> int:
        return len(self._graph._by_kind.get(NodeKind.MEMORY, set()))

    # ── Convenience ──

    def memories_recalled_by(self, synapse_id: str) -> Iterator[GraphNode]:
        """Memórias conectadas a uma synapse via RECALLS."""
        for edge in self._graph.iter_edges_from(synapse_id, kinds=[EdgeKind.RECALLS]):
            node = self._graph.get_node(edge.target_id)
            if node and node.kind == NodeKind.MEMORY:
                yield node

    def synapses_informed_by(self, memory_id: str) -> Iterator[GraphNode]:
        """Synapses conectadas a uma memória via INFORMS."""
        for edge in self._graph.iter_edges_from(memory_id, kinds=[EdgeKind.INFORMS]):
            node = self._graph.get_node(edge.target_id)
            if node and node.kind == NodeKind.SYNAPSE:
                yield node
