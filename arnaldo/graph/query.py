"""Funções de iteração e filtro sobre o grafo cognitivo."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Iterator

from .edges import EdgeKind, GraphEdge
from .nodes import GraphNode, NodeKind

if TYPE_CHECKING:
    from .store import CognitiveGraph


def iter_nodes(
    graph: CognitiveGraph,
    *,
    kind: NodeKind | None = None,
    domain: str | None = None,
    tag: str | None = None,
    active_only: bool = True,
) -> Iterator[GraphNode]:
    """Itera nós filtrando por kind, domain ou tag."""
    if kind is not None:
        ids: Iterable[str] = graph._by_kind.get(kind, set())
    elif domain is not None:
        ids = graph._by_domain.get(domain, set())
    elif tag is not None:
        ids = graph._by_tag.get(tag, set())
    else:
        ids = graph._nodes.keys()
    for node_id in ids:
        node = graph._nodes.get(node_id)
        if node is None:
            continue
        if active_only and not node.is_active:
            continue
        yield node


def iter_edges_from(
    graph: CognitiveGraph,
    node_id: str,
    *,
    kinds: Iterable[EdgeKind] | None = None,
    active_only: bool = True,
) -> Iterator[GraphEdge]:
    """Itera arestas saindo de ``node_id``."""
    kind_set = {k for k in kinds} if kinds is not None else None
    if node_id not in graph._g:
        return
    for _, target_id, key in graph._g.out_edges(node_id, keys=True):
        edge = graph._edges.get(key)
        if edge is None:
            continue
        if kind_set is not None and edge.kind not in kind_set:
            continue
        if active_only and not edge.is_active:
            continue
        yield edge


def iter_edges_to(
    graph: CognitiveGraph,
    node_id: str,
    *,
    kinds: Iterable[EdgeKind] | None = None,
    active_only: bool = True,
) -> Iterator[GraphEdge]:
    """Itera arestas entrando em ``node_id``."""
    kind_set = {k for k in kinds} if kinds is not None else None
    if node_id not in graph._g:
        return
    for source_id, _, key in graph._g.in_edges(node_id, keys=True):
        edge = graph._edges.get(key)
        if edge is None:
            continue
        if kind_set is not None and edge.kind not in kind_set:
            continue
        if active_only and not edge.is_active:
            continue
        yield edge


def iter_edges(
    graph: CognitiveGraph,
    *,
    kind: EdgeKind | None = None,
    active_only: bool = True,
) -> Iterator[GraphEdge]:
    """Itera todas as arestas do grafo."""
    for edge in graph._edges.values():
        if kind is not None and edge.kind != kind:
            continue
        if active_only and not edge.is_active:
            continue
        yield edge


def neighbors(
    graph: CognitiveGraph,
    node_id: str,
    *,
    kinds: Iterable[EdgeKind] | None = None,
) -> Iterator[GraphNode]:
    """Vizinhos imediatos (out-edges) filtrando por kind."""
    for edge in iter_edges_from(graph, node_id, kinds=kinds):
        neighbor = graph._nodes.get(edge.target_id)
        if neighbor is not None:
            yield neighbor
