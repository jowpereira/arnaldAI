"""Classificação de intenção via LLM structured output (chat_typed)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .intent_signals import IntentSignals

logger = logging.getLogger("arnaldo.kernel")

_SYSTEM_PROMPT = (
    "Classifique o pedido do usuário.\n\n"
    "Regras:\n"
    "- needs_external_data: true se precisa de dado externo, atual, de API, "
    "web ou terceiros (cotação, preço, clima, notícia, status de serviço)\n"
    "- conversational: saudação, despedida, confirmação, follow-up trivial\n"
    "- intermediate: pergunta conceitual, explicação, dúvida teórica\n"
    "- complex: criação de artefato, análise com dados, multi-step, "
    "qualquer coisa que precise de ferramenta ou dado externo\n"
    "- capability_needs: use search.* para busca web, connector.* para APIs, "
    "tool.* para ferramentas. Lista vazia se não precisa.\n"
    "- Se needs_external_data=true, complexity DEVE ser 'complex'."
)


@dataclass
class _ClassifyResponse:
    """Schema para structured output do LLM."""

    needs_external_data: bool = False
    complexity: str = "complex"
    capability_needs: list[str] = field(default_factory=list)
    reasoning: str = ""


def llm_classify(text: str, llm_client: Any) -> IntentSignals | None:
    """Classificação semântica via LLM structured output (chat_typed)."""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": text[:500]},
    ]
    try:
        typed_resp = llm_client.chat_typed(
            tier="fast",
            messages=messages,
            response_model=_ClassifyResponse,
            max_tokens=200,
            max_retries=1,
        )
    except Exception as exc:
        logger.debug("llm classify falhou: %s", exc)
        return None

    if not typed_resp.is_success or typed_resp.parsed is None:
        logger.debug("llm classify: refusal=%s", typed_resp.refusal)
        return None

    return _to_signals(typed_resp.parsed)


def _to_signals(resp: _ClassifyResponse) -> IntentSignals:
    """Converte response tipado em IntentSignals."""
    needs_external = resp.needs_external_data
    complexity = resp.complexity.strip().lower()
    if complexity not in ("conversational", "intermediate", "complex"):
        complexity = "complex"
    if needs_external and complexity != "complex":
        complexity = "complex"

    capability_needs = [c.strip() for c in resp.capability_needs if c.strip()]
    skip = complexity in ("conversational", "intermediate") and not needs_external
    tier = "fast" if complexity != "complex" else "expert"

    return IntentSignals(
        needs_external_data=needs_external,
        complexity=complexity,
        capability_needs=capability_needs,
        skip_full_pipeline=skip,
        suggested_tier=tier,
        confidence=0.85,
        source="llm",
        detail={"reasoning": resp.reasoning},
    )
