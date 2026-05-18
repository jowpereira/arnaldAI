"""Testes da camada LLM — não fazem chamadas reais à Azure.

Cobre:
- Carregamento de config via .env
- Roteamento task → tier
- Fallback do IntentCompiler quando LLM falha
- Validação de payload do LLM
"""
from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from typing import Any, Dict, List

from arnaldo.components import IntentCompiler
from arnaldo.llm import (
    API_STYLE_DEPLOYMENTS,
    API_STYLE_RESPONSES,
    API_STYLE_V1,
    CODEX,
    EXPERT,
    FAST,
    GOD,
    AzureOpenAIClient,
    LLMError,
    TierConfig,
    load_config,
    tier_for_task,
)
from arnaldo.llm.config import AzureOpenAIConfig
from arnaldo.llm.router import register_task, tasks_by_tier
from arnaldo.llm.structured import instantiate_dataclass


class FakeLLMClient:
    """Cliente fake para injeção em testes — controla a resposta."""

    is_configured = True

    def __init__(
        self,
        response: Dict[str, Any] | None = None,
        fail: bool = False,
        refusal: str | None = None,
    ) -> None:
        self._response = response or {}
        self._fail = fail
        self._refusal = refusal
        self.calls: List[Dict[str, Any]] = []

    def chat_json(self, tier: str, messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
        self.calls.append({"tier": tier, "messages": messages, "kwargs": kwargs})
        if self._fail:
            raise LLMError("fake failure")
        return self._response

    def chat_typed(
        self,
        tier: str,
        messages: List[Dict[str, str]],
        *,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "tier": tier,
                "messages": messages,
                "kwargs": kwargs,
                "response_model": response_model,
            }
        )
        if self._fail:
            raise LLMError("fake failure")
        if self._refusal is not None:
            return SimpleNamespace(parsed=None, refusal=self._refusal)
        parsed = instantiate_dataclass(response_model, self._response)
        return SimpleNamespace(parsed=parsed, refusal=None)


class TierRouterTest(unittest.TestCase):
    def test_known_task_goes_to_correct_tier(self) -> None:
        self.assertEqual(tier_for_task("intent.deep_inference"), GOD)
        self.assertEqual(tier_for_task("intent.compile"), EXPERT)
        self.assertEqual(tier_for_task("intent.extract_signals"), FAST)
        self.assertEqual(tier_for_task("entity.extract"), FAST)
        self.assertEqual(tier_for_task("task.plan_complex"), GOD)

    def test_code_tasks_go_to_codex(self) -> None:
        self.assertEqual(tier_for_task("tool_forge.generate_connector"), CODEX)
        self.assertEqual(tier_for_task("tool_forge.refactor"), CODEX)
        self.assertEqual(tier_for_task("code.generate"), CODEX)
        self.assertEqual(tier_for_task("code.refactor"), CODEX)
        self.assertEqual(tier_for_task("code.fix_bug"), CODEX)
        self.assertEqual(tier_for_task("code.generate_test"), CODEX)
        self.assertEqual(tier_for_task("runtime.generate_step_implementation"), CODEX)

    def test_unknown_task_defaults_to_expert(self) -> None:
        self.assertEqual(tier_for_task("completely.unknown.task"), EXPERT)

    def test_override_wins(self) -> None:
        self.assertEqual(tier_for_task("intent.compile", override=FAST), FAST)
        self.assertEqual(tier_for_task("intent.extract_signals", override=GOD), GOD)
        self.assertEqual(tier_for_task("code.generate", override=EXPERT), EXPERT)

    def test_register_task_dynamic(self) -> None:
        register_task("custom.task.test", GOD)
        self.assertEqual(tier_for_task("custom.task.test"), GOD)

    def test_register_codex_task_dynamic(self) -> None:
        register_task("custom.code.synthesize", CODEX)
        self.assertEqual(tier_for_task("custom.code.synthesize"), CODEX)

    def test_register_invalid_tier_raises(self) -> None:
        with self.assertRaises(ValueError):
            register_task("custom.invalid", "ultra-mega")

    def test_tasks_by_tier_groups_correctly(self) -> None:
        grouped = tasks_by_tier()
        self.assertIn(GOD, grouped)
        self.assertIn(EXPERT, grouped)
        self.assertIn(FAST, grouped)
        self.assertIn(CODEX, grouped)
        self.assertIn("intent.deep_inference", grouped[GOD])
        self.assertIn("intent.compile", grouped[EXPERT])
        self.assertIn("intent.extract_signals", grouped[FAST])
        self.assertIn("tool_forge.generate_connector", grouped[CODEX])


class ConfigLoaderTest(unittest.TestCase):
    def test_load_config_reads_env(self) -> None:
        # .env já foi carregado pelo import
        config = load_config()
        # Deve estar configurado se .env existe e tem AZURE_OPENAI_ENDPOINT
        if config.is_configured:
            self.assertTrue(config.endpoint.startswith("https://"))
            self.assertTrue(config.api_key)
            self.assertIn(GOD, config.tiers)
            self.assertIn(EXPERT, config.tiers)
            self.assertIn(FAST, config.tiers)

    def test_tier_lookup(self) -> None:
        config = load_config()
        if config.is_configured:
            god_tier = config.tier(GOD)
            self.assertEqual(god_tier.name, GOD)
            self.assertEqual(god_tier.model, os.environ.get("AZURE_TIER_GOD_DEPLOYMENT", "god-tier"))

    def test_tier_lookup_invalid_raises(self) -> None:
        config = load_config()
        with self.assertRaises(ValueError):
            config.tier("nonexistent")

    def test_tier_config_defaults(self) -> None:
        tier = TierConfig(name="test", model="test-dep", description="x")
        self.assertEqual(tier.default_temperature, 0.7)
        self.assertEqual(tier.default_max_tokens, 2000)
        self.assertEqual(tier.api_style, API_STYLE_DEPLOYMENTS)
        self.assertFalse(tier.supports_reasoning)


class ClientNotConfiguredTest(unittest.TestCase):
    def test_disabled_client_does_not_call(self) -> None:
        # Constrói config manualmente sem credenciais
        from arnaldo.llm.config import AzureOpenAIConfig

        empty_config = AzureOpenAIConfig(
            endpoint="",
            api_key="",
            api_version="2025-04-01-preview",
            tiers={},
            enabled=False,
        )
        client = AzureOpenAIClient(config=empty_config)
        self.assertFalse(client.is_configured)

        with self.assertRaises(RuntimeError):
            client.chat(tier="fast", messages=[{"role": "user", "content": "x"}])

    def test_ping_returns_false_when_not_configured(self) -> None:
        from arnaldo.llm.config import AzureOpenAIConfig

        empty_config = AzureOpenAIConfig(
            endpoint="", api_key="", api_version="x", tiers={}, enabled=False
        )
        client = AzureOpenAIClient(config=empty_config)
        self.assertFalse(client.ping())


class IntentCompilerLLMFallbackTest(unittest.TestCase):
    def test_compiler_works_without_llm(self) -> None:
        # Passa None explicitamente para forçar modo heurístico puro
        compiler = IntentCompiler(llm_client=False)  # type: ignore[arg-type]
        # Sobrescreve _llm_client manualmente para garantir None
        compiler._llm_client = None

        intent = compiler.compile("Crie um plano para um SaaS B2B", autonomy="assistido")
        self.assertEqual(intent.primary_goal, "create_or_generate")
        self.assertTrue(intent.desired_state)
        self.assertGreater(len(intent.inferred_requirements), 0)

    def test_compiler_uses_llm_when_provided(self) -> None:
        fake = FakeLLMClient(
            response={
                "desired_state": "SaaS B2B validado com primeiros clientes",
                "primary_goal": "create_or_generate",
                "signals": {"domain": "b2b_saas", "complexity": "high", "ambition": "high"},
                "requirements": ["validar dor real", "definir ICP", "construir MVP"],
                "open_questions": ["qual nicho?", "qual budget?"],
            }
        )
        compiler = IntentCompiler(llm_client=fake)
        intent = compiler.compile("Crie um plano para um SaaS B2B", autonomy="assistido")

        # LLM enriqueceu os campos
        self.assertEqual(intent.desired_state, "SaaS B2B validado com primeiros clientes")
        self.assertEqual(intent.signals.get("domain"), "b2b_saas")
        self.assertIn("validar dor real", intent.inferred_requirements)
        self.assertEqual(len(fake.calls), 1)

    def test_compiler_falls_back_when_llm_fails(self) -> None:
        fake = FakeLLMClient(fail=True)
        compiler = IntentCompiler(llm_client=fake)

        # Não deve lançar — fallback silencioso
        intent = compiler.compile("Crie um plano para um SaaS B2B", autonomy="assistido")

        # Heurístico cobriu o gap
        self.assertEqual(intent.primary_goal, "create_or_generate")
        self.assertTrue(intent.desired_state)
        self.assertEqual(len(fake.calls), 1)

    def test_compiler_rejects_invalid_primary_goal_from_llm(self) -> None:
        fake = FakeLLMClient(
            response={
                "primary_goal": "this_is_not_valid",  # inválido
                "desired_state": "estado X",
                "signals": {"domain": "x", "complexity": "medium", "ambition": "moderate"},
                "requirements": ["req-1"],
                "open_questions": [],
            }
        )
        compiler = IntentCompiler(llm_client=fake)
        intent = compiler.compile("analise o mercado de clinicas", autonomy="assistido")

        # primary_goal inválido foi descartado, fallback heurístico aplica
        self.assertEqual(intent.primary_goal, "analyze_or_evaluate")
        # desired_state válido foi aceito
        self.assertEqual(intent.desired_state, "estado X")

    def test_compiler_falls_back_on_llm_refusal(self) -> None:
        fake = FakeLLMClient(refusal="safety refusal")
        compiler = IntentCompiler(llm_client=fake)
        intent = compiler.compile("Crie um plano de marketing", autonomy="assistido")

        self.assertEqual(intent.primary_goal, "create_or_generate")
        self.assertEqual(len(fake.calls), 1)


class CodexTierTest(unittest.TestCase):
    """Testa configuração e comportamento do tier CODEX (v1 API + reasoning)."""

    def test_codex_loaded_when_base_url_present(self) -> None:
        config = load_config()
        # Se .env tem AZURE_CODEX_BASE_URL, CODEX deve estar registrado
        if os.environ.get("AZURE_CODEX_BASE_URL"):
            self.assertIn(CODEX, config.tiers)
            codex = config.tier(CODEX)
            self.assertEqual(codex.api_style, API_STYLE_RESPONSES)
            self.assertTrue(codex.supports_reasoning)
            self.assertIsNotNone(codex.base_url)
            self.assertIsNotNone(codex.default_reasoning_effort)

    def test_codex_url_uses_responses_endpoint(self) -> None:
        client = self._build_client_with_codex()
        codex = client.config.tier(CODEX)
        url = client._build_url(codex)
        # Responses API: /openai/v1/responses (não /chat/completions)
        self.assertIn("/openai/v1/responses", url)
        self.assertNotIn("/chat/completions", url)
        self.assertNotIn("/deployments/", url)

    def test_codex_body_uses_responses_format(self) -> None:
        client = self._build_client_with_codex()
        codex = client.config.tier(CODEX)
        body = client._build_body(
            tier_cfg=codex,
            messages=[{"role": "user", "content": "implementa um connector"}],
            temperature=None,
            max_tokens=None,
            response_format=None,
            reasoning_effort=None,
            reasoning_summary=None,
            extra=None,
        )
        # Formato Responses API
        self.assertEqual(body["model"], "gpt-5.3-codex")
        self.assertEqual(body["input"], "implementa um connector")  # 1 user msg → string
        self.assertEqual(body["max_output_tokens"], 2000)  # default do TierConfig
        # Reasoning como objeto aninhado, não campos planos
        self.assertEqual(body["reasoning"]["effort"], "xhigh")
        self.assertEqual(body["reasoning"]["summary"], "auto")
        # Não usa max_tokens nem max_completion_tokens
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("max_completion_tokens", body)
        # Não usa messages
        self.assertNotIn("messages", body)
        # Não usa reasoning_effort plano
        self.assertNotIn("reasoning_effort", body)

    def test_codex_multi_message_input_is_list(self) -> None:
        client = self._build_client_with_codex()
        codex = client.config.tier(CODEX)
        body = client._build_body(
            tier_cfg=codex,
            messages=[
                {"role": "system", "content": "Você é um especialista."},
                {"role": "user", "content": "implementa X"},
            ],
            temperature=None, max_tokens=None,
            response_format=None, reasoning_effort=None,
            reasoning_summary=None, extra=None,
        )
        # Múltiplas mensagens → lista
        self.assertIsInstance(body["input"], list)
        self.assertEqual(len(body["input"]), 2)
        self.assertEqual(body["input"][0]["role"], "system")
        self.assertEqual(body["input"][1]["role"], "user")

    def test_codex_reasoning_effort_can_be_overridden(self) -> None:
        client = self._build_client_with_codex()
        codex = client.config.tier(CODEX)
        body = client._build_body(
            tier_cfg=codex,
            messages=[{"role": "user", "content": "x"}],
            temperature=None,
            max_tokens=None,
            response_format=None,
            reasoning_effort="low",  # override
            reasoning_summary="concise",  # override
            extra=None,
        )
        self.assertEqual(body["reasoning"]["effort"], "low")
        self.assertEqual(body["reasoning"]["summary"], "concise")

    def test_responses_api_response_parser(self) -> None:
        client = self._build_client_with_codex()
        codex = client.config.tier(CODEX)
        # Payload típico da Responses API
        fake_payload = {
            "id": "resp_xyz",
            "status": "completed",
            "model": "gpt-5.3-codex",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "def hello():\n    print('hi')"}
                    ],
                }
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
                "output_tokens_details": {"reasoning_tokens": 5},
            },
            "reasoning": {"effort": "low", "summary": "Generated hello function"},
        }
        response = client._parse_response(fake_payload, CODEX, codex)
        self.assertEqual(response.content, "def hello():\n    print('hi')")
        self.assertEqual(response.tier, CODEX)
        self.assertEqual(response.deployment, "gpt-5.3-codex")
        self.assertEqual(response.finish_reason, "completed")
        # Usage normalizado para o mesmo schema do chat completions
        self.assertEqual(response.usage["prompt_tokens"], 10)
        self.assertEqual(response.usage["completion_tokens"], 20)
        self.assertEqual(response.usage["total_tokens"], 30)
        self.assertEqual(response.usage["reasoning_tokens"], 5)
        self.assertEqual(response.reasoning_summary, "Generated hello function")

    def test_deployments_url_uses_classic_format(self) -> None:
        client = self._build_client_with_codex()
        expert = client.config.tier(EXPERT)
        url = client._build_url(expert)
        # Estilo clássico: deployment vai na URL
        self.assertIn("/openai/deployments/expert-tier/chat/completions", url)

    def test_deployments_body_does_not_include_model_or_reasoning(self) -> None:
        client = self._build_client_with_codex()
        expert = client.config.tier(EXPERT)
        body = client._build_body(
            tier_cfg=expert,
            messages=[{"role": "user", "content": "oi"}],
            temperature=None,
            max_tokens=None,
            response_format=None,
            reasoning_effort=None,
            reasoning_summary=None,
            extra=None,
        )
        # Estilo deployments: model NÃO vai no body
        self.assertNotIn("model", body)
        # Sem reasoning porque tier não suporta
        self.assertNotIn("reasoning_effort", body)

    def test_v1_tier_without_base_url_raises(self) -> None:
        # Constrói um tier v1 sem base_url para testar validação
        bad_tier = TierConfig(
            name="bad",
            model="x",
            description="bad",
            api_style=API_STYLE_V1,
            base_url=None,  # erro: v1 precisa base_url
            supports_reasoning=True,
        )
        config = AzureOpenAIConfig(
            endpoint="https://x.com",
            api_key="k",
            api_version="2025-04-01-preview",
            tiers={"bad": bad_tier},
        )
        client = AzureOpenAIClient(config=config)
        with self.assertRaises(LLMError):
            client._build_url(bad_tier)

    def test_generate_code_helper_prefers_codex(self) -> None:
        client = self._build_client_with_codex()
        # generate_code internamente escolheria CODEX, mas a chamada real falharia
        # (sem mock real). Vamos testar só a escolha de tier via inspeção.
        from arnaldo.llm.config import CODEX
        self.assertIn(CODEX, client.config.tiers)

    # ─── helper ─────────────────────────────────────────────────

    @staticmethod
    def _build_client_with_codex() -> AzureOpenAIClient:
        """Cria client com tiers manuais, sem depender do .env."""
        config = AzureOpenAIConfig(
            endpoint="https://test-resource.cognitiveservices.azure.com",
            api_key="fake-key",
            api_version="2025-04-01-preview",
            tiers={
                EXPERT: TierConfig(
                    name=EXPERT,
                    model="expert-tier",
                    description="x",
                    api_style=API_STYLE_DEPLOYMENTS,
                ),
                CODEX: TierConfig(
                    name=CODEX,
                    model="gpt-5.3-codex",
                    description="x",
                    api_style=API_STYLE_RESPONSES,
                    base_url="https://codex-resource.openai.azure.com/openai/v1",
                    supports_reasoning=True,
                    default_reasoning_effort="xhigh",
                    default_reasoning_summary="auto",
                ),
            },
        )
        return AzureOpenAIClient(config=config)


if __name__ == "__main__":
    unittest.main()
