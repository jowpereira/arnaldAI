"""Classificação de complexidade de requests — 3 níveis de processamento."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

logger = logging.getLogger("arnaldo.kernel")


class RequestComplexity:
    """Resultado da classificação de complexidade."""

    __slots__ = ("level", "reason", "skip_full_pipeline", "use_retrieval", "suggested_tier")

    def __init__(
        self,
        level: str,
        reason: str,
        *,
        skip_full_pipeline: bool = False,
        use_retrieval: bool = False,
        suggested_tier: str = "fast",
    ) -> None:
        self.level = level
        self.reason = reason
        self.skip_full_pipeline = skip_full_pipeline
        self.use_retrieval = use_retrieval
        self.suggested_tier = suggested_tier

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "reason": self.reason,
            "skip_full_pipeline": self.skip_full_pipeline,
            "use_retrieval": self.use_retrieval,
            "suggested_tier": self.suggested_tier,
        }


# Padrões de requests puramente conversacionais (saudações, despedidas)
_GREETING_PATTERNS = re.compile(
    r"^(oi|olá|ola|hey|hello|hi|bom dia|boa tarde|boa noite|e aí|fala)\b",
    re.IGNORECASE,
)
_CLOSING_PATTERNS = re.compile(
    r"^(obrigado|valeu|tchau|bye|até|thanks|brigado|falou)\b",
    re.IGNORECASE,
)

# Perguntas simples / follow-ups → intermediate (1 LLM call + retrieval)
_SIMPLE_QUESTION = re.compile(
    r"^(o que é|quem é|quando|onde|como funciona|qual é|me explique|"
    r"me fala sobre|explica|define|o que significa|como faço|"
    r"como eu|pra que serve|qual a diferença|por que|porque)\b",
    re.IGNORECASE,
)
_FOLLOWUP_PATTERNS = re.compile(
    r"^(e sobre|pode detalhar|mais sobre|continua|"
    r"e quanto|como assim|tipo o que|exemplo|elabora|"
    r"sim|não|ok|entendi|certo|hmm)\b",
    re.IGNORECASE,
)
_CORRECTION_PATTERNS = re.compile(
    r"^(na verdade|actually|mas eu quis|quero dizer|não era isso|"
    r"correto seria|na real)\b",
    re.IGNORECASE,
)

# Indicadores de complexidade / ação (verbos que implicam artefatos ou mudanças)
_CREATION_VERBS = re.compile(
    r"\b(cri[ae]r?|ger[ae]r?|implement[ae]r?|fa[çz][ae]r?|"
    r"constru[ai]r?|planej[ae]r?|analis[ae]r?|"
    r"integr[ae]r?|deploy|build|create|implement|"
    r"delet[ae]r?|reorganiz[ae]r?|refator[ae]r?|"
    r"migr[ae]r?|configur[ae]r?|otimiz[ae]r?|"
    r"adicion[ae]r?|remov[ae]r?|inici[ae]r?|"
    r"conect[ae]r?|automatiz[ae]r?|"
    r"continu[ae]r?|refin[ae]r?|expan[de]ir?|melhor[ae]r?|"
    r"refaz|refaç[ae]r?|aprimor[ae]r?|ajust[ae]r?|corrig[aei]r?)\b",
    re.IGNORECASE,
)
_ACTION_INTENT = re.compile(
    r"\b(quero|preciso|necessito|gostaria|vamos|bora|"
    r"me ajuda|ajude|ajuda)\b",
    re.IGNORECASE,
)


def classify_request(
    request: str,
    *,
    word_count: int | None = None,
    llm_client: Any = None,
) -> RequestComplexity:
    """Classifica complexidade em 3 níveis: conversational, intermediate, complex.

    - conversational: saudações, despedidas, follow-ups triviais → fast_path
    - intermediate: perguntas, explicações, requests curtos → medium_path (retrieval+LLM)
    - complex: criação de artefatos, multi-step → pipeline completo
    """
    text = " ".join(request.strip().split())
    if not text:
        return RequestComplexity("conversational", "empty_request", skip_full_pipeline=True)

    words = word_count or len(text.split())

    # === CONVERSATIONAL: bypass total ===
    if _GREETING_PATTERNS.match(text):
        return RequestComplexity("conversational", "greeting", skip_full_pipeline=True)
    if _CLOSING_PATTERNS.match(text):
        return RequestComplexity("conversational", "closing", skip_full_pipeline=True)
    if _CORRECTION_PATTERNS.match(text):
        return RequestComplexity(
            "conversational", "correction", skip_full_pipeline=True, use_retrieval=True
        )
    if _FOLLOWUP_PATTERNS.match(text) and words <= 8:
        return RequestComplexity(
            "conversational", "followup", skip_full_pipeline=True, use_retrieval=True
        )

    # === INTERMEDIATE: retrieval + 1 LLM call ===
    if _SIMPLE_QUESTION.match(text):
        tier = "expert" if words > 12 else "fast"
        return RequestComplexity(
            "intermediate",
            "simple_question",
            skip_full_pipeline=True,
            use_retrieval=True,
            suggested_tier=tier,
        )
    if words <= 15 and not _CREATION_VERBS.search(text) and not _ACTION_INTENT.search(text):
        return RequestComplexity(
            "intermediate",
            "short_request",
            skip_full_pipeline=True,
            use_retrieval=True,
            suggested_tier="fast",
        )

    # === COMPLEX: pipeline completo ===
    complexity_markers = 0
    lowered = text.lower()
    if _CREATION_VERBS.search(text):
        complexity_markers += 1
    if _ACTION_INTENT.search(text):
        complexity_markers += 1
    if " e " in lowered and (_CREATION_VERBS.search(text) or _ACTION_INTENT.search(text)):
        complexity_markers += 1
    if len(re.findall(r"\b(depois|então|em seguida|além disso)\b", lowered)):
        complexity_markers += 1
    if words > 30:
        complexity_markers += 1
    if lowered.count(",") >= 3:
        complexity_markers += 1

    if complexity_markers >= 2:
        return RequestComplexity(
            "complex",
            "multi_objective_request",
            skip_full_pipeline=False,
            use_retrieval=True,
            suggested_tier="expert",
        )

    # === LLM classify: micro-call para zona ambígua (não-trivial, não-complex) ===
    if llm_client and getattr(llm_client, "is_configured", False):
        llm_result = _classify_with_llm(llm_client, text)
        if llm_result is not None:
            return llm_result

    # Zona ambígua sem LLM: tratamos como complex (pipeline completo, conservador)
    return RequestComplexity(
        "complex",
        "ambiguous_request",
        skip_full_pipeline=False,
        use_retrieval=True,
        suggested_tier="expert",
    )


def _classify_with_llm(llm_client: Any, text: str) -> RequestComplexity | None:
    """Micro-call LLM para classificar complexidade (~200ms, 10 tokens max)."""
    messages = [
        {
            "role": "system",
            "content": (
                "Classifique a complexidade do input do usuário. "
                "Responda APENAS com uma palavra: 'simple' ou 'complex'.\n"
                "'simple' = pergunta, conversa, explicação, dúvida.\n"
                "'complex' = criação de artefatos, plano multi-step, implementação."
            ),
        },
        {"role": "user", "content": text[:300]},
    ]
    try:
        resp = llm_client.chat(tier="fast", messages=messages, max_tokens=10)
        answer = resp.content.strip().lower()
        logger.debug("llm classify: '%s' -> '%s'", text[:50], answer)
        if "complex" in answer:
            return RequestComplexity(
                "complex",
                "llm_classified_complex",
                skip_full_pipeline=False,
                use_retrieval=True,
                suggested_tier="expert",
            )
        # Tudo que não é 'complex' vai para medium (retrieval + 1 LLM call)
        return RequestComplexity(
            "intermediate",
            "llm_classified_simple",
            skip_full_pipeline=True,
            use_retrieval=True,
            suggested_tier="fast",
        )
    except Exception as exc:
        logger.debug("llm classify indisponível: %s", exc)
        return None  # caller trata como complex
