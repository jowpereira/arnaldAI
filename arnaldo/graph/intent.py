"""Classificação heurística de intenção — intent detection para routing."""

from __future__ import annotations

from .edges import EdgeKind

INTENT_TO_EDGES: dict[str, tuple[EdgeKind, ...]] = {
    "why": (EdgeKind.CAUSAL, EdgeKind.DERIVED_FROM),
    "when": (EdgeKind.TEMPORAL_BEFORE,),
    "what": (EdgeKind.IS_A, EdgeKind.PART_OF, EdgeKind.MENTIONS),
    "who": (EdgeKind.MENTIONS,),
    "how": (EdgeKind.ACTIVATES, EdgeKind.REQUIRES, EdgeKind.DERIVED_FROM),
    "code": (EdgeKind.ACTIVATES, EdgeKind.REQUIRES, EdgeKind.DERIVED_FROM),
    "debug": (EdgeKind.CAUSAL, EdgeKind.ACTIVATES, EdgeKind.REQUIRES),
    "explain": (EdgeKind.IS_A, EdgeKind.PART_OF, EdgeKind.SEMANTIC),
    "compare": (EdgeKind.SEMANTIC, EdgeKind.IS_A),
    "plan": (EdgeKind.ACTIVATES, EdgeKind.REQUIRES, EdgeKind.PART_OF),
    "review": (EdgeKind.CAUSAL, EdgeKind.SEMANTIC, EdgeKind.DERIVED_FROM),
    "summary": (EdgeKind.PART_OF, EdgeKind.IS_A),
    "default": (EdgeKind.SEMANTIC,),
}


def classify_intent(query: str) -> str:
    """Classificador heurístico — palavras-chave em pt/en."""
    q = query.lower()
    if any(w in q for w in ["por que", "porque", "why", "razão"]):
        return "why"
    if any(w in q for w in ["quando", "when", "data"]):
        return "when"
    if any(w in q for w in ["quem", "who"]):
        return "who"
    if any(w in q for w in ["como", "how", "passo"]):
        return "how"
    if any(w in q for w in ["o que é", "what is", "definição"]):
        return "what"
    if any(w in q for w in ["código", "code", "implementa", "programa", "script", "function"]):
        return "code"
    if any(w in q for w in ["bug", "erro", "debug", "fix", "corrig", "falha", "crash"]):
        return "debug"
    if any(w in q for w in ["explica", "explain", "detalha", "elabora"]):
        return "explain"
    if any(w in q for w in ["compar", "diferença", "versus", "vs", "compare"]):
        return "compare"
    if any(w in q for w in ["plano", "plan", "estratégia", "roadmap", "planej"]):
        return "plan"
    if any(w in q for w in ["revis", "review", "analisa", "avalia"]):
        return "review"
    if any(w in q for w in ["resumo", "summary", "panorama"]):
        return "summary"
    return "default"
