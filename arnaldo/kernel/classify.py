"""Classificação de complexidade de requests — LLM + graph, sem regex.

Delega detecção semântica ao ``intent_signals`` (LLM ou graph TF-IDF).
Mantém a interface ``RequestComplexity`` para compatibilidade.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .intent_signals import IntentSignals, detect_signals
from .execution_profile import select_execution_profile

logger = logging.getLogger("arnaldo.kernel")


class RequestComplexity:
    """Resultado da classificação de complexidade."""

    __slots__ = (
        "level",
        "reason",
        "skip_full_pipeline",
        "use_retrieval",
        "suggested_tier",
        "needs_external_data",
        "capability_needs",
        "execution_profile",
        "execution_capability_ids",
    )

    def __init__(
        self,
        level: str,
        reason: str,
        *,
        skip_full_pipeline: bool = False,
        use_retrieval: bool = False,
        suggested_tier: str = "fast",
        needs_external_data: bool = False,
        capability_needs: list[str] | None = None,
        execution_profile: str = "full_pipeline",
        execution_capability_ids: list[str] | None = None,
    ) -> None:
        self.level = level
        self.reason = reason
        self.skip_full_pipeline = skip_full_pipeline
        self.use_retrieval = use_retrieval
        self.suggested_tier = suggested_tier
        self.needs_external_data = needs_external_data
        self.capability_needs = capability_needs or []
        self.execution_profile = execution_profile
        self.execution_capability_ids = execution_capability_ids or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "reason": self.reason,
            "skip_full_pipeline": self.skip_full_pipeline,
            "use_retrieval": self.use_retrieval,
            "suggested_tier": self.suggested_tier,
            "needs_external_data": self.needs_external_data,
            "capability_needs": self.capability_needs,
            "execution_profile": self.execution_profile,
            "execution_capability_ids": self.execution_capability_ids,
        }


def classify_request(
    request: str,
    *,
    graph: Any = None,
    llm_client: Any = None,
    word_count: int | None = None,
) -> RequestComplexity:
    """Classifica complexidade via LLM (primário) ou graph TF-IDF (secundário).

    Sem regex. Sem len(). Sem vocabulários hardcoded.
    O LLM entende semântica. O grafo aprende com uso.
    Sem nenhum dos dois → conservador: pipeline completo.
    """
    signals = detect_signals(request, graph=graph, llm_client=llm_client)
    return _signals_to_complexity(signals)


def _signals_to_complexity(signals: IntentSignals) -> RequestComplexity:
    """Converte IntentSignals para RequestComplexity (interface legada)."""
    profile = select_execution_profile(
        level=signals.complexity,
        needs_external_data=signals.needs_external_data,
        capability_ids=signals.capability_needs,
    )
    use_retrieval = signals.complexity != "conversational" or profile.name == "inline_capability"

    return RequestComplexity(
        signals.complexity,
        f"{signals.source}_classified",
        skip_full_pipeline=profile.skip_full_pipeline,
        use_retrieval=use_retrieval,
        suggested_tier=signals.suggested_tier,
        needs_external_data=signals.needs_external_data,
        capability_needs=signals.capability_needs,
        execution_profile=profile.name,
        execution_capability_ids=list(profile.inline_capability_ids),
    )
