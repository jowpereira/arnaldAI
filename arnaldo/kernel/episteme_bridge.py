"""Bridge entre kernel e camada epistêmica."""

from __future__ import annotations

import logging
from typing import Any

from arnaldo.episteme import (
    CuriosityEngine,
    EpistemicGapAnalyzer,
    KnowledgeIngester,
    WebForager,
)
from arnaldo.episteme.signals import CuriositySignal, GapType
from arnaldo.graph.store import CognitiveGraph
from arnaldo.graph.nodes import NodeKind

logger = logging.getLogger("arnaldo.kernel.episteme_bridge")


def maybe_forage(
    graph: CognitiveGraph,
    gap_type: GapType,
    request: str,
    confidence: float,
    *,
    has_web_search: bool = False,
    thinking: Any | None = None,
) -> list[str]:
    """Executa foraging epistêmico se gap detectado e web disponível."""
    if gap_type == GapType.NONE:
        return []

    analyzer = EpistemicGapAnalyzer()
    signals = analyzer.find_gaps(graph, request, gap_type)
    if not signals:
        signals = [
            CuriositySignal(
                query=request,
                gap_type=gap_type,
                confidence=confidence,
                priority=0.6,
                source_request=request,
            )
        ]

    engine = CuriosityEngine()
    prioritized = engine.prioritize(signals)
    if not prioritized:
        return []

    # Emite thinking events antes do loop de foraging
    if thinking is not None:
        for signal in prioritized:
            thinking.searching(signal.query, source="curiosity_engine")

    created: list[str] = []
    if has_web_search:
        forager = WebForager()
        ingester = KnowledgeIngester()
        for signal in prioritized:
            if not engine.should_forage(signal, has_web_search=True):
                continue
            results = forager.forage(signal)
            if results:
                ids = ingester.ingest_search_results(graph, results, query=signal.query)
                created.extend(ids)
                logger.info(
                    "Foraged %d nodes for '%s'",
                    len(ids),
                    signal.query[:60],
                )

    if created:
        from .episteme_hooks import resolve_prospective_memories

        resolve_prospective_memories(graph, request, gap_type)

    return created


def check_web_search_available(graph: CognitiveGraph) -> bool:
    """Verifica se capability de web search está ativa no grafo."""
    for node in graph.iter_nodes(kind=NodeKind.CAPABILITY, active_only=True):
        if (
            isinstance(node.payload, dict)
            and node.payload.get("capability_id") == "search.public_web"
        ):
            return True
    return False
