"""Testes de resiliência por perfil de execução.

Cobre:
- LLM falha em live_lookup: dado externo obtido → resposta com raw data
- Busca falha em live_lookup: erro explícito, não stack trace
- Multistep mantém strict_on_llm_failure=True
- Profile controla comportamento, não hardcoded conditionals
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from arnaldo.capabilities.base import CapabilityResult, make_source
from arnaldo.kernel.classify import RequestComplexity
from arnaldo.kernel.execution_profile import ExecutionProfile, select_execution_profile
from arnaldo.kernel.fast_path import (
    _inline_raw_data_response,
    _inline_response_text,
    inline_capability_response,
)
from arnaldo.memory import MemoryStore
from arnaldo.session import SessionManager


class TestInlineResponseText(unittest.TestCase):
    """Testa _inline_response_text com diferentes políticas de profile."""

    def _make_payloads(self, *, success: bool, data: dict | None = None) -> list[dict]:
        return [
            {
                "capability_id": "search.public_web",
                "success": success,
                "data": data or {"results": [{"title": "Dólar hoje", "snippet": "R$ 5,20"}]},
                "error": None if success else "timeout",
                "latency_ms": 200,
                "metadata": {},
            }
        ]

    def _make_llm(self, *, content: str | None = None, fail: bool = False) -> SimpleNamespace:
        if fail:
            return SimpleNamespace(
                is_configured=True,
                chat=Mock(side_effect=RuntimeError("LLM timeout")),
            )
        return SimpleNamespace(
            is_configured=True,
            chat=Mock(return_value=SimpleNamespace(content=content or "O dólar está R$ 5,20.")),
        )

    def test_llm_success_returns_llm_content(self) -> None:
        """LLM funciona → retorna conteúdo LLM, independente do profile."""
        result = _inline_response_text(
            request="preço do dólar",
            llm_client=self._make_llm(content="Dólar a R$ 5,20"),
            messages=[{"role": "user", "content": "preço do dólar"}],
            suggested_tier="fast",
            inline_payloads=self._make_payloads(success=True),
            strict_on_llm_failure=False,
        )
        self.assertEqual(result, "Dólar a R$ 5,20")

    def test_llm_fails_strict_false_returns_raw_data(self) -> None:
        """LLM falha + strict=False → retorna dados brutos formatados."""
        result = _inline_response_text(
            request="preço do dólar",
            llm_client=self._make_llm(fail=True),
            messages=[{"role": "user", "content": "preço do dólar"}],
            suggested_tier="fast",
            inline_payloads=self._make_payloads(success=True),
            strict_on_llm_failure=False,
        )
        self.assertIn("Dólar hoje", result)

    def test_llm_fails_strict_true_returns_error(self) -> None:
        """LLM falha + strict=True → retorna erro explícito."""
        result = _inline_response_text(
            request="analise o mercado",
            llm_client=self._make_llm(fail=True),
            messages=[{"role": "user", "content": "analise"}],
            suggested_tier="expert",
            inline_payloads=self._make_payloads(success=True),
            strict_on_llm_failure=True,
        )
        self.assertIn("Erro", result)
        self.assertIn("LLM", result)

    def test_llm_fails_no_data_strict_false(self) -> None:
        """Sem dados → early return com mensagem de ausência (strict irrelevante)."""
        result = _inline_response_text(
            request="preço do dólar",
            llm_client=self._make_llm(fail=True),
            messages=[{"role": "user", "content": "preço do dólar"}],
            suggested_tier="fast",
            inline_payloads=self._make_payloads(success=False),
            strict_on_llm_failure=False,
        )
        self.assertIn("Nao consegui confirmar dados atuais", result)

    def test_llm_fails_no_data_strict_true(self) -> None:
        """Sem dados → early return com mensagem de ausência (strict irrelevante)."""
        result = _inline_response_text(
            request="analise",
            llm_client=self._make_llm(fail=True),
            messages=[{"role": "user", "content": "analise"}],
            suggested_tier="expert",
            inline_payloads=self._make_payloads(success=False),
            strict_on_llm_failure=True,
        )
        self.assertIn("Nao consegui confirmar dados atuais", result)

    def test_no_llm_client_strict_false_returns_raw_data(self) -> None:
        """Sem LLM + strict=False → dados brutos."""
        result = _inline_response_text(
            request="preço do dólar",
            llm_client=None,
            messages=[],
            suggested_tier="fast",
            inline_payloads=self._make_payloads(success=True),
            strict_on_llm_failure=False,
        )
        self.assertIn("Dólar hoje", result)


class TestLiveLookupProfile(unittest.TestCase):
    """Testa que live_lookup propaga strict_on_llm_failure=False."""

    def test_live_lookup_is_not_strict(self) -> None:
        profile = select_execution_profile(
            level="intermediate",
            needs_external_data=True,
            capability_ids=["search.public_web"],
        )
        self.assertEqual(profile.name, "live_lookup")
        self.assertFalse(profile.strict_on_llm_failure)

    def test_structured_multistep_is_strict(self) -> None:
        profile = select_execution_profile(
            level="complex",
            needs_external_data=False,
            capability_ids=[],
        )
        self.assertTrue(profile.strict_on_llm_failure)

    def test_tool_execution_local_is_not_strict(self) -> None:
        profile = select_execution_profile(
            level="intermediate",
            needs_external_data=False,
            capability_ids=["shell.local.readonly"],
        )
        self.assertEqual(profile.name, "tool_execution_local")
        self.assertFalse(profile.strict_on_llm_failure)

    def test_complexity_carries_strict_flag(self) -> None:
        """RequestComplexity propaga strict_on_llm_failure do profile."""
        complexity = RequestComplexity(
            "intermediate",
            "test",
            strict_on_llm_failure=False,
        )
        self.assertFalse(complexity.strict_on_llm_failure)


class TestRawDataResponse(unittest.TestCase):
    """Testa formatação de dados brutos quando LLM não disponível."""

    def test_search_payload_formats_results(self) -> None:
        payloads = [
            {
                "capability_id": "search.public_web",
                "success": True,
                "data": {"results": [{"title": "Bitcoin hoje", "snippet": "BTC a US$ 68.000"}]},
            }
        ]
        result = _inline_raw_data_response(request="preço bitcoin", inline_payloads=payloads)
        self.assertIn("Bitcoin hoje", result)

    def test_failed_payload_shows_error(self) -> None:
        payloads = [
            {
                "capability_id": "search.public_web",
                "success": False,
                "error": "DNS resolution failed",
            }
        ]
        result = _inline_raw_data_response(request="preço bitcoin", inline_payloads=payloads)
        self.assertIn("DNS resolution failed", result)

    def test_empty_payloads(self) -> None:
        result = _inline_raw_data_response(request="qualquer coisa", inline_payloads=[])
        self.assertIn("Nenhum dado", result)


class TestInlineCapabilityResponseIntegration(unittest.TestCase):
    """Testa inline_capability_response com LLM falhando em live_lookup."""

    def test_live_lookup_llm_fails_returns_raw_data(self) -> None:
        """Issue: 'falha transitória de LLM não derruba live_lookup se dado externo já obtido'."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory")
            sessions = SessionManager(base / "sessions")

            cap_result = CapabilityResult(
                success=True,
                data={"results": [{"title": "Dólar", "snippet": "R$ 5,20 hoje"}]},
                source=make_source("search.public_web:test"),
                metadata={},
            )

            failing_llm = SimpleNamespace(
                is_configured=True,
                chat=Mock(side_effect=RuntimeError("Azure OpenAI network error")),
            )

            with patch(
                "arnaldo.kernel.fast_path.CapabilityExecutor.execute",
                return_value=cap_result,
            ):
                result = inline_capability_response(
                    request="qual o valor do dólar hoje?",
                    session_id=None,
                    autonomy="autonomo",
                    terms_accepted=True,
                    run_id="run_llm_fail_live",
                    output_dir=base / "runs",
                    sessions=sessions,
                    memory=memory,
                    llm_client=failing_llm,
                    capability_ids=["search.public_web"],
                    suggested_tier="fast",
                    strict_on_llm_failure=False,
                )

            self.assertIn("Dólar", result.response)
            self.assertNotIn("Traceback", result.response)
            self.assertNotIn("RuntimeError", result.response)

    def test_live_lookup_capability_fails_returns_explicit_error(self) -> None:
        """Issue: 'falha de busca remota gera resposta explícita, não stack trace'."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory")
            sessions = SessionManager(base / "sessions")

            cap_result = CapabilityResult(
                success=False,
                data=None,
                source=make_source("search.public_web:test"),
                metadata={},
                error="Connection timeout to DuckDuckGo",
            )

            failing_llm = SimpleNamespace(
                is_configured=True,
                chat=Mock(side_effect=RuntimeError("LLM also down")),
            )

            with patch(
                "arnaldo.kernel.fast_path.CapabilityExecutor.execute",
                return_value=cap_result,
            ):
                result = inline_capability_response(
                    request="preço do bitcoin agora",
                    session_id=None,
                    autonomy="autonomo",
                    terms_accepted=True,
                    run_id="run_cap_fail",
                    output_dir=base / "runs",
                    sessions=sessions,
                    memory=memory,
                    llm_client=failing_llm,
                    capability_ids=["search.public_web"],
                    suggested_tier="fast",
                    strict_on_llm_failure=False,
                )

            self.assertNotIn("Traceback", result.response)
            self.assertTrue(len(result.response) > 5)


if __name__ == "__main__":
    unittest.main()
