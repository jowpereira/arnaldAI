"""Dynamic synapse routing — seleção neural de synapses via matching."""

from __future__ import annotations

import heapq
from typing import TYPE_CHECKING

from ..edges import EdgeKind
from ..intent import classify_intent
from ..matching import HybridMatcher, MatchResult
from ..nodes import NodeKind

if TYPE_CHECKING:
    from ..store import CognitiveGraph


def select_synapses_for_request(
    graph: CognitiveGraph,
    request: str,
    *,
    matcher: HybridMatcher | None = None,
    max_synapses: int = 5,
    min_score: float = 0.15,
) -> list[MatchResult]:
    """Seleciona synapses mais relevantes para um request via matching híbrido.

    Substitui a seleção estática por organização — o grafo decide
    dinamicamente quais synapses ativar baseado em:
    - Similaridade semântica (embeddings)
    - Posição no grafo (vizinhança)
    - Peso plástico (consolidação via uso)
    """
    m = matcher or HybridMatcher(
        top_k_entry=8,
        max_hops=2,
        max_results=max_synapses * 2,
    )

    results = m.retrieve(
        graph,
        query=request,
        intent=classify_intent(request),
        node_kinds=[NodeKind.SYNAPSE.value],
    )

    # Filtra por score mínimo e limita
    filtered = [r for r in results if r.score >= min_score]
    return filtered[:max_synapses]


def dijkstra_weighted_path(
    graph: CognitiveGraph,
    source_id: str,
    target_id: str,
    *,
    edge_kinds: tuple[EdgeKind, ...] | None = None,
    max_cost: float = 10.0,
) -> list[str] | None:
    """Encontra caminho de menor custo (1/weight) entre dois nós.

    Usa Dijkstra com peso invertido: arestas fortes = custo baixo.
    Arestas fracas (weight ≈ 0) = custo alto → path evita.

    Returns:
        Lista de node_ids do source ao target, ou None se inalcançável.
    """
    if source_id == target_id:
        return [source_id]

    # dist[node_id] = menor custo acumulado
    dist: dict[str, float] = {source_id: 0.0}
    prev: dict[str, str | None] = {source_id: None}
    # heap: (cost, node_id)
    heap: list[tuple[float, str]] = [(0.0, source_id)]
    visited: set[str] = set()

    allowed_kinds = edge_kinds or (EdgeKind.ACTIVATES, EdgeKind.REQUIRES)

    while heap:
        cost, current = heapq.heappop(heap)
        if current in visited:
            continue
        visited.add(current)

        if current == target_id:
            # Reconstrói path
            path: list[str] = []
            node: str | None = target_id
            while node is not None:
                path.append(node)
                node = prev.get(node)
            path.reverse()
            return path

        for edge in graph.iter_edges_from(current, kinds=list(allowed_kinds)):
            if not edge.is_active:
                continue
            neighbor = edge.target_id
            if neighbor in visited:
                continue
            # Custo = 1/weight (peso alto = custo baixo)
            edge_cost = 1.0 / max(edge.weight, 0.01)
            new_cost = cost + edge_cost
            if new_cost > max_cost:
                continue
            if new_cost < dist.get(neighbor, float("inf")):
                dist[neighbor] = new_cost
                prev[neighbor] = current
                heapq.heappush(heap, (new_cost, neighbor))

    return None  # Inalcançável


def find_best_execution_path(
    graph: CognitiveGraph,
    candidates: list[MatchResult],
    *,
    max_path_length: int = 8,
) -> list[str]:
    """Dado candidatos do matcher, encontra o melhor path de execução.

    Estratégia:
    1. Ordena candidatos por score
    2. Tenta conectar top candidatos via dijkstra
    3. Se não conecta, executa independentemente (paralelo)
    """
    if not candidates:
        return []

    # Pega top candidatos como pontos de execução
    ordered = sorted(candidates, key=lambda r: r.score, reverse=True)
    path: list[str] = [ordered[0].node.id]

    for result in ordered[1:]:
        if len(path) >= max_path_length:
            break
        # Tenta encontrar conexão com último nó do path
        connection = dijkstra_weighted_path(graph, path[-1], result.node.id, max_cost=5.0)
        if connection and len(connection) <= 4:
            # Adiciona nós intermediários (exceto o primeiro que já está no path)
            path.extend(connection[1:])
        else:
            # Sem conexão direta — adiciona isoladamente
            path.append(result.node.id)

    return path
