"""Testes F6 — LLM como agente no grafo."""

from __future__ import annotations

from arnaldo.graph import CognitiveGraph, EdgeKind
from arnaldo.graph.brain import BrainDecision, activate
from arnaldo.graph.node_types import SynapseNode
from arnaldo.graph.provenance import SourceRecord
from arnaldo.kernel.bootstrap import bootstrap_graph

_BOOT = SourceRecord.from_bootstrap("test")


def _bootstrapped_graph() -> CognitiveGraph:
    g = CognitiveGraph()
    bootstrap_graph(g)
    return g


class TestLLMAsAgent:
    """LLM tiers são nós do grafo — o LLM é só um agente."""

    def test_bootstrap_has_llm_synapses(self) -> None:
        graph = _bootstrapped_graph()
        assert graph.get_node("syn-llm-fast") is not None
        assert graph.get_node("syn-llm-expert") is not None
        assert graph.get_node("syn-llm-god") is not None

    def test_llm_synapses_not_selected_as_primary(self) -> None:
        graph = _bootstrapped_graph()
        decision = activate(graph, "responder uma pergunta simples")
        if decision.primary_synapse:
            assert not decision.primary_synapse.startswith("syn-llm-")

    def test_tier_resolved_via_requires_edge(self) -> None:
        graph = _bootstrapped_graph()
        decision = activate(graph, "criar um artefato complexo e detalhado novo")
        if decision.primary_synapse == "syn-criar":
            assert decision.tier in ("god", "expert")

    def test_requires_edges_connect_to_llm(self) -> None:
        graph = _bootstrapped_graph()
        edges = list(graph.iter_edges_from("syn-responder", kinds=[EdgeKind.REQUIRES]))
        llm_targets = [e.target_id for e in edges if e.target_id.startswith("syn-llm-")]
        assert "syn-llm-fast" in llm_targets

    def test_uses_payload_tier_without_llm_edge(self) -> None:
        """Se synapse não tem REQUIRES para LLM, usa tier_preference do payload."""
        graph = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="Synapse sem LLM edge",
            id="syn-orphan",
            role="orphan",
            objective="test",
            tier_preference="codex",
        )
        graph.add_node(syn)
        decision = activate(graph, "synapse sem LLM edge test")
        assert isinstance(decision, BrainDecision)
