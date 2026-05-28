from __future__ import annotations

import json
import platform
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from arnaldo.capabilities.base import CapabilityResult, make_source
from arnaldo.capabilities.catalog import CapabilityCatalog
from arnaldo.components import ToolForge
from arnaldo.contracts import RunResult
from arnaldo.graph.brain import BrainDecision
from arnaldo.kernel import ArnaldoKernel
from arnaldo.kernel.classify import RequestComplexity
from arnaldo.kernel.fast_path import inline_capability_response
from arnaldo.memory import MemoryStore
from arnaldo.runtime import GraphRuntime, SandboxManager
from arnaldo.session import SessionManager
from tests.support_llm import AlwaysSuccessTypedClient


class _RecordingLLM:
    is_configured = True

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []

    def chat(
        self,
        tier: str = "fast",
        messages: list[dict[str, str]] | None = None,
        **kwargs: object,
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "tier": tier,
                "messages": list(messages or []),
                "kwargs": dict(kwargs),
            }
        )
        return SimpleNamespace(content=self.content)


class _FailingLLM:
    is_configured = True

    def chat(
        self,
        tier: str = "fast",
        messages: list[dict[str, str]] | None = None,
        **kwargs: object,
    ) -> SimpleNamespace:
        raise RuntimeError(
            "Azure OpenAI network error: [WinError 10054] An existing connection was forcibly closed by the remote host"
        )


class InlineCapabilityRoutingTest(unittest.TestCase):
    def _build_kernel(self, base: Path) -> ArnaldoKernel:
        llm = AlwaysSuccessTypedClient()
        runtime = GraphRuntime(llm_client=llm)
        kernel = ArnaldoKernel(
            runtime=runtime,
            memory=MemoryStore(base / "memory"),
            session_manager=SessionManager(base / "sessions"),
            tool_forge=ToolForge(base / "tool_forge"),
            capabilities=CapabilityCatalog(registry_path=base / "capability_registry.json"),
            sandbox_manager=SandboxManager(base / "sandboxes"),
        )
        kernel.intent_compiler._llm_client = llm  # type: ignore[attr-defined]
        return kernel

    def test_simple_live_data_query_uses_inline_capability_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            sentinel = RunResult(
                run_id="run_live",
                run_dir=base / "runs" / "run_live",
                files={},
                session_id="session_live",
                response="R$ 5,01",
            )
            low_confidence = BrainDecision(
                primary_synapse=None,
                tier="fast",
                complexity="conversational",
                skip_full_pipeline=True,
                needs_external_data=False,
                confidence=0.0,
            )
            classified = RequestComplexity(
                "intermediate",
                "needs_external_data",
                skip_full_pipeline=True,
                use_retrieval=True,
                suggested_tier="fast",
                needs_external_data=True,
                capability_needs=["connector.*", "tool.*"],
                execution_profile="inline_capability",
                execution_capability_ids=["search.public_web"],
            )

            with (
                patch("arnaldo.kernel.kernel.brain_activate", return_value=low_confidence),
                patch("arnaldo.kernel.kernel.classify_request", return_value=classified),
                patch(
                    "arnaldo.kernel.kernel.inline_capability_response",
                    return_value=sentinel,
                ) as inline_mock,
                patch("arnaldo.kernel.kernel.run_full_pipeline") as full_mock,
            ):
                result = kernel.run(
                    "sabe me dizer o preco do dolar hoje?",
                    autonomy="autonomo",
                    output_dir=base / "runs",
                    llm_classify=True,
                )

            self.assertEqual(result.response, "R$ 5,01")
            inline_mock.assert_called_once()
            full_mock.assert_not_called()

    def test_explicit_local_command_prefers_semantic_classifier_when_brain_misses_capability(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            sentinel = RunResult(
                run_id="run_local_cmd",
                run_dir=base / "runs" / "run_local_cmd",
                files={},
                session_id="session_local_cmd",
                response="README.md",
            )
            brain_decision = BrainDecision(
                primary_synapse="syn-test",
                tier="fast",
                complexity="intermediate",
                skip_full_pipeline=True,
                needs_external_data=False,
                confidence=1.0,
                capability_needs=[],
            )
            classified = RequestComplexity(
                "intermediate",
                "explicit_local_inline",
                skip_full_pipeline=True,
                use_retrieval=True,
                suggested_tier="fast",
                needs_external_data=False,
                capability_needs=["shell.local.readonly"],
                execution_profile="inline_capability",
                execution_capability_ids=["shell.local.readonly"],
            )

            with (
                patch("arnaldo.kernel.kernel.brain_activate", return_value=brain_decision),
                patch("arnaldo.kernel.kernel.classify_request", return_value=classified),
                patch(
                    "arnaldo.kernel.kernel.inline_capability_response",
                    return_value=sentinel,
                ) as inline_mock,
                patch("arnaldo.kernel.kernel.medium_response") as medium_mock,
                patch("arnaldo.kernel.kernel.run_full_pipeline") as full_mock,
            ):
                result = kernel.run(
                    "ls",
                    autonomy="autonomo",
                    output_dir=base / "runs",
                    llm_classify=True,
                )

            self.assertEqual(result.response, "README.md")
            inline_mock.assert_called_once()
            medium_mock.assert_not_called()
            full_mock.assert_not_called()

    def test_live_lookup_prefers_semantic_classifier_when_brain_misses_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            sentinel = RunResult(
                run_id="run_live_lookup",
                run_dir=base / "runs" / "run_live_lookup",
                files={},
                session_id="session_live_lookup",
                response="R$ 5,01",
            )
            brain_decision = BrainDecision(
                primary_synapse="syn-test",
                tier="fast",
                complexity="intermediate",
                skip_full_pipeline=True,
                needs_external_data=False,
                confidence=1.0,
                capability_needs=[],
            )
            classified = RequestComplexity(
                "intermediate",
                "needs_external_data",
                skip_full_pipeline=True,
                use_retrieval=True,
                suggested_tier="fast",
                needs_external_data=True,
                capability_needs=["search.public_web"],
                execution_profile="inline_capability",
                execution_capability_ids=["search.public_web"],
            )

            with (
                patch("arnaldo.kernel.kernel.brain_activate", return_value=brain_decision),
                patch(
                    "arnaldo.kernel.kernel.classify_request", return_value=classified
                ) as classify_mock,
                patch(
                    "arnaldo.kernel.kernel.inline_capability_response",
                    return_value=sentinel,
                ) as inline_mock,
                patch("arnaldo.kernel.kernel.fast_response") as fast_mock,
                patch("arnaldo.kernel.kernel.run_full_pipeline") as full_mock,
            ):
                result = kernel.run(
                    "qual o valor do dolar hoje",
                    autonomy="autonomo",
                    output_dir=base / "runs",
                    llm_classify=True,
                )

            self.assertEqual(result.response, "R$ 5,01")
            classify_mock.assert_called_once()
            inline_mock.assert_called_once()
            fast_mock.assert_not_called()
            full_mock.assert_not_called()


class InlineCapabilityResponseTest(unittest.TestCase):
    def test_inline_capability_response_writes_search_payload_and_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory")
            sessions = SessionManager(base / "sessions")
            capability_result = CapabilityResult(
                success=True,
                data={
                    "query": "sabe me dizer o preco do dolar hoje?",
                    "results": [
                        {
                            "title": "Dolar comercial hoje",
                            "snippet": "Cotacao em torno de R$ 5,01 no fechamento recente.",
                            "url": "https://example.com/dolar-hoje",
                        }
                    ],
                    "count": 1,
                },
                source=make_source("search.public_web:test"),
                metadata={"engine": "stub"},
            )

            with patch(
                "arnaldo.kernel.fast_path.CapabilityExecutor.execute",
                return_value=capability_result,
            ) as execute_mock:
                result = inline_capability_response(
                    request="sabe me dizer o preco do dolar hoje?",
                    session_id=None,
                    autonomy="autonomo",
                    terms_accepted=True,
                    run_id="run_ext",
                    output_dir=base / "runs",
                    sessions=sessions,
                    memory=memory,
                    llm_client=_RecordingLLM("O dolar esta em torno de R$ 5,01."),
                    capability_ids=["search.public_web"],
                    suggested_tier="expert",
                )

            # LLM sintetiza — resposta é conteúdo do LLM
            self.assertIn("R$ 5,01", result.response)
            execute_mock.assert_called_once_with(
                "search.public_web",
                {"query": "sabe me dizer o preco do dolar hoje?", "max_results": 5},
            )
            self.assertTrue(result.files["response"].exists())
            self.assertTrue(result.files["inline_capabilities"].exists())

            payload = json.loads(result.files["inline_capabilities"].read_text(encoding="utf-8"))
            self.assertEqual(payload["request"], "sabe me dizer o preco do dolar hoje?")
            self.assertEqual(payload["capabilities"][0]["capability_id"], "search.public_web")
            self.assertTrue(payload["capabilities"][0]["success"])

    def test_inline_capability_response_falls_back_when_llm_network_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory")
            sessions = SessionManager(base / "sessions")
            capability_result = CapabilityResult(
                success=True,
                data={
                    "query": "sabe me dizer o preco do dolar hoje?",
                    "results": [
                        {
                            "title": "Dolar comercial hoje",
                            "snippet": "Cotacao em torno de R$ 5,01 no fechamento recente.",
                            "url": "https://example.com/dolar-hoje",
                        }
                    ],
                    "count": 1,
                },
                source=make_source("search.public_web:test"),
                metadata={"engine": "stub"},
            )

            with patch(
                "arnaldo.kernel.fast_path.CapabilityExecutor.execute",
                return_value=capability_result,
            ):
                result = inline_capability_response(
                    request="sabe me dizer o preco do dolar hoje?",
                    session_id=None,
                    autonomy="autonomo",
                    terms_accepted=True,
                    run_id="run_ext_failover",
                    output_dir=base / "runs",
                    sessions=sessions,
                    memory=memory,
                    llm_client=_FailingLLM(),
                    capability_ids=["search.public_web"],
                    suggested_tier="expert",
                )

            self.assertIn("Encontrei um resultado recente na web", result.response)
            self.assertIn("R$ 5,01", result.response)

    def test_inline_capability_response_uses_previous_topic_for_generic_search_followup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory")
            sessions = SessionManager(base / "sessions")
            session = sessions.open(
                session_id="session_followup",
                autonomy_mode="autonomo",
                terms_accepted=True,
            )
            session = sessions.record_turn(
                session,
                "qual o valor do dolar hoje",
                "Ainda vou verificar.",
            )
            capability_result = CapabilityResult(
                success=True,
                data={
                    "query": "qual o valor do dolar hoje",
                    "results": [
                        {
                            "title": "Dolar comercial hoje",
                            "snippet": "Cotacao em torno de R$ 5,01 no fechamento recente.",
                            "url": "https://example.com/dolar-hoje",
                        }
                    ],
                    "count": 1,
                },
                source=make_source("search.public_web:test"),
                metadata={"engine": "stub"},
            )

            with patch(
                "arnaldo.kernel.fast_path.CapabilityExecutor.execute",
                return_value=capability_result,
            ) as execute_mock:
                _ = inline_capability_response(
                    request="esquise no google",
                    session_id=session.id,
                    autonomy="autonomo",
                    terms_accepted=True,
                    run_id="run_followup_search",
                    output_dir=base / "runs",
                    sessions=sessions,
                    memory=memory,
                    llm_client=_FailingLLM(),
                    capability_ids=["search.public_web"],
                    suggested_tier="expert",
                )

            execute_mock.assert_called_once_with(
                "search.public_web",
                {"query": "qual o valor do dolar hoje", "max_results": 5},
            )

    def test_inline_capability_response_skips_llm_when_web_lookup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory")
            sessions = SessionManager(base / "sessions")
            capability_result = CapabilityResult(
                success=False,
                data=None,
                source=make_source("search.public_web:test"),
                error="Busca falhou: <urlopen error timed out>",
                metadata={"engine": "duckduckgo"},
            )
            llm = _RecordingLLM("Nao. Eu nao consigo pesquisar no Google daqui.")

            with patch(
                "arnaldo.kernel.fast_path.CapabilityExecutor.execute",
                return_value=capability_result,
            ):
                result = inline_capability_response(
                    request="qual o valor do dolar hoje",
                    session_id=None,
                    autonomy="autonomo",
                    terms_accepted=True,
                    run_id="run_ext_failure",
                    output_dir=base / "runs",
                    sessions=sessions,
                    memory=memory,
                    llm_client=llm,
                    capability_ids=["search.public_web"],
                    suggested_tier="expert",
                )

            self.assertIn("Nao consegui confirmar dados atuais na web agora.", result.response)
            self.assertEqual(llm.calls, [])

    def test_inline_capability_response_executes_local_shell_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            llm = _RecordingLLM("Encontrei estes itens no workspace: README.md, arnaldo, tests.")
            memory = MemoryStore(base / "memory")
            sessions = SessionManager(base / "sessions")
            capability_result = CapabilityResult(
                success=True,
                data={
                    "stdout": "README.md\r\narnaldo\r\ntests\r\n",
                    "command": "cmd /c dir .",
                },
                source=make_source("shell.local.readonly:test"),
                metadata={},
            )

            with patch(
                "arnaldo.kernel.fast_path.CapabilityExecutor.execute",
                return_value=capability_result,
            ) as execute_mock:
                result = inline_capability_response(
                    request="dentro do workspace, consegue fazer um ls?",
                    session_id=None,
                    autonomy="autonomo",
                    terms_accepted=True,
                    run_id="run_local_inline",
                    output_dir=base / "runs",
                    sessions=sessions,
                    memory=memory,
                    llm_client=llm,
                    capability_ids=["shell.local.readonly"],
                    suggested_tier="fast",
                )

            expected_command = "dir" if platform.system() == "Windows" else "ls"
            execute_mock.assert_called_once()
            self.assertEqual(execute_mock.call_args[0][0], "shell.local.readonly")
            self.assertEqual(execute_mock.call_args[0][1]["command"], expected_command)
            # LLM sintetiza a resposta com dados do contexto
            self.assertIn("README.md", result.response)
            self.assertIn("arnaldo", result.response)
            payload = json.loads(result.files["inline_capabilities"].read_text(encoding="utf-8"))
            self.assertEqual(payload["capabilities"][0]["capability_id"], "shell.local.readonly")

    def test_inline_capability_response_uses_raw_data_when_llm_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory")
            sessions = SessionManager(base / "sessions")
            capability_result = CapabilityResult(
                success=True,
                data={
                    "stdout": "README.md\r\narnaldo\r\ntests\r\n",
                    "command": "cmd /c dir .",
                },
                source=make_source("shell.local.readonly:test"),
                metadata={},
            )

            failing_llm = SimpleNamespace(
                is_configured=True,
                chat=Mock(side_effect=RuntimeError("LLM unavailable")),
            )

            with patch(
                "arnaldo.kernel.fast_path.CapabilityExecutor.execute",
                return_value=capability_result,
            ):
                result = inline_capability_response(
                    request="dentro do workspace, consegue fazer um ls?",
                    session_id=None,
                    autonomy="autonomo",
                    terms_accepted=True,
                    run_id="run_local_inline_denied",
                    output_dir=base / "runs",
                    sessions=sessions,
                    memory=memory,
                    llm_client=failing_llm,
                    capability_ids=["shell.local.readonly"],
                    suggested_tier="fast",
                    strict_on_llm_failure=False,
                )

            self.assertIn("Executei o comando local read-only", result.response)
            self.assertIn("README.md", result.response)


if __name__ == "__main__":
    unittest.main()
