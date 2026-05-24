"""Isolamento de memória por agente via GraphRef.OWNED."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .hierarchy import attach_subgraph, resolve_subgraph
from .matching import MatchResult
from .nodes import NodeKind
from .refs import GraphRefKind

if TYPE_CHECKING:
    from .node_types import MemoryNode
    from .store import CognitiveGraph

logger = logging.getLogger("arnaldo.graph.agent_subgraphs")


def ensure_agent_subgraph(graph: CognitiveGraph, synapse_id: str) -> CognitiveGraph:
    """Garante que o synapse tem sub-grafo OWNED. Cria se não existir."""
    node = graph.get_node(synapse_id)
    if node is None:
        raise KeyError(f"Synapse {synapse_id} não encontrada")
    if node.kind != NodeKind.SYNAPSE:
        raise TypeError(f"Nó {synapse_id} não é SYNAPSE (é {node.kind})")

    # Verifica se já tem OWNED
    for ref in node.subgraph_refs:
        if ref.kind == GraphRefKind.OWNED:
            sub = resolve_subgraph(graph, ref)
            if sub is not None:
                return sub

    # Cria novo sub-grafo OWNED
    from .store import CognitiveGraph as CG

    sub = CG()
    attach_subgraph(graph, synapse_id, sub, kind=GraphRefKind.OWNED)
    logger.debug("Criado sub-grafo OWNED para synapse %s", synapse_id)
    return sub


def route_memory_to_agent(
    graph: CognitiveGraph,
    synapse_id: str,
    memory_node: MemoryNode,
) -> bool:
    """Adiciona memory_node ao sub-grafo OWNED do agente."""
    try:
        sub = ensure_agent_subgraph(graph, synapse_id)
    except (KeyError, TypeError) as exc:
        logger.warning("route_memory_to_agent falhou: %s", exc)
        return False
    sub.add_node(memory_node)
    return True


def query_agent_context(
    graph: CognitiveGraph,
    synapse_id: str,
    query: str,
    *,
    top_k: int = 5,
) -> list[MatchResult]:
    """Busca no sub-grafo OWNED do agente."""
    node = graph.get_node(synapse_id)
    if node is None or node.kind != NodeKind.SYNAPSE:
        return []
    for ref in node.subgraph_refs:
        if ref.kind == GraphRefKind.OWNED:
            sub = resolve_subgraph(graph, ref)
            if sub is not None:
                return sub.match(query=query)[:top_k]
    return []
