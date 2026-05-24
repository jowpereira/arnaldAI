"""graph_bridge_utils — utilitários de conversão para o graph bridge."""

from __future__ import annotations

from typing import Any

from arnaldo.graph import (
    CognitiveGraph,
    NodeKind,
    SourceRecord,
)

from .models import MemorySynapseCandidate, jaccard, tokenize_payload


def source_for_payload(payload: dict[str, Any]) -> SourceRecord:
    run_id = str(payload.get("run_id", "")).strip()
    session_id = str(payload.get("session_id", "")).strip()
    if run_id:
        agent_id = str(payload.get("agent_id", "")).strip()
        if agent_id:
            return SourceRecord.from_run(run_id, agent=agent_id)
        return SourceRecord.from_run(run_id)
    if session_id:
        return SourceRecord.from_user(session_id)
    return SourceRecord.from_bootstrap("memory.store")


def build_label(kind: str, payload: dict[str, Any]) -> str:
    for key in ("summary", "statement", "goal", "action", "step_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return f"{kind}::{value.strip()[:180]}"
    return f"{kind}::memory_record"


def domain_for_record(kind: str, payload: dict[str, Any]) -> str:
    if kind == "episodic":
        return "episodic"
    if kind == "procedural":
        return "procedural"
    if kind == "prospective":
        return "prospective"
    if kind == "negative":
        return "negative"
    base = str(payload.get("domain", "")).strip()
    return base or "semantic_stable"


def related_memories(
    graph: CognitiveGraph,
    *,
    node_id: str,
    payload: dict[str, Any],
    association_window: int,
) -> list[tuple[str, float]]:
    """Encontra memórias relacionadas por contexto compartilhado."""
    run_id = str(payload.get("run_id", "")).strip()
    session_id = str(payload.get("session_id", "")).strip()
    action = str(payload.get("action", "")).strip()
    capability_id = str(payload.get("capability_id", "")).strip()
    tokens = tokenize_payload(payload)
    scored: list[tuple[str, float, Any]] = []
    for node in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=True):
        if node.id == node_id:
            continue
        node_payload = node.payload if isinstance(node.payload, dict) else {}
        score = 0.0
        node_run_id = str(node_payload.get("run_id", "")).strip()
        node_session_id = str(node_payload.get("session_id", "")).strip()
        node_action = str(node_payload.get("action", "")).strip()
        node_capability = str(node_payload.get("capability_id", "")).strip()

        if run_id and node_run_id == run_id:
            score += 0.45
        if session_id and node_session_id == session_id:
            score += 0.35
        if action and node_action and action == node_action:
            score += 0.15
        if capability_id and node_capability and capability_id == node_capability:
            score += 0.15

        overlap = jaccard(tokens, tokenize_payload(node_payload))
        if overlap > 0.0:
            score += min(0.4, overlap)
        if score <= 0.0:
            continue
        scored.append((node.id, min(1.0, score), node.bitemp.recorded_at))

    scored.sort(key=lambda item: (item[1], item[2]), reverse=True)
    top = scored[:association_window]
    return [(source_id, reward) for source_id, reward, _ in top]


def upsert_candidate(
    candidates: dict[str, MemorySynapseCandidate],
    *,
    source_id: str,
    target_id: str,
    source_signature: str,
    target_signature: str,
    reward: float,
) -> MemorySynapseCandidate:
    """Cria ou atualiza um candidato a sinapse."""
    key = f"{source_signature}->{target_signature}"
    candidate = candidates.get(key)
    if candidate is None:
        candidate = MemorySynapseCandidate(
            source_memory_id=source_id,
            target_memory_id=target_id,
            source_signature=source_signature,
            target_signature=target_signature,
        )
        candidates[key] = candidate
    else:
        candidate.source_memory_id = source_id
        candidate.target_memory_id = target_id
        if source_signature:
            candidate.source_signature = source_signature
        if target_signature:
            candidate.target_signature = target_signature
    candidate.register_observation(reward=reward)
    return candidate
