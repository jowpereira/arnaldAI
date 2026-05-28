"""Testes do módulo de routing — seleção dinâmica de synapses."""

from __future__ import annotations

import uuid

from arnaldo.graph.edges import EdgeKind, GraphEdge
from arnaldo.graph.execution.routing import (
    dijkstra_weighted_path,
    find_best_execution_path,
    select_synapses_for_request,
)
from arnaldo.graph.matching import MatchResult
from arnaldo.graph.nodes import NodeKind, SynapseNode
from arnaldo.graph.provenance import SourceKind, SourceRecord
from arnaldo.graph.store import CognitiveGraph


def _source() -> SourceRecord:
    return SourceRecord(kind=SourceKind.SYSTEM_ARTIFACT, identifier="test")


def _edge(src: str, tgt: str, weight: float = 0.5) -> GraphEdge:
    return GraphEdge(
        id=f"e-{uuid.uuid4().hex[:8]}",
        source_id=src,
        target_id=tgt,
        kind=EdgeKind.ACTIVATES,
        weight=weight,
    )


def _make_synapse(graph: CognitiveGraph, sid: str, weight: float = 0.5) -> SynapseNode:
    node = SynapseNode(
        id=sid,
        kind=NodeKind.SYNAPSE,
        label=f"Synapse {sid}",
        source=_source(),
        weight=weight,
    )
    graph.add_node(node)
    return node


class TestDijkstraWeightedPath:
    """Testa Dijkstra com pesos invertidos."""

    def test_same_node(self):
        g = CognitiveGraph()
        _make_synapse(g, "a")
        assert dijkstra_weighted_path(g, "a", "a") == ["a"]

    def test_direct_connection(self):
        g = CognitiveGraph()
        _make_synapse(g, "a")
        _make_synapse(g, "b")
        g.add_edge(_edge("a", "b", 0.8))
        path = dijkstra_weighted_path(g, "a", "b")
        assert path == ["a", "b"]

    def test_multi_hop_path(self):
        g = CognitiveGraph()
        _make_synapse(g, "a")
        _make_synapse(g, "b")
        _make_synapse(g, "c")
        g.add_edge(_edge("a", "b", 0.9))
        g.add_edge(_edge("b", "c", 0.8))
        path = dijkstra_weighted_path(g, "a", "c")
        assert path == ["a", "b", "c"]

    def test_prefers_strong_edges(self):
        g = CognitiveGraph()
        _make_synapse(g, "a")
        _make_synapse(g, "b")
        _make_synapse(g, "c")
        # Caminho direto a→c com peso fraco
        g.add_edge(_edge("a", "c", 0.1))
        # Caminho a→b→c com pesos fortes
        g.add_edge(_edge("a", "b", 0.9))
        g.add_edge(_edge("b", "c", 0.9))
        path = dijkstra_weighted_path(g, "a", "c")
        # Indireto via b é mais barato: 1/0.9 + 1/0.9 ≈ 2.2 vs 1/0.1 = 10
        assert path == ["a", "b", "c"]

    def test_unreachable_returns_none(self):
        g = CognitiveGraph()
        _make_synapse(g, "a")
        _make_synapse(g, "b")
        # Sem edge entre eles
        assert dijkstra_weighted_path(g, "a", "b") is None

    def test_max_cost_limits_search(self):
        g = CognitiveGraph()
        _make_synapse(g, "a")
        _make_synapse(g, "b")
        g.add_edge(_edge("a", "b", 0.01))  # custo = 100
        # max_cost=5 impede caminho caro
        assert dijkstra_weighted_path(g, "a", "b", max_cost=5.0) is None


class TestSelectSynapsesForRequest:
    """Testa seleção dinâmica via matcher."""

    def test_returns_list(self):
        g = CognitiveGraph()
        _make_synapse(g, "s1", weight=0.8)
        result = select_synapses_for_request(g, "como faço X?")
        # Sem embeddings, pode retornar com TF-IDF ou vazio
        assert isinstance(result, list)

    def test_respects_max_synapses(self):
        g = CognitiveGraph()
        for i in range(10):
            _make_synapse(g, f"s{i}", weight=0.8)
        result = select_synapses_for_request(g, "query", max_synapses=3)
        assert len(result) <= 3


class TestFindBestExecutionPath:
    """Testa construção de path a partir de candidatos."""

    def test_empty_candidates(self):
        assert find_best_execution_path(CognitiveGraph(), []) == []

    def test_single_candidate(self):
        g = CognitiveGraph()
        node = _make_synapse(g, "s1")
        candidates = [MatchResult(node=node, score=0.9)]
        path = find_best_execution_path(g, candidates)
        assert path == ["s1"]

    def test_connected_candidates_uses_path(self):
        g = CognitiveGraph()
        n1 = _make_synapse(g, "s1")
        n2 = _make_synapse(g, "s2")
        g.add_edge(_edge("s1", "s2", 0.9))
        candidates = [
            MatchResult(node=n1, score=0.9),
            MatchResult(node=n2, score=0.7),
        ]
        path = find_best_execution_path(g, candidates)
        assert "s1" in path
        assert "s2" in path

    def test_disconnected_candidates_adds_both(self):
        g = CognitiveGraph()
        n1 = _make_synapse(g, "s1")
        n2 = _make_synapse(g, "s2")
        candidates = [
            MatchResult(node=n1, score=0.9),
            MatchResult(node=n2, score=0.7),
        ]
        path = find_best_execution_path(g, candidates)
        assert path == ["s1", "s2"]
