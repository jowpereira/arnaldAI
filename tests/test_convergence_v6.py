"""Testes de convergência v6 — ingestão, retrieval, persona, session, spawning."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from arnaldo.graph import CognitiveGraph, SourceKind, SourceRecord
from arnaldo.graph.matching import classify_intent
from arnaldo.graph.text_similarity import node_searchable_text, tfidf_rank
from arnaldo.kernel.bootstrap import bootstrap_graph
from arnaldo.kernel.classify import classify_request
from arnaldo.kernel.fast_path import _remember_turn
from arnaldo.memory import MemoryStore
from arnaldo.prompts.persona import build_system_prompt, compute_persona_context
from arnaldo.session import SessionManager

_SRC = SourceRecord(kind=SourceKind.BOOTSTRAP, identifier="test", confidence=0.9)


# ── F0: Ingestão de memória ──────────────────────────────────────────────


class MemoryIngestionTest(unittest.TestCase):
    """Verifica que conversas são ingeridas como MemoryNode no grafo."""

    def test_remember_turn_creates_memory_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "mem")
            bootstrap_graph(store.load_graph())
            initial_count = store.load_graph().node_count

            _remember_turn(store, "como funciona o deploy?", "Funciona assim...", "sess-1")

            graph = store.load_graph()
            self.assertGreater(graph.node_count, initial_count)

    def test_remember_turn_payload_has_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "mem")
            bootstrap_graph(store.load_graph())

            _remember_turn(store, "teste de ingestão", "resposta teste", "sess-1")

            from arnaldo.graph.nodes import NodeKind

            graph = store.load_graph()
            memories = list(graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False))
            self.assertGreaterEqual(len(memories), 1)
            # Verifica que o payload tem content e result
            mem = memories[-1]
            self.assertIn("content", mem.payload)
            self.assertIn("result", mem.payload)

    def test_multiple_turns_grow_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "mem")
            bootstrap_graph(store.load_graph())

            for i in range(5):
                _remember_turn(store, f"pergunta {i}", f"resposta {i}", "sess-1")

            graph = store.load_graph()
            # 5 bootstrap synapses + 5 memories (mínimo)
            self.assertGreaterEqual(graph.node_count, 10)


# ── F1: Retrieval calibrado ──────────────────────────────────────────────


class RetrievalCalibrationTest(unittest.TestCase):
    """Verifica que o retrieval funciona com dados reais no grafo."""

    def test_tfidf_finds_ingested_memory(self) -> None:
        """Após ingerir uma memória, TF-IDF deve encontrá-la."""
        docs = [
            ("mem-1", "deploy azure kubernetes configuração cluster"),
            ("mem-2", "código python implementação função"),
            ("syn-1", "Responder perguntas"),
        ]
        results = tfidf_rank("deploy no azure", docs, min_score=0.01)
        self.assertGreater(len(results), 0)
        # mem-1 deve ter score mais alto
        self.assertEqual(results[0][0], "mem-1")

    def test_node_searchable_text_includes_content(self) -> None:
        """node_searchable_text deve extrair content e result do payload."""
        node = SimpleNamespace(
            label="Conversa sobre deploy",
            kind=SimpleNamespace(value="memory"),
            payload={
                "action": "conversa",
                "content": "como funciona o deploy no Azure?",
                "result": {"summary": "Funciona com AKS e Container Apps"},
            },
        )
        text = node_searchable_text(node)
        self.assertIn("deploy", text.lower())
        self.assertIn("azure", text.lower())
        self.assertIn("aks", text.lower())

    def test_enriched_text_includes_objective(self) -> None:
        """Bootstrap synapses devem ter objective no texto buscável."""
        node = SimpleNamespace(
            label="Planejar tarefas",
            kind=SimpleNamespace(value="synapse"),
            payload={
                "objective": "Decompor requests complexos em etapas executáveis",
                "role": "planner",
            },
        )
        text = node_searchable_text(node)
        self.assertIn("decompor", text.lower())
        self.assertIn("planner", text.lower())


# ── F2: Session continuity ───────────────────────────────────────────────


class SessionContinuityTest(unittest.TestCase):
    """Verifica que sessões persistem entre restarts."""

    def test_last_active_session_finds_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(Path(tmp) / "sessions")
            state = mgr.open(autonomy_mode="assistido")
            state = mgr.record_turn(state, "oi", "e aí")

            last = mgr.last_active_session()
            self.assertEqual(last, state.id)

    def test_last_active_session_returns_none_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(Path(tmp) / "sessions")
            last = mgr.last_active_session()
            self.assertIsNone(last)

    def test_session_load_preserves_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(Path(tmp) / "sessions")
            state = mgr.open(autonomy_mode="assistido")
            state = mgr.record_turn(state, "pergunta", "resposta")

            loaded = mgr.load(state.id)
            self.assertEqual(loaded.turns, 1)
            self.assertEqual(len(loaded.message_history), 2)


# ── F3: Classificação com LLM ───────────────────────────────────────────


class ClassifyWithLLMTest(unittest.TestCase):
    """Verifica que classificação com LLM funciona na zona ambígua."""

    @staticmethod
    def _mock_llm(complexity: str = "complex", needs_external: bool = False) -> Any:
        class MockLLM:
            is_configured = True

            def chat_typed(self, **kwargs: Any) -> SimpleNamespace:
                parsed = SimpleNamespace(
                    needs_external_data=needs_external,
                    complexity=complexity,
                    capability_needs=[],
                    reasoning="mock",
                )
                return SimpleNamespace(is_success=True, parsed=parsed, refusal=None)

            def chat(self, **kwargs: Any) -> SimpleNamespace:
                return SimpleNamespace(content=complexity)

        return MockLLM()

    def test_ambiguous_request_uses_llm(self) -> None:
        result = classify_request(
            "melhore o sistema de cache", llm_client=self._mock_llm("complex")
        )
        self.assertEqual(result.level, "complex")

    def test_ambiguous_request_llm_says_simple(self) -> None:
        result = classify_request(
            "melhore o sistema de cache", llm_client=self._mock_llm("intermediate")
        )
        self.assertEqual(result.level, "intermediate")

    def test_clear_complex_skips_llm(self) -> None:
        """Request com 2+ markers não precisa de LLM."""
        result = classify_request(
            "Crie um plano detalhado e implemente a integração com o Azure DevOps"
        )
        self.assertEqual(result.level, "complex")

    def test_without_llm_ambiguous_goes_complex(self) -> None:
        """Sem LLM, request ambíguo vai para pipeline completo (conservador)."""
        result = classify_request("melhore o sistema de cache")
        self.assertEqual(result.level, "complex")
        self.assertFalse(result.skip_full_pipeline)

    def test_llm_local_false_positive_is_sanitized_out_of_inline_path(self) -> None:
        class MockLLM:
            is_configured = True

            def chat_typed(self, **kwargs: Any) -> SimpleNamespace:
                parsed = SimpleNamespace(
                    needs_external_data=False,
                    complexity="intermediate",
                    capability_needs=["filesystem.local.search"],
                    reasoning="mock",
                )
                return SimpleNamespace(is_success=True, parsed=parsed, refusal=None)

            def chat(self, **kwargs: Any) -> SimpleNamespace:
                return SimpleNamespace(content="intermediate")

        result = classify_request(
            "analise as opções e proponha o próximo passo para validar hipóteses",
            llm_client=MockLLM(),
        )
        self.assertEqual(result.level, "intermediate")
        self.assertEqual(result.execution_profile, "medium_response")
        self.assertEqual(result.capability_needs, [])
        self.assertEqual(result.execution_capability_ids, [])

    def test_llm_drops_non_capability_barewords_from_capability_needs(self) -> None:
        class MockLLM:
            is_configured = True

            def chat_typed(self, **kwargs: Any) -> SimpleNamespace:
                parsed = SimpleNamespace(
                    needs_external_data=True,
                    complexity="intermediate",
                    capability_needs=["conversational", "analysis_conceptual", "search.public_web"],
                    reasoning="mock",
                )
                return SimpleNamespace(is_success=True, parsed=parsed, refusal=None)

            def chat(self, **kwargs: Any) -> SimpleNamespace:
                return SimpleNamespace(content="intermediate")

        result = classify_request("qual o valor do dolar hoje?", llm_client=MockLLM())
        self.assertEqual(result.capability_needs, ["search.public_web"])
        self.assertEqual(result.execution_profile, "inline_capability")

    def test_explicit_local_ls_request_routes_inline_shell_profile(self) -> None:
        class MockLLM:
            is_configured = True

            def chat_typed(self, **kwargs: Any) -> SimpleNamespace:
                parsed = SimpleNamespace(
                    needs_external_data=False,
                    complexity="complex",
                    capability_needs=["filesystem.local.search"],
                    reasoning="mock",
                )
                return SimpleNamespace(is_success=True, parsed=parsed, refusal=None)

            def chat(self, **kwargs: Any) -> SimpleNamespace:
                return SimpleNamespace(content="complex")

        result = classify_request(
            "dentro do desckto tem uma asta worksace, consegue fazerum ls",
            llm_client=MockLLM(),
        )
        self.assertEqual(result.level, "intermediate")
        self.assertEqual(result.execution_profile, "inline_capability")
        self.assertTrue(result.skip_full_pipeline)
        self.assertEqual(result.execution_capability_ids, ["shell.local.readonly"])


# ── F4: Persona emergente ────────────────────────────────────────────────


class PersonaContextTest(unittest.TestCase):
    """Verifica que persona emerge do grafo real."""

    def test_persona_has_dominant_topics(self) -> None:
        graph = CognitiveGraph()
        bootstrap_graph(graph)
        # Ingere memórias com tópicos
        from arnaldo.graph.nodes import MemoryNode, NodeKind

        for i in range(3):
            node = MemoryNode(
                id=f"mem-{i}",
                kind=NodeKind.MEMORY,
                label=f"Conversa {i}",
                source=_SRC,
                payload={"action": "conversa", "content": f"texto {i}"},
            )
            graph.add_node(node)

        ctx = compute_persona_context(graph)
        self.assertIn("dominant_topics", ctx)
        self.assertIn("conversa", ctx["dominant_topics"])

    def test_persona_has_recent_memories(self) -> None:
        graph = CognitiveGraph()
        from arnaldo.graph.nodes import MemoryNode, NodeKind

        node = MemoryNode(
            id="mem-test",
            kind=NodeKind.MEMORY,
            label="Deploy discussion",
            source=_SRC,
            payload={
                "action": "conversa",
                "content": "como funciona o deploy?",
                "result": {"summary": "Usa AKS"},
            },
        )
        graph.add_node(node)

        ctx = compute_persona_context(graph)
        self.assertIn("recent_memories", ctx)
        self.assertTrue(any("deploy" in m.lower() for m in ctx["recent_memories"]))

    def test_system_prompt_includes_topics(self) -> None:
        stats = {
            "total_nodes": 15,
            "memories": 10,
            "synapses": 5,
            "capabilities": 0,
            "dominant_topics": ["conversa", "código"],
            "recent_memories": ["deploy no Azure → Usa AKS"],
        }
        prompt = build_system_prompt(graph_stats=stats)
        self.assertIn("Tópicos recentes", prompt)
        self.assertIn("conversa", prompt)


# ── F5: Spawning calibrado ──────────────────────────────────────────────


class SpawningCalibrationTest(unittest.TestCase):
    """Verifica que spawning funciona com conversas reais."""

    def test_classify_intent_has_more_intents(self) -> None:
        """classify_intent deve ter 12+ intents."""
        self.assertEqual(classify_intent("como funciona?"), "how")
        self.assertEqual(classify_intent("corrija esse bug"), "debug")
        self.assertEqual(classify_intent("implemente o código"), "code")
        self.assertEqual(classify_intent("explica o conceito"), "explain")
        self.assertEqual(classify_intent("compare as opções"), "compare")
        self.assertEqual(classify_intent("faça um plano"), "plan")
        self.assertEqual(classify_intent("revise este PR"), "review")

    def test_spawning_threshold_lowered(self) -> None:
        """Spawning deve funcionar com min_occurrences=2."""
        from arnaldo.graph.execution.spawning import detect_recurring_pattern

        history = [
            {"role": "user", "content": "como funciona o deploy?"},
            {"role": "assistant", "content": "resposta..."},
            {"role": "user", "content": "como faço o rollback?"},
        ]
        patterns = detect_recurring_pattern(history, min_occurrences=2)
        # "how" deve ser detectado com 2 ocorrências
        self.assertGreater(len(patterns), 0)
        self.assertEqual(patterns[0]["intent"], "how")

    def test_default_intent_filtered_from_spawning(self) -> None:
        """Default intent é filtrado do spawning — só intents explícitos."""
        from arnaldo.graph.execution.spawning import detect_recurring_pattern

        history = [
            {"role": "user", "content": "contexto genérico"},
            {"role": "user", "content": "outro genérico"},
        ]
        patterns = detect_recurring_pattern(history, min_occurrences=2)
        # default NÃO deve gerar pattern
        default_patterns = [p for p in patterns if p["intent"] == "default"]
        self.assertEqual(len(default_patterns), 0)


# ── F6: Lazy init ────────────────────────────────────────────────────────


class LazyInitTest(unittest.TestCase):
    """Verifica que kernel usa lazy initialization."""

    def test_kernel_init_does_not_create_intent_compiler(self) -> None:
        """IntentCompiler não deve ser criado no __init__."""
        with tempfile.TemporaryDirectory() as tmp:
            from arnaldo.kernel import ArnaldoKernel

            kernel = ArnaldoKernel(
                memory=MemoryStore(Path(tmp) / "mem"),
                session_manager=SessionManager(Path(tmp) / "sess"),
            )
            # _intent_compiler cache deve ser None até primeiro acesso
            self.assertIsNone(kernel._intent_compiler)

    def test_kernel_lazy_creates_on_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from arnaldo.kernel import ArnaldoKernel

            kernel = ArnaldoKernel(
                memory=MemoryStore(Path(tmp) / "mem"),
                session_manager=SessionManager(Path(tmp) / "sess"),
            )
            # Acessar a property deve criar a instância
            compiler = kernel.intent_compiler
            self.assertIsNotNone(compiler)
            self.assertIsNotNone(kernel._intent_compiler)


if __name__ == "__main__":
    unittest.main()
