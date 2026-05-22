"""Classificação de complexidade de requests — LLM + graph, sem regex.

Delega detecção semântica ao ``intent_signals`` (LLM ou graph TF-IDF).
Mantém a interface ``RequestComplexity`` para compatibilidade.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .intent_signals import IntentSignals, detect_signals

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
    ) -> None:
        self.level = level
        self.reason = reason
        self.skip_full_pipeline = skip_full_pipeline
        self.use_retrieval = use_retrieval
        self.suggested_tier = suggested_tier
        self.needs_external_data = needs_external_data
        self.capability_needs = capability_needs or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "reason": self.reason,
            "skip_full_pipeline": self.skip_full_pipeline,
            "use_retrieval": self.use_retrieval,
            "suggested_tier": self.suggested_tier,
            "needs_external_data": self.needs_external_data,
            "capability_needs": self.capability_needs,
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
    use_retrieval = signals.complexity != "conversational"

    # Se precisa de dado externo → NUNCA atalhar
    if signals.needs_external_data:
        return RequestComplexity(
            "complex",
            "needs_external_data",
            skip_full_pipeline=False,
            use_retrieval=True,
            suggested_tier="expert",
            needs_external_data=True,
            capability_needs=signals.capability_needs,
        )

    return RequestComplexity(
        signals.complexity,
        f"{signals.source}_classified",
        skip_full_pipeline=signals.skip_full_pipeline,
        use_retrieval=use_retrieval,
        suggested_tier=signals.suggested_tier,
        needs_external_data=False,
        capability_needs=signals.capability_needs,
    )
