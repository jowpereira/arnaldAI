"""Classificação de intenção via LLM structured output (chat_typed)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
import re
from typing import Any

from .intent_signals import IntentSignals
from .execution_profile import select_execution_profile

logger = logging.getLogger("arnaldo.kernel")

_SYSTEM_PROMPT = (
    "Classifique o pedido do usuário.\n\n"
    "Regras:\n"
    "- needs_external_data: true se precisa de dado externo, atual, de API, "
    "web ou terceiros (cotação, preço, clima, notícia, status de serviço)\n"
    "- conversational: saudação, despedida, confirmação, follow-up trivial\n"
    "- intermediate: pergunta conceitual, explicação, dúvida teórica, lookup "
    "pontual com capability read-only ou descoberta local read-only simples "
    "(ex: ls/dir/where, listar pasta, localizar arquivo)\n"
    "- complex: criação de artefato, análise com dados, multi-step, "
    "tooling local com várias etapas, integração, mutação ou workflow\n"
    "- capability_needs: prefira IDs concretos quando forem óbvios: "
    "search.public_web para busca pública/current data, connector.http.generic "
    "para HTTP/API explícita, filesystem.local.search para descoberta local, "
    "shell.local.readonly para shell read-only. Use famílias abstratas "
    "search.*, connector.* ou tool.* só quando o executor preciso for desconhecido.\n"
    "- Nao infira filesystem.local.search ou shell.local.readonly em pedidos "
    "abstratos sobre analise, opções, hipóteses ou próximos passos sem menção "
    "explícita a pasta, arquivo, diretório, caminho, terminal, shell ou comando.\n"
    "- Needs_external_data por si só não implica complex. Lookup read-only simples "
    "costuma ser intermediate."
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

    capability_needs = _sanitize_capability_ids(resp.capability_needs)
    profile = select_execution_profile(
        level=complexity,
        needs_external_data=needs_external,
        capability_ids=capability_needs,
    )
    skip = profile.skip_full_pipeline
    tier = "expert" if profile.name == "full_pipeline" else "fast"

    return IntentSignals(
        needs_external_data=needs_external,
        complexity=complexity,
        capability_needs=capability_needs,
        skip_full_pipeline=skip,
        suggested_tier=tier,
        confidence=0.85,
        source="llm",
        detail={"reasoning": resp.reasoning, "execution_profile": profile.name},
    )


def _sanitize_capability_ids(raw_ids: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in raw_ids:
        current = str(raw or "").strip().lower()
        if not current or current in seen:
            continue
        if not re.match(r"^[a-z0-9_]+(?:\.(?:[a-z0-9_]+|\*))+?$", current):
            continue
        seen.add(current)
        cleaned.append(current)
    return cleaned
