"""Testes para os 20 gaps — parte 1: edges, intent, node_types, bootstrap, brain helpers."""

from __future__ import annotations

import pytest

from arnaldo.graph import CognitiveGraph, EdgeKind
from arnaldo.graph.brain import activate
from arnaldo.graph.brain_helpers import (
    apply_memory_modulation,
    check_needs_external,
    detect_knowledge_gap,
)
from arnaldo.graph.edges import GraphEdge
from arnaldo.graph.intent import INTENT_TO_EDGES, classify_intent
from arnaldo.episteme.signals import GapType
from arnaldo.graph.matching import MatchResult
from arnaldo.graph.node_types import CapabilityNode, MemoryNode, SynapseNode
from arnaldo.graph.provenance import SourceRecord
from arnaldo.kernel.bootstrap import bootstrap_graph

_BOOT = SourceRecord.from_bootstrap("test")


def _bootstrapped_graph() -> CognitiveGraph:
    g = CognitiveGraph()
    bootstrap_graph(g)
    return g


class TestG16ContradictsSupersedesEdges:
    def test_contradicts_exists(self) -> None:
        assert EdgeKind.CONTRADICTS.value == "contradicts"

    def test_supersedes_exists(self) -> None:
        assert EdgeKind.SUPERSEDES.value == "supersedes"

    def test_contradicts_is_memory_internal(self) -> None:
        assert EdgeKind.CONTRADICTS.is_memory_internal is True
        assert EdgeKind.CONTRADICTS.is_agent_internal is False

    def test_supersedes_is_memory_internal(self) -> None:
        assert EdgeKind.SUPERSEDES.is_memory_internal is True
        assert EdgeKind.SUPERSEDES.is_agent_internal is False

    def test_contradicts_default_weight(self) -> None:
        edge = GraphEdge.connect("a", "b", EdgeKind.CONTRADICTS)
        assert edge.weight == pytest.approx(0.80)

    def test_supersedes_default_weight(self) -> None:
        edge = GraphEdge.connect("a", "b", EdgeKind.SUPERSEDES)
        assert edge.weight == pytest.approx(0.90)

    def test_contradicts_edge_in_graph(self) -> None:
        g = CognitiveGraph()
        m1 = MemoryNode.semantic(label="fact::A", id="m1", source=_BOOT)
        m2 = MemoryNode.semantic(label="fact::B", id="m2", source=_BOOT)
        g.add_node(m1)
        g.add_node(m2)
        e = GraphEdge.connect("m1", "m2", EdgeKind.CONTRADICTS)
        g.add_edge(e)
        edges = list(g.iter_edges_from("m1", kinds=[EdgeKind.CONTRADICTS]))
        assert len(edges) == 1
        assert edges[0].target_id == "m2"



class TestG19IncludesNotMemoryInternal:
    def test_includes_not_memory_internal(self) -> None:
        assert EdgeKind.INCLUDES.is_memory_internal is False

    def test_includes_is_compositional(self) -> None:
        assert EdgeKind.INCLUDES.is_compositional is True



class TestG11IntentWordBoundaries:
    def test_dataset_no_longer_matches_when(self) -> None:
        """'dataset' contém 'data' — não deve classificar como 'when'."""
        assert classify_intent("analise o dataset completo") == "default"

    def test_quando_still_matches_when(self) -> None:
        assert classify_intent("quando foi a última reunião?") == "when"

    def test_when_still_matches_when(self) -> None:
        assert classify_intent("when did it happen?") == "when"

    def test_corrigir_matches_debug(self) -> None:
        assert classify_intent("corrija esse problema") == "debug"

    def test_comparar_matches_compare(self) -> None:
        assert classify_intent("compare as duas opções") == "compare"

    def test_contradicts_in_why_edges(self) -> None:
        assert EdgeKind.CONTRADICTS in INTENT_TO_EDGES["why"]

    def test_contradicts_in_compare_edges(self) -> None:
        assert EdgeKind.CONTRADICTS in INTENT_TO_EDGES["compare"]

    def test_supersedes_in_review_edges(self) -> None:
        assert EdgeKind.SUPERSEDES in INTENT_TO_EDGES["review"]



class TestG7BFSDeque:
    def test_bfs_still_works_after_deque_refactor(self) -> None:
        """Garante que retrieval funciona após troca para deque."""
        g = _bootstrapped_graph()
        decision = activate(g, "analisar dados")
        assert decision.primary_synapse is not None



class TestG1RequiresNetwork:
    def test_tool_with_requires_network_true(self) -> None:
        cap = CapabilityNode.tool(
            "search.test",
            description="test",
            requires_network=True,
        )
        assert cap.requires_network is True

    def test_tool_default_requires_network_false(self) -> None:
        cap = CapabilityNode.tool("local.tool", description="test")
        assert cap.requires_network is False

    def test_check_needs_external_via_requires_network(self) -> None:
        g = CognitiveGraph()
        cap = CapabilityNode.tool(
            "custom.api",
            id="cap-api",
            description="API connector",
            requires_network=True,
        )
        g.add_node(cap)
        assert check_needs_external(g, ["custom.api"]) is True

    def test_check_needs_external_false_without_network(self) -> None:
        g = CognitiveGraph()
        cap = CapabilityNode.tool(
            "local.formatter",
            id="cap-fmt",
            description="formatter",
            requires_network=False,
        )
        g.add_node(cap)
        assert check_needs_external(g, ["local.formatter"]) is False

    def test_bootstrap_caps_have_requires_network(self) -> None:
        g = _bootstrapped_graph()
        cap = g.get_node("cap-search-web")
        assert cap is not None
        assert cap.payload.get("requires_network") is True



class TestG12CapabilitiesDraft:
    def test_bootstrap_web_search_is_draft(self) -> None:
        g = _bootstrapped_graph()
        cap = g.get_node("cap-search-web")
        assert cap is not None
        assert cap.payload.get("maturity") == "draft"

    def test_bootstrap_http_generic_is_draft(self) -> None:
        g = _bootstrapped_graph()
        cap = g.get_node("cap-http-generic")
        assert cap is not None
        assert cap.payload.get("maturity") == "draft"



class TestG4LLMCodex:
    def test_codex_synapse_exists(self) -> None:
        g = _bootstrapped_graph()
        node = g.get_node("syn-llm-codex")
        assert node is not None
        assert node.payload.get("tier_preference") == "codex"

    def test_codex_requires_edges(self) -> None:
        g = _bootstrapped_graph()
        edges = list(g.iter_edges_from("syn-criar", kinds=[EdgeKind.REQUIRES]))
        targets = {e.target_id for e in edges}
        assert "syn-llm-codex" in targets

    def test_codex_inhibits_fast(self) -> None:
        g = _bootstrapped_graph()
        edges = list(g.iter_edges_from("syn-llm-codex", kinds=[EdgeKind.INHIBITS]))
        targets = {e.target_id for e in edges}
        assert "syn-llm-fast" in targets



class TestG17GapDetection:
    def test_high_confidence_no_gap(self) -> None:
        assert detect_knowledge_gap(0.5, []) == GapType.NONE

    def test_low_confidence_no_memories_is_gap(self) -> None:
        assert detect_knowledge_gap(0.1, []) != GapType.NONE

    def test_low_confidence_low_memory_score_is_gap(self) -> None:
        node = MemoryNode.semantic(label="test", id="m1", source=_BOOT)
        mem = MatchResult(node=node, score=0.1)
        assert detect_knowledge_gap(0.1, [mem]) != GapType.NONE

    def test_low_confidence_high_memory_score_no_gap(self) -> None:
        node = MemoryNode.semantic(label="test", id="m1", source=_BOOT)
        mem = MatchResult(node=node, score=0.5)
        assert detect_knowledge_gap(0.1, [mem]) == GapType.RETRIEVAL_MISS

    def test_brain_decision_has_knowledge_gap_field(self) -> None:
        g = CognitiveGraph()
        decision = activate(g, "algo completamente desconhecido xyz")
        assert hasattr(decision, "knowledge_gap")



class TestG3InformsModulation:
    def test_informs_boosts_synapse_score(self) -> None:
        g = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="Analisar dados",
            id="syn-a",
            role="analyst",
            objective="analisar",
            tier_preference="expert",
        )
        mem = MemoryNode.semantic(
            label="fact::contexto relevante",
            id="mem-ctx",
            source=_BOOT,
        )
        g.add_node(syn)
        g.add_node(mem)
        g.add_edge(
            GraphEdge.connect(
                source_id="mem-ctx",
                target_id="syn-a",
                kind=EdgeKind.INFORMS,
                weight=0.8,
            )
        )
        syn_match = MatchResult(node=syn, score=0.5)
        mem_match = MatchResult(node=mem, score=0.6)

        result = apply_memory_modulation(g, [syn_match], [mem_match])
        assert result[0].score > 0.5  # Score boosted

    def test_no_modulation_without_memories(self) -> None:
        syn = SynapseNode.specialist(
            label="test",
            id="s",
            role="t",
            objective="t",
            tier_preference="fast",
        )
        syn_match = MatchResult(node=syn, score=0.5)
        result = apply_memory_modulation(CognitiveGraph(), [syn_match], [])
        assert result[0].score == pytest.approx(0.5)



class TestG5NegativeMemoryInhibition:
    def test_negative_memory_inhibits_target_synapse(self) -> None:
        g = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="syn",
            id="s1",
            role="t",
            objective="t",
            tier_preference="fast",
        )
        g.add_node(syn)
        mem = MemoryNode.new(
            label="lesson::não usar X",
            id="mem-neg",
            payload={
                "memory_type": "negative",
                "inhibits_synapses": ["s1"],
            },
            source=_BOOT,
        )
        syn_match = MatchResult(node=syn, score=0.8)
        mem_match = MatchResult(node=mem, score=0.6)

        result = apply_memory_modulation(g, [syn_match], [mem_match])
        assert result[0].score < 0.8
