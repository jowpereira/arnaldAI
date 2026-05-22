"""Helpers do Graph Brain — funções auxiliares extraídas para manter brain.py ≤ 300 linhas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .edges import EdgeKind
from .matching import MatchResult
from .nodes import NodeKind

if TYPE_CHECKING:
    from .store import CognitiveGraph

_MIN_SYNAPSE_SCORE = 0.10
_MIN_CAPABILITY_SCORE = 0.20
_LLM_SYNAPSE_PREFIX = "syn-llm-"
_GAP_CONFIDENCE_THRESHOLD = 0.30
_GAP_MEMORY_SCORE_THRESHOLD = 0.20

TierLevel = Literal["fast", "expert", "god", "codex"]
ComplexityLevel = Literal["conversational", "intermediate", "complex"]


def apply_memory_modulation(
    graph: CognitiveGraph,
    synapses: list[MatchResult],
    memories: list[MatchResult],
) -> list[MatchResult]:
    """G3+G5: Memórias modulam scores de synapses — co-decisão, não só contexto."""
    if not memories or not synapses:
        return synapses

    scores: dict[str, float] = {s.node.id: s.score for s in synapses}
    syn_map: dict[str, MatchResult] = {s.node.id: s for s in synapses}

    for mem in memories:
        mem_type = mem.node.payload.get("memory_type", "")

        # G5: Memórias negativas/lesson inibem synapses relevantes
        if mem_type in ("negative", "lesson"):
            inhibition_targets = mem.node.payload.get("inhibits_synapses", [])
            for syn_id in inhibition_targets:
                if syn_id in scores:
                    scores[syn_id] *= max(0.1, 1.0 - mem.score * 0.5)

        # G3: INFORMS edges — memória contextualiza synapse (boost)
        for edge in graph.iter_edges_from(mem.node.id, kinds=[EdgeKind.INFORMS]):
            if not edge.is_active or edge.weight < 0.2:
                continue
            if edge.target_id in scores:
                boost = 1.0 + (edge.weight * mem.score * 0.3)
                scores[edge.target_id] *= boost

    adjusted = []
    for sid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        original = syn_map[sid]
        if abs(score - original.score) > 1e-9:
            adjusted.append(MatchResult(node=original.node, score=score))
        else:
            adjusted.append(original)
    return adjusted


def check_needs_external(graph: CognitiveGraph, cap_needs: list[str]) -> bool:
    """G1: Verifica se alguma capability requer rede — via campo explícito + fallback prefix."""
    for cap_id in cap_needs:
        # Prioridade: campo requires_network no nó
        for node in graph.iter_nodes(kind=NodeKind.CAPABILITY, active_only=True):
            if node.payload.get("capability_id") == cap_id:
                if node.payload.get("requires_network", False):
                    return True
                break
        # Fallback: heurística de prefixo para caps sem campo explícito
        if cap_id.startswith(("search.", "connector.")):
            return True
    return False


def detect_knowledge_gap(confidence: float, memories: list[MatchResult]) -> bool:
    """G17: Detecta se o brain não tem conhecimento suficiente."""
    if confidence >= _GAP_CONFIDENCE_THRESHOLD:
        return False
    if not memories:
        return True
    max_mem_score = max(m.score for m in memories)
    return max_mem_score < _GAP_MEMORY_SCORE_THRESHOLD


def discover_capabilities(
    graph: CognitiveGraph,
    synapses: list[MatchResult],
    direct_caps: list[MatchResult],
) -> list[str]:
    """Descobre capabilities via REQUIRES edges das synapses ativadas."""
    cap_ids: list[str] = []
    seen: set[str] = set()

    for cap in direct_caps:
        if cap.score >= _MIN_CAPABILITY_SCORE:
            cap_id = str(cap.node.payload.get("capability_id", ""))
            if cap_id and cap_id not in seen:
                cap_ids.append(cap_id)
                seen.add(cap_id)

    for syn in synapses:
        if syn.score < _MIN_SYNAPSE_SCORE:
            continue
        for edge in graph.iter_edges_from(syn.node.id, kinds=[EdgeKind.REQUIRES]):
            if not edge.is_active or edge.weight < 0.3:
                continue
            target = graph.get_node(edge.target_id)
            if target and target.kind == NodeKind.CAPABILITY:
                cap_id = str(target.payload.get("capability_id", ""))
                if cap_id and cap_id not in seen:
                    cap_ids.append(cap_id)
                    seen.add(cap_id)

    return cap_ids


def resolve_tier_from_graph(
    graph: CognitiveGraph,
    primary: MatchResult,
) -> TierLevel | None:
    """Resolve tier seguindo REQUIRES edges para syn-llm-* nodes."""
    for edge in graph.iter_edges_from(primary.node.id, kinds=[EdgeKind.REQUIRES]):
        if not edge.is_active or edge.weight < 0.3:
            continue
        target = graph.get_node(edge.target_id)
        if target and target.id.startswith(_LLM_SYNAPSE_PREFIX):
            tier_val = target.payload.get("tier_preference", "")
            if tier_val in ("fast", "expert", "god", "codex"):
                return tier_val  # type: ignore[return-value]
    return None


def derive_complexity(
    graph: CognitiveGraph,
    primary: MatchResult | None,
    synapses: list[MatchResult],
    cap_needs: list[str],
    request: str,
    confidence_threshold: float = 0.25,
) -> tuple[ComplexityLevel, bool, TierLevel]:
    """Deriva complexidade do padrão de ativação."""
    words = request.split()

    if primary is None or primary.score < confidence_threshold:
        if len(words) <= 4:
            return "conversational", True, "fast"
        return "intermediate", True, "fast"

    if cap_needs:
        return (
            "intermediate",
            True,
            primary.node.payload.get("tier_preference", "expert"),
        )

    depth = int(primary.node.payload.get("specialization_depth", 0))
    graph_tier = resolve_tier_from_graph(graph, primary)
    tier: TierLevel = graph_tier or primary.node.payload.get("tier_preference", "fast")
    if depth >= 2:
        return "complex", False, tier

    high_activation = [s for s in synapses if s.score > 0.4]
    if len(high_activation) >= 3:
        return "complex", False, "expert"

    if tier in ("god", "expert"):
        return "complex", False, tier

    return "intermediate", True, tier
