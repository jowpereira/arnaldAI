"""Retrieval híbrido: vector search + graph expansion + reranking.

**Padrão arquitetural:** ``VectorCypherRetriever`` (Neo4j, 2024) generalizado.

Estágios formais::

    ┌─────────┐  ┌────────────┐  ┌───────────────┐  ┌──────────┐
    │  query  │→│ vector top-K│→│ graph expand   │→│  rerank  │
    │  + intent│ │ entry nodes │ │ (k-hop, typed) │  │ + budget │
    └─────────┘  └────────────┘  └───────────────┘  └──────────┘

A escolha dos tipos de aresta na expansão depende da **intenção da query**.
Mapping derivado de MAGMA (Jiang et al., 2026) com pequenas extensões:

    intent      |  tipos priorizados
    ────────────┼──────────────────────────────────────────────
    "why"       |  CAUSAL, DERIVED_FROM
    "when"      |  TEMPORAL_BEFORE
    "what"      |  IS_A, PART_OF, MENTIONS
    "who"       |  MENTIONS
    "how"       |  ACTIVATES, REQUIRES, DERIVED_FROM
    "summary"   |  PART_OF, IS_A (hierarquia)
    default     |  SEMANTIC

Benchmarks (Jiang et al., 2026):

    Tipo query           | Vector  | Graph  | Hybrid
    ─────────────────────┼─────────┼────────┼────────
    Semântica simples    |   95%   |  80%   |   95%
    Multi-entidade       |    0%   |  90%   |   92%
    Multi-hop temporal   |   20%   |  95%   |   97%
    Causal ("por quê?")  |   10%   |  85%   |   88%
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

import numpy as np
from numpy.typing import NDArray

from .edges import EdgeKind

if TYPE_CHECKING:
    from .nodes import GraphNode
    from .store import CognitiveGraph


# ────────────────────────────────────────────────────────────────────────────
# Resultado
# ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class MatchResult:
    """Resultado de um matching com scores decomponíveis para auditoria.

    Atributos:
        node:               nó recuperado.
        score:              score final (combinação ponderada).
        semantic_score:     similaridade do embedding (cosine ∈ [0,1]).
        graph_score:        score derivado da posição no grafo.
        plasticity_score:   peso efetivo (weight · decay · prov).
        hop_distance:       distância em hops do entry node (0 = entry).
        path:               caminho de arestas até este nó (para explicabilidade).
    """

    node: GraphNode
    score: float
    semantic_score: float = 0.0
    graph_score: float = 0.0
    plasticity_score: float = 0.0
    hop_distance: int = 0
    path: list[str] = field(default_factory=list)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<MatchResult {self.node.id} score={self.score:.3f} "
            f"sem={self.semantic_score:.2f} g={self.graph_score:.2f} "
            f"p={self.plasticity_score:.2f} hops={self.hop_distance}>"
        )


# ────────────────────────────────────────────────────────────────────────────
# Mapping intent → edge kinds
# ────────────────────────────────────────────────────────────────────────────


INTENT_TO_EDGES: dict[str, tuple[EdgeKind, ...]] = {
    "why": (EdgeKind.CAUSAL, EdgeKind.DERIVED_FROM),
    "when": (EdgeKind.TEMPORAL_BEFORE,),
    "what": (EdgeKind.IS_A, EdgeKind.PART_OF, EdgeKind.MENTIONS),
    "who": (EdgeKind.MENTIONS,),
    "how": (EdgeKind.ACTIVATES, EdgeKind.REQUIRES, EdgeKind.DERIVED_FROM),
    "summary": (EdgeKind.PART_OF, EdgeKind.IS_A),
    "default": (EdgeKind.SEMANTIC,),
}


def classify_intent(query: str) -> str:
    """Classificador heurístico simples — palavras-chave em pt/en.

    Em produção (Fase 2+), este classificador será substituído por chamada
    ao tier FAST (gpt-5.4-nano) via ``llm.tier_for_task("query.classify_intent")``.
    """
    q = query.lower()
    if any(w in q for w in ["por que", "porque", "why", "razão"]):
        return "why"
    if any(w in q for w in ["quando", "when", "data"]):
        return "when"
    if any(w in q for w in ["quem", "who"]):
        return "who"
    if any(w in q for w in ["como", "how", "passo"]):
        return "how"
    if any(w in q for w in ["o que é", "what is", "definição"]):
        return "what"
    if any(w in q for w in ["resumo", "summary", "panorama"]):
        return "summary"
    return "default"


# ────────────────────────────────────────────────────────────────────────────
# Matcher
# ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class HybridMatcher:
    """Retrieval híbrido sobre ``CognitiveGraph``.

    Configurável via pesos da combinação final:

        score = α · semantic + β · graph + γ · plasticity − δ · hop_distance

    Defaults baseados em ablações reportadas em MAGMA (α=0.5, β=0.2, γ=0.3) e
    ajustados para incluir penalidade explícita por distância de hop (cf.
    KuzuDB benchmarks, 2025).
    """

    alpha_semantic: float = 0.45
    beta_graph: float = 0.20
    gamma_plasticity: float = 0.30
    delta_hop_penalty: float = 0.05

    top_k_entry: int = 5
    """Quantos entry nodes pegar via vector search."""

    max_hops: int = 2
    """Profundidade máxima de expansão a partir dos entry nodes."""

    max_results: int = 25
    """Tamanho máximo do conjunto retornado."""

    min_semantic_similarity: float = 0.30
    """Threshold para entry nodes (descarta lixo)."""

    # ── API principal ───────────────────────────────────────────────────

    def retrieve(
        self,
        graph: CognitiveGraph,
        *,
        query: str | None = None,
        query_embedding: NDArray[np.float32] | None = None,
        intent: str | None = None,
        node_kinds: Iterable[str] | None = None,
    ) -> list[MatchResult]:
        """Executa retrieval híbrido completo.

        Args:
            graph:           grafo a consultar.
            query:           texto da query (opcional — necessário se sem embedding).
            query_embedding: embedding pré-computado (preferido em produção).
            intent:          classe de intenção; se ``None``, inferido de ``query``.
            node_kinds:      filtra resultados por tipo de nó (memory/synapse/...).

        Returns:
            Lista ordenada por ``score`` decrescente, limitada a ``max_results``.
        """
        # 1) Classifica intenção e seleciona tipos de aresta
        effective_intent = intent or (
            classify_intent(query) if query else "default"
        )
        edge_kinds = INTENT_TO_EDGES.get(effective_intent, INTENT_TO_EDGES["default"])

        # 2) Vector search — entry nodes
        entries = self._find_entry_nodes(graph, query_embedding)

        # 3) Graph expansion — coleta candidatos
        candidates = self._expand_from_entries(graph, entries, edge_kinds)

        # 4) Filtro por tipo (se requerido)
        if node_kinds is not None:
            allowed = {str(k) for k in node_kinds}
            candidates = {
                nid: cand
                for nid, cand in candidates.items()
                if cand["node"].kind.value in allowed
            }

        # 5) Score final + sort
        results = [self._score(graph, **cand) for cand in candidates.values()]
        results.sort(key=lambda r: r.score, reverse=True)
        return results[: self.max_results]

    # ── Estágios internos ───────────────────────────────────────────────

    def _find_entry_nodes(
        self,
        graph: CognitiveGraph,
        query_embedding: NDArray[np.float32] | None,
    ) -> list[tuple[GraphNode, float]]:
        """Top-K nós por similaridade de cosseno com ``query_embedding``.

        Quando ``query_embedding`` é ``None``, retorna nós com maior peso
        efetivo (fallback puramente sináptico — útil em runs iniciais sem
        embeddings configurados).
        """
        if query_embedding is None:
            ranked = [
                (node, graph.plasticity.effective_weight(node))
                for node in graph.iter_nodes()
                if node.is_active
            ]
            ranked.sort(key=lambda t: t[1], reverse=True)
            return ranked[: self.top_k_entry]

        q = _normalize(query_embedding)
        scored: list[tuple[GraphNode, float]] = []
        for node in graph.iter_nodes():
            if node.embedding is None or not node.is_active:
                continue
            sim = float(np.dot(q, _normalize(node.embedding)))
            if sim >= self.min_semantic_similarity:
                scored.append((node, sim))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[: self.top_k_entry]

    def _expand_from_entries(
        self,
        graph: CognitiveGraph,
        entries: list[tuple[GraphNode, float]],
        edge_kinds: tuple[EdgeKind, ...],
    ) -> dict[str, dict]:
        """BFS limitada a ``max_hops`` seguindo apenas ``edge_kinds``.

        Retorna dict por node_id com metadados acumulados (hop_distance, path,
        semantic_score do entry mais próximo).
        """
        candidates: dict[str, dict] = {}
        for entry, sim in entries:
            self._bfs_from(
                graph,
                entry,
                edge_kinds,
                entry_sim=sim,
                candidates=candidates,
            )
        return candidates

    def _bfs_from(
        self,
        graph: CognitiveGraph,
        entry: GraphNode,
        edge_kinds: tuple[EdgeKind, ...],
        *,
        entry_sim: float,
        candidates: dict[str, dict],
    ) -> None:
        """BFS típica, ponderada por edge weights, com limite de hops."""
        visited: dict[str, int] = {entry.id: 0}
        queue: list[tuple[str, int, list[str]]] = [(entry.id, 0, [])]

        # Sempre inclui o próprio entry
        self._upsert_candidate(
            candidates, entry, hop=0, path=[], semantic=entry_sim
        )

        while queue:
            node_id, hop, path = queue.pop(0)
            if hop >= self.max_hops:
                continue
            for edge in graph.iter_edges_from(node_id, kinds=edge_kinds):
                if not edge.is_active:
                    continue
                nxt = edge.target_id
                if nxt in visited and visited[nxt] <= hop + 1:
                    continue
                visited[nxt] = hop + 1
                next_path = [*path, edge.id]
                neighbor = graph.get_node(nxt)
                if neighbor is None or not neighbor.is_active:
                    continue
                # Sim do entry decai com distância
                propagated_sim = entry_sim * (0.7 ** (hop + 1))
                self._upsert_candidate(
                    candidates,
                    neighbor,
                    hop=hop + 1,
                    path=next_path,
                    semantic=propagated_sim,
                )
                queue.append((nxt, hop + 1, next_path))

    def _upsert_candidate(
        self,
        candidates: dict[str, dict],
        node: GraphNode,
        *,
        hop: int,
        path: list[str],
        semantic: float,
    ) -> None:
        """Mantém o melhor representante (menor hop, maior semantic) por id."""
        existing = candidates.get(node.id)
        if existing is None or hop < existing["hop"]:
            candidates[node.id] = {
                "node": node,
                "hop": hop,
                "path": path,
                "semantic": semantic,
            }
        elif hop == existing["hop"] and semantic > existing["semantic"]:
            existing["semantic"] = semantic
            existing["path"] = path

    def _score(
        self,
        graph: CognitiveGraph,
        *,
        node: GraphNode,
        hop: int,
        path: list[str],
        semantic: float,
    ) -> MatchResult:
        """Combina os 3 componentes em score final ∈ ℝ (não-normalizado)."""
        plasticity = graph.plasticity.effective_weight(node)
        # graph_score: degrau-suave por proximidade na vizinhança
        graph_score = 1.0 / (1.0 + hop)
        score = (
            self.alpha_semantic * semantic
            + self.beta_graph * graph_score
            + self.gamma_plasticity * plasticity
            - self.delta_hop_penalty * hop
        )
        return MatchResult(
            node=node,
            score=float(score),
            semantic_score=float(semantic),
            graph_score=float(graph_score),
            plasticity_score=float(plasticity),
            hop_distance=hop,
            path=path,
        )


def _normalize(v: NDArray[np.float32]) -> NDArray[np.float32]:
    """L2-normaliza um vetor (cosine similarity = dot product após normalização)."""
    norm = float(np.linalg.norm(v))
    if norm == 0:
        return v
    return (v / norm).astype(np.float32)
