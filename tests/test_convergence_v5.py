"""Testes para as features de convergência v5."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from arnaldo.kernel.classify import RequestComplexity, classify_request
from arnaldo.kernel.learning import (
    apply_learning_to_graph,
    compute_reward,
    detect_implicit_feedback,
)
from arnaldo.graph.text_similarity import (
    cosine_sim,
    node_searchable_text,
    tfidf_rank,
    tokenize,
)
from arnaldo.kernel.bootstrap import bootstrap_graph
from arnaldo.prompts.persona import build_system_prompt, compute_graph_stats
from arnaldo.graph import CognitiveGraph, MemoryNode, SourceKind, SourceRecord


_SRC = SourceRecord(kind=SourceKind.BOOTSTRAP, identifier="test", confidence=0.9)


class ClassifyRequestTest(unittest.TestCase):
    """Testa classificação de requests em 3 níveis."""

    def test_greeting_is_conversational(self) -> None:
        c = classify_request("oi")
        self.assertEqual(c.level, "conversational")
        self.assertTrue(c.skip_full_pipeline)

    def test_closing_is_conversational(self) -> None:
        c = classify_request("obrigado")
        self.assertEqual(c.level, "conversational")

    def test_simple_question_is_intermediate(self) -> None:
        c = classify_request("o que é machine learning?")
        self.assertEqual(c.level, "intermediate")
        self.assertTrue(c.skip_full_pipeline)
        self.assertTrue(c.use_retrieval)

    def test_short_request_without_verbs_is_intermediate(self) -> None:
        c = classify_request("status do projeto")
        self.assertEqual(c.level, "intermediate")
        self.assertTrue(c.use_retrieval)

    def test_creation_verb_forces_full_pipeline(self) -> None:
        c = classify_request("Crie um plano de ação completo")
        self.assertFalse(c.skip_full_pipeline)

    def test_multi_objective_is_complex(self) -> None:
        c = classify_request("Analise o mercado, crie um relatório e integre com o dashboard")
        self.assertEqual(c.level, "complex")
        self.assertFalse(c.skip_full_pipeline)

    def test_empty_is_conversational(self) -> None:
        c = classify_request("")
        self.assertEqual(c.level, "conversational")

    def test_correction_is_conversational_with_retrieval(self) -> None:
        c = classify_request("na verdade eu quis dizer outra coisa")
        self.assertEqual(c.level, "conversational")
        self.assertTrue(c.use_retrieval)

    def test_request_complexity_to_dict(self) -> None:
        c = RequestComplexity("intermediate", "test", use_retrieval=True, suggested_tier="fast")
        d = c.to_dict()
        self.assertEqual(d["level"], "intermediate")
        self.assertTrue(d["use_retrieval"])
        self.assertEqual(d["suggested_tier"], "fast")


class TFIDFTest(unittest.TestCase):
    """Testa TF-IDF sem dependências externas."""

    def test_tokenize_removes_stopwords(self) -> None:
        tokens = tokenize("o gato é um animal de estimação")
        self.assertNotIn("o", tokens)
        self.assertNotIn("é", tokens)
        self.assertIn("gato", tokens)
        self.assertIn("animal", tokens)

    def test_cosine_sim_identical(self) -> None:
        v = {"a": 1.0, "b": 2.0}
        self.assertAlmostEqual(cosine_sim(v, v), 1.0, places=5)

    def test_cosine_sim_orthogonal(self) -> None:
        a = {"x": 1.0}
        b = {"y": 1.0}
        self.assertAlmostEqual(cosine_sim(a, b), 0.0)

    def test_tfidf_rank_basic(self) -> None:
        docs = [
            ("d1", "python machine learning tutorial"),
            ("d2", "receita de bolo de chocolate"),
            ("d3", "python data science análise"),
        ]
        results = tfidf_rank("python machine learning", docs)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0][0], "d1")

    def test_tfidf_rank_empty(self) -> None:
        self.assertEqual(tfidf_rank("", []), [])

    def test_node_searchable_text(self) -> None:
        node = SimpleNamespace(
            label="test node",
            payload={"action": "analyze", "content": "hello world"},
        )
        text = node_searchable_text(node)
        self.assertIn("test node", text)
        self.assertIn("analyze", text)
        self.assertIn("hello world", text)


class LearningTest(unittest.TestCase):
    """Testa learning real com plasticidade."""

    def test_apply_learning_positive(self) -> None:
        graph = CognitiveGraph()
        node = MemoryNode.semantic(label="test", id="mem1", payload={}, source=_SRC)
        graph.add_node(node)
        updated = apply_learning_to_graph(graph, activated_node_ids=["mem1"], feedback="positive")
        self.assertEqual(updated, 1)

    def test_apply_learning_missing_node(self) -> None:
        graph = CognitiveGraph()
        updated = apply_learning_to_graph(
            graph, activated_node_ids=["nonexistent"], feedback="positive"
        )
        self.assertEqual(updated, 0)

    def test_apply_learning_empty(self) -> None:
        graph = CognitiveGraph()
        updated = apply_learning_to_graph(graph, activated_node_ids=[], feedback="positive")
        self.assertEqual(updated, 0)

    def test_detect_implicit_feedback(self) -> None:
        self.assertEqual(detect_implicit_feedback("obrigado, perfeito!"), "positive")
        self.assertEqual(detect_implicit_feedback("tá errado"), "negative")
        self.assertEqual(detect_implicit_feedback("na verdade eu quis"), "correction")
        self.assertEqual(detect_implicit_feedback("hmm ok"), "neutral")

    def test_compute_reward(self) -> None:
        self.assertGreater(compute_reward("positive"), 0.5)
        self.assertLess(compute_reward("negative"), 0.5)


class BootstrapTest(unittest.TestCase):
    """Testa bootstrap do grafo."""

    def test_bootstrap_empty_graph(self) -> None:
        graph = CognitiveGraph()
        added = bootstrap_graph(graph)
        self.assertGreater(added, 0)
        self.assertGreater(graph.node_count, 0)

    def test_bootstrap_idempotent(self) -> None:
        graph = CognitiveGraph()
        first = bootstrap_graph(graph)
        second = bootstrap_graph(graph)
        self.assertGreater(first, 0)
        self.assertEqual(second, 0)

    def test_bootstrap_has_seed_synapses(self) -> None:
        from arnaldo.graph.nodes import NodeKind

        graph = CognitiveGraph()
        bootstrap_graph(graph)
        synapses = list(graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=True))
        self.assertGreaterEqual(len(synapses), 3)


class DynamicPersonaTest(unittest.TestCase):
    """Testa persona dinâmica baseada no estado do grafo."""

    def test_build_system_prompt_with_graph_stats(self) -> None:
        stats = {
            "total_nodes": 42,
            "memories": 30,
            "synapses": 10,
            "capabilities": 2,
            "consolidated_expertise": ["Responder perguntas", "Planejar tarefas"],
            "dominant_topics": ["conversa", "código"],
        }
        prompt = build_system_prompt(graph_stats=stats)
        self.assertIn("42 nós", prompt)
        self.assertIn("Tópicos recentes", prompt)

    def test_build_system_prompt_empty_graph(self) -> None:
        stats = {"total_nodes": 0}
        prompt = build_system_prompt(graph_stats=stats)
        self.assertIn("Primeiro contato", prompt)

    def test_compute_graph_stats_empty(self) -> None:
        graph = CognitiveGraph()
        stats = compute_graph_stats(graph)
        self.assertEqual(stats["total_nodes"], 0)

    def test_compute_graph_stats_with_nodes(self) -> None:
        graph = CognitiveGraph()
        bootstrap_graph(graph)
        stats = compute_graph_stats(graph)
        self.assertGreater(stats["total_nodes"], 0)
        self.assertGreater(stats["synapses"], 0)


if __name__ == "__main__":
    unittest.main()
