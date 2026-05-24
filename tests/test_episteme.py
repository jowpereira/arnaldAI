"""Tests for epistemic module — gaps, curiosity, forager, ingester."""

from __future__ import annotations

from arnaldo.episteme.signals import CuriositySignal, GapType, SignalStatus
from arnaldo.episteme.gap_analyzer import EpistemicGapAnalyzer
from arnaldo.episteme.curiosity import CuriosityEngine
from arnaldo.graph import CognitiveGraph
from arnaldo.graph.provenance import SourceRecord


_BOOT = SourceRecord.from_bootstrap("test")


# ── GapType ──────────────────────────────────────────────────────────


class TestGapType:
    def test_enum_values(self) -> None:
        assert GapType.NONE == "none"
        assert GapType.GENUINE == "genuine"
        assert GapType.DECAYED == "decayed"
        assert GapType.RETRIEVAL_MISS == "retrieval_miss"


# ── SignalStatus ─────────────────────────────────────────────────────


class TestSignalStatus:
    def test_enum_values(self) -> None:
        assert SignalStatus.PENDING == "pending"
        assert SignalStatus.FORAGING == "foraging"
        assert SignalStatus.RESOLVED == "resolved"
        assert SignalStatus.SKIPPED == "skipped"


# ── CuriositySignal ──────────────────────────────────────────────────


class TestCuriositySignal:
    def test_creation_defaults(self) -> None:
        signal = CuriositySignal(query="test query", gap_type=GapType.GENUINE, confidence=0.0)
        assert signal.query == "test query"
        assert signal.gap_type == GapType.GENUINE
        assert signal.domain == "unknown"
        assert signal.priority == 0.5

    def test_frozen(self) -> None:
        signal = CuriositySignal(query="q", gap_type=GapType.NONE, confidence=0.5)
        try:
            signal.query = "new"  # type: ignore[misc]
            assert False, "Should be frozen"
        except AttributeError:
            pass

    def test_new_fields_defaults(self) -> None:
        signal = CuriositySignal(query="q", gap_type=GapType.GENUINE, confidence=0.0)
        assert signal.search_hints == ()
        assert signal.related_nodes == ()
        assert signal.status == SignalStatus.PENDING

    def test_signal_id_deterministic(self) -> None:
        s1 = CuriositySignal(query="test", gap_type=GapType.GENUINE, confidence=0.0)
        s2 = CuriositySignal(query="test", gap_type=GapType.GENUINE, confidence=0.5)
        assert s1.signal_id == s2.signal_id

    def test_signal_id_different_for_different_input(self) -> None:
        s1 = CuriositySignal(query="a", gap_type=GapType.GENUINE, confidence=0.0)
        s2 = CuriositySignal(query="b", gap_type=GapType.GENUINE, confidence=0.0)
        assert s1.signal_id != s2.signal_id


# ── EpistemicGapAnalyzer ─────────────────────────────────────────────


class TestEpistemicGapAnalyzer:
    def test_find_gaps_none_returns_empty(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        signals = analyzer.find_gaps(graph, "test", GapType.NONE)
        assert signals == []

    def test_find_gaps_genuine_returns_signal(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        signals = analyzer.find_gaps(graph, "test", GapType.GENUINE)
        assert len(signals) == 1
        assert signals[0].gap_type == GapType.GENUINE
        assert signals[0].priority == 0.8

    def test_find_gaps_decayed_returns_signal(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        signals = analyzer.find_gaps(graph, "test", GapType.DECAYED)
        assert len(signals) == 1
        assert signals[0].priority == 0.5

    def test_find_gaps_retrieval_miss_returns_signal(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        signals = analyzer.find_gaps(graph, "q", GapType.RETRIEVAL_MISS)
        assert len(signals) == 1
        assert signals[0].priority == 0.2

    def test_analyze_domain_coverage_with_nodes(self) -> None:
        from arnaldo.graph.nodes import MemoryNode

        graph = CognitiveGraph()
        for i in range(3):
            node = MemoryNode.semantic(
                label=f"test::{i}",
                id=f"mem-{i}",
                payload={},
                source=_BOOT,
                domain="tech",
            )
            graph.add_node(node)
        analyzer = EpistemicGapAnalyzer()
        coverage = analyzer.analyze_domain_coverage(graph)
        tech = [c for c in coverage if c.domain == "tech"]
        assert len(tech) == 1
        assert tech[0].node_count == 3
        assert tech[0].active_count == 3
        assert tech[0].stale_count == 0

    def test_analyze_domain_coverage_empty_graph(self) -> None:
        analyzer = EpistemicGapAnalyzer()
        graph = CognitiveGraph()
        coverage = analyzer.analyze_domain_coverage(graph)
        assert coverage == []


# ── CuriosityEngine ─────────────────────────────────────────────────


class TestCuriosityEngine:
    def test_prioritize_filters_below_min(self) -> None:
        engine = CuriosityEngine(min_priority=0.4)
        signals = [
            CuriositySignal(
                query="low",
                gap_type=GapType.RETRIEVAL_MISS,
                confidence=0.0,
                priority=0.2,
            ),
            CuriositySignal(
                query="high",
                gap_type=GapType.GENUINE,
                confidence=0.0,
                priority=0.8,
            ),
        ]
        result = engine.prioritize(signals)
        assert len(result) == 1
        assert result[0].query == "high"

    def test_prioritize_sorts_descending(self) -> None:
        engine = CuriosityEngine(min_priority=0.1)
        signals = [
            CuriositySignal(
                query="a",
                gap_type=GapType.GENUINE,
                confidence=0.0,
                priority=0.3,
            ),
            CuriositySignal(
                query="b",
                gap_type=GapType.GENUINE,
                confidence=0.0,
                priority=0.9,
            ),
        ]
        result = engine.prioritize(signals)
        assert result[0].query == "b"

    def test_prioritize_limits_to_max(self) -> None:
        engine = CuriosityEngine(min_priority=0.0, max_signals_per_run=1)
        signals = [
            CuriositySignal(
                query="a",
                gap_type=GapType.GENUINE,
                confidence=0.0,
                priority=0.5,
            ),
            CuriositySignal(
                query="b",
                gap_type=GapType.GENUINE,
                confidence=0.0,
                priority=0.6,
            ),
        ]
        result = engine.prioritize(signals)
        assert len(result) == 1

    def test_should_forage_retrieval_miss_returns_false(self) -> None:
        engine = CuriosityEngine()
        signal = CuriositySignal(
            query="q",
            gap_type=GapType.RETRIEVAL_MISS,
            confidence=0.0,
            priority=0.5,
        )
        assert engine.should_forage(signal, has_web_search=True) is False

    def test_should_forage_genuine_with_web(self) -> None:
        engine = CuriosityEngine()
        signal = CuriositySignal(
            query="q",
            gap_type=GapType.GENUINE,
            confidence=0.0,
            priority=0.8,
        )
        assert engine.should_forage(signal, has_web_search=True) is True

    def test_should_forage_genuine_without_web(self) -> None:
        engine = CuriosityEngine()
        signal = CuriositySignal(
            query="q",
            gap_type=GapType.GENUINE,
            confidence=0.0,
            priority=0.8,
        )
        assert engine.should_forage(signal, has_web_search=False) is False

    def test_should_forage_decayed_high_priority_with_web(self) -> None:
        engine = CuriosityEngine()
        signal = CuriositySignal(
            query="q",
            gap_type=GapType.DECAYED,
            confidence=0.0,
            priority=0.5,
        )
        assert engine.should_forage(signal, has_web_search=True) is True

    def test_should_forage_decayed_low_priority(self) -> None:
        engine = CuriosityEngine()
        signal = CuriositySignal(
            query="q",
            gap_type=GapType.DECAYED,
            confidence=0.0,
            priority=0.3,
        )
        assert engine.should_forage(signal, has_web_search=True) is False

    def test_compute_priority_genuine_high_urgency(self) -> None:
        engine = CuriosityEngine()
        graph = CognitiveGraph()
        signal = CuriositySignal(
            query="q", gap_type=GapType.GENUINE, confidence=0.0, domain="new_domain"
        )
        priority = engine.compute_priority(signal, graph)
        # Grafo vazio → domain_relevance=1.0, urgency=1.0, staleness=0.0
        # 1.0*0.5 + 1.0*0.3 + 0.0*0.2 = 0.8
        assert priority == 0.8

    def test_compute_priority_with_stale_nodes(self) -> None:
        from arnaldo.graph.nodes import MemoryNode, NodeStatus

        engine = CuriosityEngine()
        graph = CognitiveGraph()
        # 3 nós no domínio "tech", 2 stale
        for i in range(3):
            node = MemoryNode.semantic(
                label=f"test::{i}",
                id=f"mem-stale-{i}",
                source=_BOOT,
                domain="tech",
            )
            if i < 2:
                node.status = NodeStatus.STALE
            graph.add_node(node)
        signal = CuriositySignal(query="q", gap_type=GapType.DECAYED, confidence=0.0, domain="tech")
        priority = engine.compute_priority(signal, graph)
        # domain_relevance = 1 - 3/3 = 0.0 (all nodes are in this domain)
        # urgency = 0.7, staleness = 2/3 ≈ 0.667
        # 0.0*0.5 + 0.7*0.3 + 0.667*0.2 ≈ 0.343
        assert priority > 0.3
        assert priority < 0.5

    def test_prioritize_with_graph_recomputes(self) -> None:
        engine = CuriosityEngine(min_priority=0.0)
        graph = CognitiveGraph()
        # Grafo vazio → todos os domínios são "novos" = alta relevância
        signals = [
            CuriositySignal(
                query="a",
                gap_type=GapType.GENUINE,
                confidence=0.0,
                priority=0.1,
                domain="new",
            ),
            CuriositySignal(
                query="b",
                gap_type=GapType.RETRIEVAL_MISS,
                confidence=0.0,
                priority=0.9,
                domain="new",
            ),
        ]
        result_no_graph = engine.prioritize(signals)
        result_with_graph = engine.prioritize(signals, graph=graph)
        # Com grafo, prioridades são recalculadas — a ordem pode mudar
        assert result_no_graph[0].query == "b"  # original: 0.9 > 0.1
        # Com grafo: GENUINE urgency=1.0 > RETRIEVAL_MISS urgency=0.3
        assert result_with_graph[0].query == "a"

    def test_prioritize_backward_compat(self) -> None:
        engine = CuriosityEngine(min_priority=0.0)
        signals = [
            CuriositySignal(
                query="x",
                gap_type=GapType.GENUINE,
                confidence=0.0,
                priority=0.5,
            ),
        ]
        # Sem graph = comportamento original
        result = engine.prioritize(signals)
        assert len(result) == 1
        assert result[0].priority == 0.5
