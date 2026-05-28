"""IntentCompiler — compilação de intenção com saída validada por LLM.

Estratégia:
- Em modo estrito (default), exige LLM configurado e falha explicitamente.
- Em modo não estrito (uso de teste), usa heurística local.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any, Dict, Optional

from arnaldo.contracts import IntentIR, new_id, utc_now
from .intent_heuristics import (
    autonomy_level,
    derive_desired_state,
    derive_primary_goal,
    external_effects_for,
    infer_open_questions,
    infer_requirements,
    infer_signals,
    normalize_request,
)

try:
    from arnaldo.llm import AzureOpenAIClient, LLMError, tier_for_task

    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IntentSignals:
    domain: str
    complexity: str
    ambition: str


@dataclass(slots=True)
class IntentEnrichment:
    desired_state: str
    primary_goal: str
    signals: IntentSignals
    requirements: list[str]
    open_questions: list[str]


class IntentCompiler:
    """Converts a human request into a generic declarative contract.

    `strict_real=True` por padrão para manter comportamento real strict
    no fluxo principal. Testes podem injetar `strict_real=False`.
    """

    def __init__(self, llm_client: Optional[Any] = None, strict_real: bool = True) -> None:
        self._llm_client = llm_client
        self._strict_real = bool(strict_real)
        if llm_client is None and _LLM_AVAILABLE:
            # Auto-init: cria client a partir do .env se disponível
            try:
                self._llm_client = AzureOpenAIClient()
            except Exception:
                self._llm_client = None

    @property
    def llm_enabled(self) -> bool:
        return bool(self._llm_client and getattr(self._llm_client, "is_configured", False))

    @property
    def llm_client(self) -> Any:
        """Acesso público ao LLM client."""
        return self._llm_client

    def compile(self, request: str, autonomy: str = "assistido") -> IntentIR:
        text = normalize_request(request)
        if not text:
            raise ValueError("Informe uma intencao para o Arnaldo executar.")

        # === Camada heurística (sempre roda, piso garantido) ===
        signals = infer_signals(text)
        desired_state = derive_desired_state(text)
        requirements = infer_requirements(signals)
        open_questions = infer_open_questions(text, signals)
        primary_goal = derive_primary_goal(text)

        # === Camada LLM (opcional, enriquece se disponível) ===
        if self._strict_real and not self.llm_enabled:
            raise RuntimeError(
                "strict_real habilitado: LLM indisponível no IntentCompiler (modo strict)."
            )
        if self.llm_enabled:
            enrichment = self._enrich_with_llm(text)
            if self._strict_real and enrichment is None:
                raise RuntimeError("strict_real habilitado: enriquecimento LLM de intenção falhou.")
            if enrichment is not None:
                desired_state = enrichment.get("desired_state") or desired_state
                primary_goal = enrichment.get("primary_goal") or primary_goal
                signals.update(enrichment.get("signals", {}))
                requirements = enrichment.get("requirements") or requirements
                open_questions = enrichment.get("open_questions") or open_questions

        return IntentIR(
            version="intent-ir/v0",
            id=new_id("intent"),
            created_at=utc_now(),
            original_request=text,
            desired_state=desired_state,
            primary_goal=primary_goal,
            autonomy={
                "mode": autonomy,
                "max_level": autonomy_level(autonomy),
            },
            constraints={
                "genericity": "high",
                "local_first": True,
                "external_side_effects": external_effects_for(autonomy),
                "private_data": "terms_based_access"
                if autonomy == "livre"
                else "explicit_permission_required",
            },
            inferred_requirements=requirements,
            open_questions=open_questions,
            signals=signals,
        )

    def _enrich_with_llm(self, request: str) -> Optional[Dict[str, Any]]:
        """Chama LLM tier=FAST para enriquecer a inferência.

        Retorna dict com campos opcionais ou `None`.
        Em modo estrito, erros/refusals propagam exceção.
        """
        if not _LLM_AVAILABLE or self._llm_client is None:
            return None

        messages = [
            {
                "role": "system",
                "content": (
                    "Você é o estágio de compilação de intenção do Arnaldo. "
                    "Sua tarefa: analisar o pedido do usuário e produzir inferências "
                    "estruturadas. Não execute a tarefa, apenas analise. "
                    "Responda em português."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Pedido do usuário: {request}\n\n"
                    "Produza:\n"
                    "1. desired_state: descrição declarativa do estado final desejado\n"
                    "2. primary_goal: tipo de objetivo (use exatamente um dos valores do schema)\n"
                    "3. signals: domínio inferido, complexidade, ambição\n"
                    "4. requirements: 3-6 requisitos críticos derivados do pedido\n"
                    "5. open_questions: 0-4 perguntas que esclareceriam ambiguidades"
                ),
            },
        ]

        try:
            tier = tier_for_task("intent.extract_signals")  # FAST
            result = self._llm_client.chat_typed(
                tier=tier,
                messages=messages,
                response_model=IntentEnrichment,
                max_tokens=1500,
                temperature=0.2,
                max_retries=2,
            )
        except (LLMError, RuntimeError, ValueError, TypeError) as exc:
            if self._strict_real:
                raise
            logger.warning("IntentCompiler LLM degraded: %s", exc)
            return None

        if result.refusal is not None:
            if self._strict_real:
                raise RuntimeError(f"IntentCompiler LLM refusal em strict_real: {result.refusal}")
            logger.warning("IntentCompiler LLM refusal: %s", result.refusal)
            return None
        if result.parsed is None:
            if self._strict_real:
                raise RuntimeError("IntentCompiler LLM retornou sem parsed em strict_real.")
            return None

        return self._validate_enrichment(asdict(result.parsed))

    @staticmethod
    def _validate_enrichment(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Valida estrutura do payload do LLM, descartando se malformado."""
        if not isinstance(payload, dict):
            return None
        # Campos esperados (todos opcionais — qualquer um pode vir e enriquecer)
        valid_goals = {
            "create_or_generate",
            "analyze_or_evaluate",
            "plan_or_structure",
            "execute_or_automate",
            "repair_or_improve",
            "decide_or_compare",
            "open_ended_execution",
        }
        primary_goal = payload.get("primary_goal")
        if primary_goal and primary_goal not in valid_goals:
            payload.pop("primary_goal", None)

        signals = payload.get("signals")
        if signals and not isinstance(signals, dict):
            payload.pop("signals", None)

        for list_field in ("requirements", "open_questions"):
            val = payload.get(list_field)
            if val is not None and not isinstance(val, list):
                payload.pop(list_field, None)

        return payload
