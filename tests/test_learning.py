"""Testes do módulo de learning — detecção de feedback implícito."""

from __future__ import annotations

from arnaldo.graph import CognitiveGraph, EdgeKind
from arnaldo.graph.node_types import SynapseNode, MemoryNode
from arnaldo.graph.provenance import SourceRecord
from arnaldo.kernel.bootstrap import bootstrap_graph
from arnaldo.kernel.learning import (
    apply_learning_to_graph,
    compute_reward,
    detect_implicit_feedback,
    extract_quality_signals,
)

_BOOT = SourceRecord.from_bootstrap("test")


class TestDetectImplicitFeedback:
    """Testa detecção de sinais de qualidade."""

    def test_positive_obrigado(self):
        assert detect_implicit_feedback("Obrigado, ficou perfeito!") == "positive"

    def test_positive_valeu(self):
        assert detect_implicit_feedback("valeu!") == "positive"

    def test_negative_errado(self):
        assert detect_implicit_feedback("Isso está errado") == "negative"

    def test_negative_nao_funciona(self):
        assert detect_implicit_feedback("não funciona") == "negative"

    def test_correction_na_verdade(self):
        assert detect_implicit_feedback("Na verdade, eu quis dizer outra coisa") == "correction"

    def test_correction_actually(self):
        assert detect_implicit_feedback("actually, o certo seria X") == "correction"

    def test_neutral_normal(self):
        assert detect_implicit_feedback("Crie um plano de negócios") == "neutral"

    def test_empty_is_neutral(self):
        assert detect_implicit_feedback("") == "neutral"

    def test_none_equivalent(self):
        assert detect_implicit_feedback("   ") == "neutral"

    def test_correction_takes_priority_over_negative(self):
        # "na verdade" implica correção, não negatividade pura
        assert detect_implicit_feedback("Na verdade isso tá errado") == "correction"


class TestComputeReward:
    """Testa conversão feedback → reward numérico."""

    def test_positive_reward(self):
        assert compute_reward("positive") == 0.8

    def test_neutral_reward(self):
        assert compute_reward("neutral") == 0.5

    def test_negative_reward(self):
        assert compute_reward("negative") == 0.1

    def test_correction_reward(self):
        assert compute_reward("correction") == 0.15

    def test_unknown_defaults_neutral(self):
        assert compute_reward("invalid") == 0.5


class TestExtractQualitySignals:
    """Testa extração de sinais de qualidade do histórico."""

    def test_empty_history(self):
        result = extract_quality_signals([])
        assert result["avg_reward"] == 0.0
        assert result["trend"] == "negative"
        assert result["signals"] == []

    def test_positive_trend(self):
        history = [
            {"role": "assistant", "content": "Resposta"},
            {"role": "user", "content": "Obrigado, perfeito!"},
            {"role": "assistant", "content": "Outra resposta"},
            {"role": "user", "content": "Excelente!"},
        ]
        result = extract_quality_signals(history)
        assert result["trend"] == "positive"
        assert result["avg_reward"] == 0.8

    def test_negative_trend(self):
        history = [
            {"role": "user", "content": "Isso tá errado"},
            {"role": "user", "content": "Não funciona, refaz"},
        ]
        result = extract_quality_signals(history)
        assert result["trend"] == "negative"

    def test_window_limits(self):
        history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        result = extract_quality_signals(history, window=3)
        assert len(result["signals"]) == 3


class TestApplyLearningToGraph:
    """Testa plasticidade Hebbian no grafo."""

    def test_empty_node_list_returns_zero(self) -> None:
        graph = CognitiveGraph()
        result = apply_learning_to_graph(graph, activated_node_ids=[], feedback="positive")
        assert result == 0

    def test_nonexistent_node_is_skipped(self) -> None:
        graph = CognitiveGraph()
        result = apply_learning_to_graph(
            graph, activated_node_ids=["non-existent"], feedback="positive"
        )
        assert result == 0

    def test_positive_feedback_records_success(self) -> None:
        graph = CognitiveGraph()
        bootstrap_graph(graph)
        syn_id = "syn-responder"
        node_before = graph.get_node(syn_id)
        assert node_before is not None

        updated = apply_learning_to_graph(graph, activated_node_ids=[syn_id], feedback="positive")
        assert updated == 1

    def test_negative_feedback_records_failure(self) -> None:
        graph = CognitiveGraph()
        bootstrap_graph(graph)
        updated = apply_learning_to_graph(
            graph, activated_node_ids=["syn-responder"], feedback="negative"
        )
        assert updated == 1


class TestCrossLayerLinks:
    """Testa criação de edges RECALLS entre synapses e memórias."""

    def test_positive_feedback_creates_activates_edges(self) -> None:
        graph = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="test syn",
            id="syn-test",
            role="tester",
            objective="testar",
            tier_preference="fast",
        )
        mem = MemoryNode.semantic(
            label="test mem",
            id="mem-test",
            payload={"content": "test"},
            source=_BOOT,
        )
        graph.add_node(syn)
        graph.add_node(mem)

        apply_learning_to_graph(
            graph,
            activated_node_ids=["syn-test"],
            feedback="positive",
            synapse_ids=["syn-test"],
            memory_ids=["mem-test"],
        )

        edges = list(graph.iter_edges_from("syn-test", kinds=[EdgeKind.RECALLS]))
        assert len(edges) == 1
        assert edges[0].target_id == "mem-test"

    def test_negative_feedback_does_not_create_cross_links(self) -> None:
        graph = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="test syn",
            id="syn-neg",
            role="tester",
            objective="testar",
            tier_preference="fast",
        )
        mem = MemoryNode.semantic(
            label="test mem",
            id="mem-neg",
            payload={"content": "test"},
            source=_BOOT,
        )
        graph.add_node(syn)
        graph.add_node(mem)

        apply_learning_to_graph(
            graph,
            activated_node_ids=["syn-neg"],
            feedback="negative",
            synapse_ids=["syn-neg"],
            memory_ids=["mem-neg"],
        )

        edges = list(graph.iter_edges_from("syn-neg", kinds=[EdgeKind.ACTIVATES]))
        assert len(edges) == 0

        # Also verify no RECALLS edges either
        edges = list(graph.iter_edges_from("syn-neg", kinds=[EdgeKind.RECALLS]))
        assert len(edges) == 0

    def test_max_cross_links_cap_is_respected(self) -> None:
        graph = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="test syn",
            id="syn-cap",
            role="tester",
            objective="testar",
            tier_preference="fast",
        )
        graph.add_node(syn)

        mem_ids = []
        for i in range(10):
            mid = f"mem-cap-{i}"
            mem = MemoryNode.semantic(
                label=f"test mem {i}",
                id=mid,
                payload={"content": f"test {i}"},
                source=_BOOT,
            )
            graph.add_node(mem)
            mem_ids.append(mid)

        apply_learning_to_graph(
            graph,
            activated_node_ids=["syn-cap"],
            feedback="positive",
            synapse_ids=["syn-cap"],
            memory_ids=mem_ids,
        )

        edges = list(graph.iter_edges_from("syn-cap", kinds=[EdgeKind.RECALLS]))
        assert len(edges) == 5
