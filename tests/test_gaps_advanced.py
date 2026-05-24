"""Testes para detect_stale_domains, detect_contradictions e find_gaps expandido."""

from __future__ import annotations

from arnaldo.episteme.gap_analyzer import EpistemicGapAnalyzer
from arnaldo.episteme.signals import GapType
from arnaldo.graph import CognitiveGraph
from arnaldo.graph.nodes import MemoryNode, NodeStatus
from arnaldo.graph.provenance import SourceKind, SourceRecord

_BOOT = SourceRecord.from_bootstrap("test")


def _make_source(confidence: float) -> SourceRecord:
    return SourceRecord(kind=SourceKind.INFERENCE, identifier="test", confidence=confidence)


class TestDetectStaleDomains:
    def test_detect_stale_domains_finds_stale_heavy(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        # 4 nós no domínio "old_tech", 3 stale → 75% > 50%
        for i in range(4):
            node = MemoryNode.semantic(
                label=f"old::{i}",
                id=f"stale-{i}",
                source=_BOOT,
                domain="old_tech",
            )
            if i < 3:
                node.status = NodeStatus.STALE
            graph.add_node(node)
        signals = analyzer.detect_stale_domains(graph)
        assert len(signals) >= 1
        assert signals[0].gap_type == GapType.DECAYED
        assert signals[0].domain == "old_tech"

    def test_detect_stale_domains_ignores_healthy(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        for i in range(5):
            node = MemoryNode.semantic(
                label=f"fresh::{i}",
                id=f"fresh-{i}",
                source=_BOOT,
                domain="fresh_tech",
            )
            graph.add_node(node)
        signals = analyzer.detect_stale_domains(graph)
        stale_signals = [s for s in signals if s.domain == "fresh_tech"]
        assert stale_signals == []


class TestDetectContradictions:
    def test_detect_contradictions_finds_conflict(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        # 2 nós no mesmo domínio com payload similar mas confiança divergente
        n1 = MemoryNode.semantic(
            label="fact::python_fast",
            id="c1",
            source=_make_source(0.9),
            payload={"claim": "python is fast for data processing"},
            domain="perf",
        )
        n2 = MemoryNode.semantic(
            label="fact::python_slow",
            id="c2",
            source=_make_source(0.4),
            payload={"claim": "python is fast for data analysis"},
            domain="perf",
        )
        graph.add_node(n1)
        graph.add_node(n2)
        signals = analyzer.detect_contradictions(graph)
        assert len(signals) == 1
        assert signals[0].gap_type == GapType.GENUINE
        assert signals[0].priority == 0.7

    def test_detect_contradictions_ignores_consistent(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        n1 = MemoryNode.semantic(
            label="fact::a",
            id="cons1",
            source=_make_source(0.8),
            payload={"claim": "python is great for ML"},
            domain="ml",
        )
        n2 = MemoryNode.semantic(
            label="fact::b",
            id="cons2",
            source=_make_source(0.75),
            payload={"claim": "python is great for machine learning"},
            domain="ml",
        )
        graph.add_node(n1)
        graph.add_node(n2)
        signals = analyzer.detect_contradictions(graph)
        # |0.8 - 0.75| = 0.05 < 0.3 → sem contradição
        assert signals == []


class TestFindGapsExpanded:
    def test_find_gaps_includes_stale_and_contradictions(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        # Adicionar domínio stale
        for i in range(4):
            node = MemoryNode.semantic(
                label=f"stale::{i}",
                id=f"fg-stale-{i}",
                source=_BOOT,
                domain="dying_domain",
            )
            if i < 3:
                node.status = NodeStatus.STALE
            graph.add_node(node)
        # Adicionar contradição
        n1 = MemoryNode.semantic(
            label="fact::x",
            id="fg-c1",
            source=_make_source(0.95),
            payload={"topic": "alpha beta gamma"},
            domain="research",
        )
        n2 = MemoryNode.semantic(
            label="fact::y",
            id="fg-c2",
            source=_make_source(0.3),
            payload={"topic": "alpha beta gamma delta"},
            domain="research",
        )
        graph.add_node(n1)
        graph.add_node(n2)

        signals = analyzer.find_gaps(graph, "test", GapType.GENUINE)
        gap_types = {s.gap_type for s in signals}
        # Deve ter: GENUINE (do query), DECAYED (stale domain), GENUINE (contradição)
        assert GapType.GENUINE in gap_types
        assert GapType.DECAYED in gap_types
        assert len(signals) >= 3

    def test_find_gaps_none_still_detects_stale_and_contradictions(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        # Domínio stale
        for i in range(3):
            node = MemoryNode.semantic(
                label=f"old::{i}",
                id=f"fg2-s-{i}",
                source=_BOOT,
                domain="legacy",
            )
            node.status = NodeStatus.STALE
            graph.add_node(node)
        signals = analyzer.find_gaps(graph, "q", GapType.NONE)
        # GapType.NONE não adiciona signal do query, mas detecta stale
        assert any(s.gap_type == GapType.DECAYED for s in signals)
