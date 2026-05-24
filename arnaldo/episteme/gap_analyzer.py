"""Análise epistêmica — detecta gaps de cobertura no grafo."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from arnaldo.graph.store import CognitiveGraph
from arnaldo.graph.nodes import NodeKind, NodeStatus

from arnaldo.memory.models import jaccard, tokenize_payload

from .signals import CuriositySignal, GapType

logger = logging.getLogger("arnaldo.episteme")

_MAX_CONTRADICTION_SCAN = 100


@dataclass(frozen=True, slots=True)
class DomainCoverage:
    """Cobertura de um domínio no grafo cognitivo."""

    domain: str
    node_count: int
    active_count: int
    avg_weight: float
    stale_count: int


class EpistemicGapAnalyzer:
    """Analisa cobertura de domínios e gera sinais de curiosidade."""

    def __init__(self, min_coverage: int = 3, min_avg_weight: float = 0.3) -> None:
        self.min_coverage = min_coverage
        self.min_avg_weight = min_avg_weight

    def analyze_domain_coverage(self, graph: CognitiveGraph) -> list[DomainCoverage]:
        """Retorna cobertura por domínio — nós ativos, stale, peso médio."""
        domains: dict[str, list[float]] = {}
        stale_counts: dict[str, int] = {}
        active_counts: dict[str, int] = {}

        for node in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False):
            d = str(node.domain or "unknown")
            domains.setdefault(d, []).append(node.weight)
            is_stale = node.status in (NodeStatus.STALE, NodeStatus.ARCHIVED)
            stale_counts[d] = stale_counts.get(d, 0) + (1 if is_stale else 0)
            active_counts[d] = active_counts.get(d, 0) + (0 if is_stale else 1)

        return [
            DomainCoverage(
                domain=d,
                node_count=len(weights),
                active_count=active_counts.get(d, 0),
                avg_weight=sum(weights) / len(weights) if weights else 0.0,
                stale_count=stale_counts.get(d, 0),
            )
            for d, weights in domains.items()
        ]

    # ── Detecção de domínios stale ───────────────────────────────────

    def detect_stale_domains(self, graph: CognitiveGraph) -> list[CuriositySignal]:
        """Emite sinais para domínios com >50% nós stale/archived."""
        signals: list[CuriositySignal] = []
        for cov in self.analyze_domain_coverage(graph):
            if cov.node_count < 3:
                continue
            stale_ratio = cov.stale_count / cov.node_count
            if stale_ratio > 0.5:
                signals.append(
                    CuriositySignal(
                        query=f"refresh domain '{cov.domain}'",
                        gap_type=GapType.DECAYED,
                        confidence=0.0,
                        domain=cov.domain,
                        priority=0.5,
                        search_hints=(cov.domain,),
                    )
                )
        return signals

    # ── Detecção de contradições ─────────────────────────────────────

    def detect_contradictions(self, graph: CognitiveGraph) -> list[CuriositySignal]:
        """Detecta pares de nós similares com confiança divergente."""
        signals: list[CuriositySignal] = []

        # Agrupar nós MEMORY ativos por domínio, limitando scan
        by_domain: dict[str, list[tuple[str, set[str], float]]] = {}
        count = 0
        for node in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=True):
            if count >= _MAX_CONTRADICTION_SCAN:
                break
            d = str(node.domain or "unknown")
            tokens = tokenize_payload(node.payload)
            by_domain.setdefault(d, []).append((node.id, tokens, node.source.confidence))
            count += 1

        seen_pairs: set[tuple[str, str]] = set()
        for domain, nodes in by_domain.items():
            for i, (id_a, tok_a, conf_a) in enumerate(nodes):
                for id_b, tok_b, conf_b in nodes[i + 1 :]:
                    pair = (min(id_a, id_b), max(id_a, id_b))
                    if pair in seen_pairs:
                        continue
                    sim = jaccard(tok_a, tok_b)
                    if sim > 0.5 and abs(conf_a - conf_b) > 0.3:
                        seen_pairs.add(pair)
                        signals.append(
                            CuriositySignal(
                                query=f"contradiction in '{domain}' between {id_a} and {id_b}",
                                gap_type=GapType.GENUINE,
                                confidence=0.0,
                                domain=domain,
                                priority=0.7,
                                related_nodes=(id_a, id_b),
                            )
                        )
        return signals

    # ── Gap principal ────────────────────────────────────────────────

    def find_gaps(
        self, graph: CognitiveGraph, query: str, gap_type: GapType
    ) -> list[CuriositySignal]:
        """Gera sinais de curiosidade — gaps + stale domains + contradições."""
        signals: list[CuriositySignal] = []

        if gap_type != GapType.NONE:
            priority_map = {
                GapType.GENUINE: 0.8,
                GapType.DECAYED: 0.5,
                GapType.RETRIEVAL_MISS: 0.2,
            }
            signals.append(
                CuriositySignal(
                    query=query,
                    gap_type=gap_type,
                    confidence=0.0,
                    priority=priority_map.get(gap_type, 0.5),
                    source_request=query,
                )
            )

        signals.extend(self.detect_stale_domains(graph))
        signals.extend(self.detect_contradictions(graph))
        return signals
