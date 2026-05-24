"""Graph Brain — o grafo decide, o LLM executa.

Spreading activation sobre o CognitiveGraph para selecionar
synapses, capabilities e tier de LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .brain_helpers import (
    _LLM_SYNAPSE_PREFIX,
    _MIN_SYNAPSE_SCORE,
    ComplexityLevel,
    TierLevel,
    apply_memory_modulation as _apply_memory_modulation,
    check_needs_external as _check_needs_external,
    derive_complexity as _derive_complexity,
    detect_knowledge_gap as _detect_knowledge_gap,
    discover_capabilities as _discover_capabilities,
)
from .edges import EdgeKind
from .matching import HybridMatcher, MatchResult
from .nodes import NodeKind

from arnaldo.episteme.signals import GapType

if TYPE_CHECKING:
    from .store import CognitiveGraph

logger = logging.getLogger("arnaldo.graph.brain")

BRAIN_CONFIDENCE_THRESHOLD = 0.25


@dataclass(slots=True, frozen=True)
class BrainDecision:
    """Decisão do grafo — o que fazer com este request."""

    primary_synapse: str | None
    """ID da synapse mais ativada (None = nenhuma relevante)."""

    tier: TierLevel
    """Tier de LLM sugerido pela synapse ativada."""

    complexity: ComplexityLevel
    """conversational | intermediate | complex — derivado da ativação."""

    skip_full_pipeline: bool

    needs_external_data: bool

    capability_needs: list[str] = field(default_factory=list)

    activated_synapses: list[MatchResult] = field(default_factory=list)

    activated_memories: list[MatchResult] = field(default_factory=list)

    confidence: float = 0.0

    knowledge_gap: bool = False
    """Se True, o brain detectou gap de conhecimento — considere busca externa."""

    gap_type: GapType = GapType.NONE
    """Tipo de gap detectado — NONE, GENUINE, DECAYED ou RETRIEVAL_MISS."""


def activate(
    graph: CognitiveGraph,
    request: str,
    *,
    max_synapses: int = 5,
    max_memories: int = 8,
) -> BrainDecision:
    """Spreading activation — G6: single scan, G3+G5: memory modulation.

    Phase 1: Single scan — all node kinds at once
    Phase 2: Agent filter + inhibition
    Phase 3: Memory recall via RECALLS edges + direct matches
    Phase 3b: Memory modulation (INFORMS boost + negative inhibition)
    Phase 4: Merge — decisão final
    """
    if graph.node_count == 0:
        return _fallback_decision()

    # G6: Single scan — all kinds at once
    matcher = HybridMatcher(
        top_k_entry=15,
        max_hops=2,
        max_results=max_synapses + max_memories + 10,
        min_semantic_similarity=0.05,
    )
    all_matches = matcher.retrieve(graph, query=request)

    # Split by layer
    raw_synapses: list[MatchResult] = []
    capabilities: list[MatchResult] = []
    direct_memories: list[MatchResult] = []
    for m in all_matches:
        if m.node.kind == NodeKind.SYNAPSE:
            raw_synapses.append(m)
        elif m.node.kind == NodeKind.CAPABILITY:
            capabilities.append(m)
        elif m.node.kind == NodeKind.MEMORY:
            direct_memories.append(m)

    # Phase 2: Filter agent layer (remove LLM synapses) + inhibition
    synapses = [s for s in raw_synapses if not s.node.id.startswith(_LLM_SYNAPSE_PREFIX)]
    synapses = _apply_inhibition(graph, synapses)

    # Phase 3: Memory recall — RECALLS edges + direct matches from scan
    memories = _recall_memories(graph, synapses, direct_memories, max_memories)

    # Phase 3b: Memory modulation — G3+G5
    synapses = _apply_memory_modulation(graph, synapses, memories)

    # Phase 4: Merge — decisão final
    cap_needs = _discover_capabilities(graph, synapses, capabilities)
    primary = synapses[0] if synapses and synapses[0].score >= _MIN_SYNAPSE_SCORE else None

    complexity, skip, tier = _derive_complexity(
        graph,
        primary,
        synapses,
        cap_needs,
        request,
        BRAIN_CONFIDENCE_THRESHOLD,
    )

    # G1: needs_external via requires_network, não string prefix
    needs_external = _check_needs_external(graph, cap_needs)

    # G17: Gap detection
    confidence = primary.score if primary else 0.0
    gap_type = _detect_knowledge_gap(confidence, memories, graph)
    has_gap = gap_type != GapType.NONE

    return BrainDecision(
        primary_synapse=primary.node.id if primary else None,
        tier=tier,
        complexity=complexity,
        skip_full_pipeline=skip,
        needs_external_data=needs_external or has_gap,
        capability_needs=cap_needs,
        activated_synapses=synapses[:max_synapses],
        activated_memories=memories[:max_memories],
        confidence=confidence,
        knowledge_gap=has_gap,
        gap_type=gap_type,
    )


def _apply_inhibition(
    graph: CognitiveGraph,
    synapses: list[MatchResult],
) -> list[MatchResult]:
    """Aplica inibição entre synapses — competição neural."""
    if len(synapses) <= 1:
        return synapses
    scores: dict[str, float] = {s.node.id: s.score for s in synapses}
    syn_map: dict[str, MatchResult] = {s.node.id: s for s in synapses}
    for syn in synapses:
        for edge in graph.iter_edges_from(syn.node.id, kinds=[EdgeKind.INHIBITS]):
            if not edge.is_active:
                continue
            if edge.target_id in scores:
                scores[edge.target_id] *= 1.0 - edge.weight
    adjusted = []
    for sid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        original = syn_map[sid]
        if abs(score - original.score) > 1e-9:
            adjusted.append(MatchResult(node=original.node, score=score))
        else:
            adjusted.append(original)
    return adjusted


def _recall_memories(
    graph: CognitiveGraph,
    synapses: list[MatchResult],
    direct_memories: list[MatchResult],
    max_memories: int,
) -> list[MatchResult]:
    """Phase 2: Memory recall via RECALLS edges + direct matches (G6)."""
    recalled: dict[str, MatchResult] = {}

    # 2a: Memórias via RECALLS edges das synapses ativadas
    for syn in synapses:
        if syn.score < _MIN_SYNAPSE_SCORE:
            continue
        for edge in graph.iter_edges_from(syn.node.id, kinds=[EdgeKind.RECALLS]):
            if not edge.is_active or edge.weight < 0.2:
                continue
            mem = graph.get_node(edge.target_id)
            if mem and mem.kind == NodeKind.MEMORY and mem.id not in recalled:
                propagated_score = syn.score * edge.weight
                recalled[mem.id] = MatchResult(node=mem, score=propagated_score)

    # 2b: Direct matches from single scan (G6)
    for m in direct_memories:
        if m.node.id not in recalled:
            recalled[m.node.id] = m
        else:
            existing = recalled[m.node.id]
            if m.score > existing.score:
                recalled[m.node.id] = m

    return sorted(recalled.values(), key=lambda m: m.score, reverse=True)[:max_memories]


def _fallback_decision() -> BrainDecision:
    return BrainDecision(
        primary_synapse=None,
        tier="fast",
        complexity="conversational",
        skip_full_pipeline=True,
        needs_external_data=False,
    )
