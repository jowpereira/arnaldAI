"""Consolidação episodic → semantic — agrupa memórias episódicas similares."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from arnaldo.graph.edge_ops import ensure_edge
from arnaldo.graph.edges import EdgeKind
from arnaldo.graph.node_types import MemoryNode
from arnaldo.graph.nodes import NodeKind
from arnaldo.graph.provenance import SourceKind, SourceRecord
from arnaldo.memory.models import jaccard, tokenize_payload

if TYPE_CHECKING:
    from arnaldo.graph.store import CognitiveGraph

logger = logging.getLogger("arnaldo.memory")


@dataclass(frozen=True, slots=True)
class ConsolidationResult:
    """Resultado de uma rodada de consolidação."""

    created_semantic_ids: tuple[str, ...]
    source_episodic_ids: tuple[str, ...]
    edges_created: int


def _find_clusters(
    nodes: list[MemoryNode],
    tokens_map: dict[str, set[str]],
    similarity_threshold: float,
) -> list[list[MemoryNode]]:
    """Clustering simples por similaridade jaccard."""
    visited: set[str] = set()
    clusters: list[list[MemoryNode]] = []

    for node in nodes:
        if node.id in visited:
            continue
        cluster = [node]
        visited.add(node.id)
        for other in nodes:
            if other.id in visited:
                continue
            sim = jaccard(tokens_map[node.id], tokens_map[other.id])
            if sim >= similarity_threshold:
                cluster.append(other)
                visited.add(other.id)
        clusters.append(cluster)

    return clusters


def _most_common_action(nodes: list[MemoryNode]) -> str:
    """Extrai a ação mais comum dos payloads episódicos."""
    counts: dict[str, int] = {}
    for n in nodes:
        action = str(n.payload.get("action", "unknown"))
        counts[action] = counts.get(action, 0) + 1
    if not counts:
        return "unknown"
    return max(counts, key=lambda k: counts[k])


def consolidate_episodic_memories(
    graph: CognitiveGraph,
    *,
    min_cluster_size: int = 3,
    similarity_threshold: float = 0.5,
    max_consolidations: int = 5,
) -> ConsolidationResult:
    """Agrupa episódicos similares e cria nós semânticos derivados."""
    episodics = [
        n
        for n in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=True)
        if n.payload.get("memory_type") == "episodic"
    ]

    if not episodics:
        return ConsolidationResult((), (), 0)

    tokens_map = {n.id: tokenize_payload(n.payload) for n in episodics}
    clusters = _find_clusters(episodics, tokens_map, similarity_threshold)

    created_ids: list[str] = []
    source_ids: list[str] = []
    edges_count = 0

    for cluster in clusters:
        if len(cluster) < min_cluster_size:
            continue
        if len(created_ids) >= max_consolidations:
            break

        action = _most_common_action(cluster)
        cluster_ids = [n.id for n in cluster]
        label = f"consolidated::{action}×{len(cluster)}"

        source = SourceRecord(
            kind=SourceKind.INFERENCE,
            identifier="memory.consolidation",
            confidence=0.70,
        )
        sem_node = MemoryNode.semantic(
            label=label,
            source=source,
            payload={
                "consolidated_from": cluster_ids,
                "pattern": action,
                "observation_count": len(cluster),
                "memory_type": "semantic",
            },
            domain="semantic_stable",
        )
        graph.add_node(sem_node)
        created_ids.append(sem_node.id)
        source_ids.extend(cluster_ids)

        for ep_id in cluster_ids:
            ensure_edge(
                graph,
                source_id=ep_id,
                target_id=sem_node.id,
                kind=EdgeKind.DERIVED_FROM,
                weight=0.6,
            )
            edges_count += 1

    return ConsolidationResult(
        created_semantic_ids=tuple(created_ids),
        source_episodic_ids=tuple(source_ids),
        edges_created=edges_count,
    )
