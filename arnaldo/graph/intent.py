"""Classificação heurística de intenção — intent detection para routing."""

from __future__ import annotations

import re

from .edges import EdgeKind

INTENT_TO_EDGES: dict[str, tuple[EdgeKind, ...]] = {
    "why": (EdgeKind.CAUSAL, EdgeKind.DERIVED_FROM, EdgeKind.CONTRADICTS),
    "when": (EdgeKind.TEMPORAL_BEFORE,),
    "what": (EdgeKind.IS_A, EdgeKind.PART_OF, EdgeKind.MENTIONS),
    "who": (EdgeKind.MENTIONS,),
    "how": (EdgeKind.ACTIVATES, EdgeKind.RECALLS, EdgeKind.REQUIRES, EdgeKind.DERIVED_FROM),
    "code": (EdgeKind.ACTIVATES, EdgeKind.RECALLS, EdgeKind.REQUIRES, EdgeKind.DERIVED_FROM),
    "debug": (EdgeKind.CAUSAL, EdgeKind.ACTIVATES, EdgeKind.RECALLS, EdgeKind.REQUIRES),
    "explain": (EdgeKind.IS_A, EdgeKind.PART_OF, EdgeKind.SEMANTIC, EdgeKind.INFORMS),
    "compare": (EdgeKind.SEMANTIC, EdgeKind.IS_A, EdgeKind.CONTRADICTS),
    "plan": (EdgeKind.ACTIVATES, EdgeKind.RECALLS, EdgeKind.REQUIRES, EdgeKind.PART_OF),
    "review": (
        EdgeKind.CAUSAL,
        EdgeKind.SEMANTIC,
        EdgeKind.INFORMS,
        EdgeKind.DERIVED_FROM,
        EdgeKind.SUPERSEDES,
    ),
    "summary": (EdgeKind.PART_OF, EdgeKind.IS_A),
    "default": (EdgeKind.SEMANTIC, EdgeKind.INFORMS),
}

# Pre-compiled patterns com word boundaries — G11
_INTENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "why": re.compile(r"\b(por que|porque|why|razão)\b", re.IGNORECASE),
    "when": re.compile(r"\b(quando|when)\b", re.IGNORECASE),
    "who": re.compile(r"\b(quem|who)\b", re.IGNORECASE),
    "how": re.compile(r"\b(como|how|passo)\b", re.IGNORECASE),
    "what": re.compile(r"\b(o que é|what is|definição)\b", re.IGNORECASE),
    "code": re.compile(r"\b(código|code|implementa|programa|script|function)\b", re.IGNORECASE),
    "debug": re.compile(r"\b(bug|erro|debug|fix|corri[gj]\w*|falha|crash)\b", re.IGNORECASE),
    "explain": re.compile(r"\b(explica\w*|explain|detalha|elabora)\b", re.IGNORECASE),
    "compare": re.compile(r"\b(compar\w*|diferença|versus|vs|compare)\b", re.IGNORECASE),
    "plan": re.compile(r"\b(plano|plan|estratégia|roadmap|planej\w*)\b", re.IGNORECASE),
    "review": re.compile(r"\b(revis\w*|review|avalia\w*)\b", re.IGNORECASE),
    "summary": re.compile(r"\b(resumo|summary|panorama)\b", re.IGNORECASE),
}


def classify_intent(query: str) -> str:
    """Classificador heurístico — regex com word boundaries em pt/en."""
    q = query.lower()
    for intent, pattern in _INTENT_PATTERNS.items():
        if pattern.search(q):
            return intent
    return "default"
