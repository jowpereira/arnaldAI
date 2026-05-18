"""IntentCompiler — heurístico com upgrade opcional via LLM.

Estratégia:
- Sempre roda o pipeline heurístico (zero dep, determinístico, sem custo)
- Se LLM client estiver configurado (.env presente), enriquece os campos
  fracos (desired_state, signals, requirements, open_questions) com inferência
- Se LLM falhar por qualquer razão, mantém o resultado heurístico
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any, Dict, List, Optional
import re

from arnaldo.contracts import IntentIR, new_id, utc_now

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

    Pode receber um LLM client opcional. Se ausente ou desconfigurado,
    funciona em modo puramente heurístico (comportamento original).
    """

    def __init__(self, llm_client: Optional[Any] = None) -> None:
        self._llm_client = llm_client
        if llm_client is None and _LLM_AVAILABLE:
            # Auto-init: cria client a partir do .env se disponível
            try:
                self._llm_client = AzureOpenAIClient()
            except Exception:
                self._llm_client = None

    @property
    def llm_enabled(self) -> bool:
        return bool(self._llm_client and getattr(self._llm_client, "is_configured", False))

    def compile(self, request: str, autonomy: str = "assistido") -> IntentIR:
        text = normalize_request(request)
        if not text:
            raise ValueError("Informe uma intencao para o Arnaldo executar.")

        # === Camada heurística (sempre roda, é o fallback garantido) ===
        signals = infer_signals(text)
        desired_state = derive_desired_state(text)
        requirements = infer_requirements(signals)
        open_questions = infer_open_questions(text, signals)
        primary_goal = derive_primary_goal(text)

        # === Camada LLM (opcional, enriquece se disponível) ===
        if self.llm_enabled:
            enrichment = self._enrich_with_llm(text)
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
                "private_data": "terms_based_access" if autonomy == "livre" else "explicit_permission_required",
            },
            inferred_requirements=requirements,
            open_questions=open_questions,
            signals=signals,
        )

    def _enrich_with_llm(self, request: str) -> Optional[Dict[str, Any]]:
        """Chama LLM tier=FAST para enriquecer a inferência.

        Retorna dict com campos opcionais, ou None se LLM falhar.
        Nunca lança — falha silenciosa é o fallback projetado.
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
            logger.warning("IntentCompiler LLM fallback: %s", exc)
            return None

        if result.refusal is not None:
            logger.warning("IntentCompiler LLM refusal: %s", result.refusal)
            return None
        if result.parsed is None:
            return None

        return self._validate_enrichment(asdict(result.parsed))

    @staticmethod
    def _validate_enrichment(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Valida estrutura do payload do LLM, descartando se malformado."""
        if not isinstance(payload, dict):
            return None
        # Campos esperados (todos opcionais — qualquer um pode vir e enriquecer)
        valid_goals = {
            "create_or_generate", "analyze_or_evaluate", "plan_or_structure",
            "execute_or_automate", "repair_or_improve", "decide_or_compare",
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


# ─── Funções heurísticas (mantidas intactas para fallback) ──────────


def normalize_request(request: str) -> str:
    return " ".join((request or "").strip().split())


def derive_desired_state(text: str) -> str:
    return text[:180]


def derive_primary_goal(text: str) -> str:
    lowered = text.lower()
    goal_patterns = [
        ("crie|criar|construa|construir|gere|gerar|monte|montar|implemente|implementar", "create_or_generate"),
        ("analise|analisar|avalie|avaliar|diagnostique|diagnosticar|revise|revisar", "analyze_or_evaluate"),
        ("planeje|planejar|organize|organizar|priorize|priorizar|estruture|estruturar", "plan_or_structure"),
        ("automatize|automatizar|execute|executar|rode|rodar|operacionalize|operacionalizar", "execute_or_automate"),
        ("corrija|corrigir|melhore|melhorar|otimize|otimizar|refatore|refatorar", "repair_or_improve"),
        ("decida|decidir|escolha|escolher|compare|comparar|selecione|selecionar", "decide_or_compare"),
    ]
    for pattern, goal in goal_patterns:
        if re.search(pattern, lowered):
            return goal
    return "open_ended_execution"


def autonomy_level(autonomy: str) -> int:
    levels = {
        "manual": 1,
        "assistido": 2,
        "autonomo": 3,
        "livre": 6,
    }
    return levels.get(autonomy, 2)


def external_effects_for(autonomy: str) -> str:
    if autonomy == "livre":
        return "allowed_if_policy_compliant"
    return "approval_required"


def infer_signals(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    words = lowered.split()
    vague_terms = count_matches(lowered, ["qualquer", "tudo", "generico", "amplo", "melhor", "ideal"])
    external_terms = count_matches(lowered, ["publicar", "enviar", "comprar", "deletar", "deploy", "cliente"])
    sensitive_terms = count_matches(lowered, ["senha", "token", "privado", "cpf", "pagamento", "dados pessoais"])
    irreversible_terms = count_matches(lowered, ["deletar", "apagar", "publicar", "comprar", "migrar"])

    return {
        "word_count": len(words),
        "ambiguity_score": min(3, vague_terms + (1 if len(words) < 8 else 0)),
        "external_impact_score": min(3, external_terms),
        "data_sensitivity_score": min(3, sensitive_terms),
        "irreversibility_score": min(3, irreversible_terms),
        "goal_type": derive_primary_goal(text),
    }


def infer_requirements(signals: Dict[str, Any]) -> List[str]:
    requirements = [
        "preservar intencao original",
        "produzir artefato verificavel",
        "registrar decisoes e evidencias",
        "marcar incertezas em vez de escondelas",
    ]
    if signals["ambiguity_score"] > 0:
        requirements.append("separar inferencias de fatos")
    if signals["external_impact_score"] > 0:
        requirements.append("bloquear efeitos externos sem aprovacao")
    return requirements


def infer_open_questions(text: str, signals: Dict[str, Any]) -> List[str]:
    questions = []
    if signals["ambiguity_score"] >= 2:
        questions.append("qual nivel de profundidade e suficiente para esta execucao?")
    if signals["external_impact_score"] > 0:
        questions.append("quais acoes externas estao autorizadas?")
    if signals["word_count"] < 8:
        questions.append("qual artefato final o usuario espera receber?")
    return questions


def count_matches(text: str, terms: List[str]) -> int:
    return sum(1 for term in terms if term in text)
