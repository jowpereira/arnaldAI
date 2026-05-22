"""Bridge entre MemoryStore e o grafo cognitivo — ingestão e materialização."""

from __future__ import annotations

import hashlib
import json

from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
    MemoryNode,
    SynapseNode,
)
from arnaldo.graph.edge_ops import ensure_edge

from .models import MemoryRecord, MemorySynapseCandidate, association_signature
from .graph_bridge_utils import (
    build_label,
    domain_for_record,
    related_memories,
    source_for_payload,
    upsert_candidate,
)


def ingest_record_to_graph(
    graph: CognitiveGraph,
    candidates: dict[str, MemorySynapseCandidate],
    record: MemoryRecord,
    *,
    association_window: int,
    materialize_support_threshold: int,
    materialize_score_threshold: float,
) -> None:
    """Ingere um MemoryRecord no grafo cognitivo e atualiza candidatos."""
    node = to_memory_node(record)
    graph.add_node(node)
    related = related_memories(
        graph,
        node_id=node.id,
        payload=node.payload,
        association_window=association_window,
    )
    target_sig = association_signature(node.payload, fallback=node.id)
    for source_id, reward in related:
        source_node = graph.get_node(source_id)
        source_payload = (
            source_node.payload
            if isinstance(source_node, MemoryNode) and isinstance(source_node.payload, dict)
            else {}
        )
        source_sig = association_signature(source_payload, fallback=source_id)
        candidate = upsert_candidate(
            candidates,
            source_id=source_id,
            target_id=node.id,
            source_signature=source_sig,
            target_signature=target_sig,
            reward=reward,
        )
        ensure_memory_transition(graph, source_id=source_id, target_id=node.id, weight=reward)
        # Ligação semântica entre memórias com conteúdo similar
        ensure_semantic_link(graph, source_id=source_id, target_id=node.id, reward=reward)
        if candidate.is_materialized:
            refresh_materialized_synapse(graph, candidate)
    materialize_candidates(
        graph,
        candidates,
        support_threshold=materialize_support_threshold,
        score_threshold=materialize_score_threshold,
    )


def to_memory_node(record: MemoryRecord) -> MemoryNode:
    """Converte um MemoryRecord em MemoryNode."""
    record_id = str(record.id).strip()
    if not record_id:
        digest = hashlib.sha256(
            json.dumps(record.payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        record_id = f"memory_{digest}"
    payload = dict(record.payload or {})
    payload["record_kind"] = record.kind
    payload.setdefault("record_id", record_id)
    label = build_label(record.kind, payload)
    domain = domain_for_record(record.kind, payload)

    if record.kind == "episodic":
        run_id = str(payload.get("run_id") or payload.get("session_id") or "memory_run").strip()
        return MemoryNode.episodic(
            label=label,
            id=record_id,
            run_id=run_id,
            payload=payload,
            domain=domain,
        )

    source = source_for_payload(payload)
    if record.kind == "procedural":
        pattern = str(payload.get("pattern") or payload.get("action") or label).strip()
        return MemoryNode.procedural(
            label=label,
            id=record_id,
            pattern=pattern,
            payload=payload,
            source=source,
            domain=domain,
        )

    return MemoryNode.semantic(
        label=label,
        id=record_id,
        payload=payload,
        source=source,
        domain=domain,
    )


def materialize_candidates(
    graph: CognitiveGraph,
    candidates: dict[str, MemorySynapseCandidate],
    *,
    support_threshold: int,
    score_threshold: float,
) -> None:
    """Materializa candidatos elegíveis como SynapseNode no grafo."""
    from .models import memory_synapse_id

    for candidate in candidates.values():
        if candidate.support < support_threshold:
            continue
        if candidate.greedy_score < score_threshold:
            continue
        if candidate.is_materialized:
            refresh_materialized_synapse(graph, candidate)
            continue
        if not (
            graph.has_node(candidate.source_memory_id)
            and graph.has_node(candidate.target_memory_id)
        ):
            continue
        synapse_id = memory_synapse_id(candidate.key)
        synapse = SynapseNode.specialist(
            label=(
                "memory_association::%s->%s"
                % (
                    candidate.source_signature or candidate.source_memory_id,
                    candidate.target_signature or candidate.target_memory_id,
                )
            ),
            id=synapse_id,
            role="memory_associator",
            objective="ativar memória relacionada com base em coocorrência recorrente",
            epistemic_style="associative_retrieval",
            tier_preference="fast",
            action="memory_association",
            source_memory_id=candidate.source_memory_id,
            target_memory_id=candidate.target_memory_id,
            source_signature=candidate.source_signature or candidate.source_memory_id,
            target_signature=candidate.target_signature or candidate.target_memory_id,
            support=candidate.support,
            greedy_score=round(candidate.greedy_score, 6),
        )
        graph.add_node(synapse)
        ensure_edge(
            graph,
            source_id=candidate.source_memory_id,
            target_id=synapse_id,
            kind=EdgeKind.INFORMS,
            weight=min(0.95, 0.5 + (0.08 * candidate.support)),
        )
        ensure_edge(
            graph,
            source_id=synapse_id,
            target_id=candidate.target_memory_id,
            kind=EdgeKind.MENTIONS,
            weight=min(0.95, 0.5 + (0.3 * candidate.greedy_score)),
        )
        candidate.materialized_synapse_id = synapse_id


def refresh_materialized_synapse(
    graph: CognitiveGraph,
    candidate: MemorySynapseCandidate,
) -> None:
    """Atualiza payload de sinapse já materializada."""
    synapse_id = str(candidate.materialized_synapse_id or "").strip()
    if not synapse_id:
        return
    node = graph.get_node(synapse_id)
    if not isinstance(node, SynapseNode):
        candidate.materialized_synapse_id = None
        return
    updated = node.with_payload_merge(
        support=candidate.support,
        greedy_score=round(candidate.greedy_score, 6),
        source_memory_id=candidate.source_memory_id,
        target_memory_id=candidate.target_memory_id,
        source_signature=candidate.source_signature or candidate.source_memory_id,
        target_signature=candidate.target_signature or candidate.target_memory_id,
    )
    assert isinstance(updated, SynapseNode)
    graph.add_node(updated)
    ensure_edge(
        graph,
        source_id=candidate.source_memory_id,
        target_id=synapse_id,
        kind=EdgeKind.INFORMS,
        weight=min(0.95, 0.5 + (0.08 * candidate.support)),
    )
    ensure_edge(
        graph,
        source_id=synapse_id,
        target_id=candidate.target_memory_id,
        kind=EdgeKind.MENTIONS,
        weight=min(0.95, 0.5 + (0.3 * candidate.greedy_score)),
    )


def ensure_memory_transition(
    graph: CognitiveGraph,
    *,
    source_id: str,
    target_id: str,
    weight: float,
) -> None:
    ensure_edge(
        graph,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.TEMPORAL_BEFORE,
        weight=min(0.95, 0.35 + (0.45 * max(0.0, min(1.0, weight)))),
    )


def ensure_semantic_link(
    graph: CognitiveGraph,
    *,
    source_id: str,
    target_id: str,
    reward: float,
) -> None:
    """Cria aresta SEMANTIC entre memórias com conteúdo similar.

    Só cria se reward (que incorpora Jaccard overlap) indica
    similaridade real de conteúdo, não apenas co-temporalidade.
    """
    if reward < 0.3:
        return
    semantic_weight = min(0.90, 0.25 + (0.5 * reward))
    ensure_edge(
        graph,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SEMANTIC,
        weight=semantic_weight,
    )
