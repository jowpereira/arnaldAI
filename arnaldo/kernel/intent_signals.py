"""Detecção de sinais de intenção — LLM + graph TF-IDF, zero hardcoded.

Arquitetura em 3 camadas:
1. LLM structured output — entende semântica nativamente
2. Graph TF-IDF — classifica contra nós do próprio grafo (aprende com uso)
3. Conservador — sem inteligência disponível, nunca atalha

Nenhuma lista de vocabulário. O grafo É o vocabulário.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from arnaldo.graph.text_similarity import node_searchable_text, tfidf_rank

logger = logging.getLogger("arnaldo.kernel")

# Prefixos que indicam capabilities de dados externos
_EXTERNAL_CAPABILITY_PREFIXES = ("search.", "connector.")


@dataclass(slots=True, frozen=True)
class IntentSignals:
    """Sinais multi-dimensionais detectados do request."""

    needs_external_data: bool
    complexity: str  # "conversational" | "intermediate" | "complex"
    capability_needs: list[str]
    skip_full_pipeline: bool
    suggested_tier: str
    confidence: float
    source: str  # "llm" | "graph" | "conservative"
    detail: dict[str, Any] = field(default_factory=dict)


def detect_signals(
    request: str,
    *,
    graph: Any | None = None,
    llm_client: Any | None = None,
) -> IntentSignals:
    """Detecta sinais de intenção sem nenhum vocabulário hardcoded.

    Camada 1 — LLM: entendimento semântico real.
    Camada 2 — Graph TF-IDF: classifica contra nós do grafo (aprendido).
    Camada 3 — Conservador: sem inteligência, nunca atalha.
    """
    text = " ".join(request.strip().split())
    if not text:
        return IntentSignals(
            needs_external_data=False,
            complexity="conversational",
            capability_needs=[],
            skip_full_pipeline=True,
            suggested_tier="fast",
            confidence=1.0,
            source="structural",
            detail={"reason": "empty_input"},
        )

    # Camada 1: LLM — entendimento semântico real
    if llm_client and getattr(llm_client, "is_configured", False):
        result = _classify_with_llm(text, llm_client)
        if result is not None:
            return result

    # Camada 2: Graph TF-IDF — classificação aprendida
    if graph is not None:
        result = _classify_with_graph(text, graph)
        if result is not None:
            return result

    # Camada 3: sem LLM nem grafo → heurística estrutural mínima
    words = text.split()
    if len(words) <= 3:
        # Frases muito curtas sem contexto → provavelmente conversacional
        return IntentSignals(
            needs_external_data=False,
            complexity="conversational",
            capability_needs=[],
            skip_full_pipeline=True,
            suggested_tier="fast",
            confidence=0.4,
            source="structural",
            detail={"reason": "short_no_context", "word_count": len(words)},
        )

    # Camada 4: conservador puro — pipeline completo
    return IntentSignals(
        needs_external_data=False,
        complexity="complex",
        capability_needs=[],
        skip_full_pipeline=False,
        suggested_tier="expert",
        confidence=0.2,
        source="conservative",
        detail={"reason": "no_llm_no_graph"},
    )


# ── Camada 1: LLM ────────────────────────────────────────────────────────


def _classify_with_llm(text: str, llm_client: Any) -> IntentSignals | None:
    """Classificação semântica via LLM — delega ao módulo especializado."""
    from .intent_signals_llm import llm_classify

    return llm_classify(text, llm_client)


# ── Camada 2: Graph TF-IDF ───────────────────────────────────────────────


def _classify_with_graph(text: str, graph: Any) -> IntentSignals | None:
    """Classificação via TF-IDF contra nós do grafo cognitivo.

    O grafo É o vocabulário. CapabilityNodes detectam necessidade
    de ferramentas, SynapseNodes detectam tipo de tarefa.
    """
    from arnaldo.graph.nodes import NodeKind

    docs: list[tuple[str, str]] = []
    capability_map: dict[str, str] = {}  # doc_id → capability_id
    synapse_roles: dict[str, str] = {}  # doc_id → role

    for node in graph.iter_nodes(kind=NodeKind.CAPABILITY, active_only=False):
        doc_id = f"cap:{node.id}"
        searchable = node_searchable_text(node)
        if searchable.strip():
            docs.append((doc_id, searchable))
            cap_id = str(node.payload.get("capability_id") or node.label)
            capability_map[doc_id] = cap_id

    for node in graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=True):
        doc_id = f"syn:{node.id}"
        searchable = node_searchable_text(node)
        if searchable.strip():
            docs.append((doc_id, searchable))
            synapse_roles[doc_id] = str(node.payload.get("role", ""))

    if not docs:
        return None

    matches = tfidf_rank(text, docs, min_score=0.01)
    if not matches:
        return _graph_no_match_result(text, len(docs))

    # Extrai capabilities necessárias dos matches
    capability_needs: list[str] = []
    matched_roles: list[str] = []
    top_score = matches[0][1]

    for doc_id, score in matches[:8]:
        if doc_id in capability_map:
            cap_id = capability_map[doc_id]
            if cap_id not in capability_needs:
                capability_needs.append(cap_id)
        if doc_id in synapse_roles:
            matched_roles.append(synapse_roles[doc_id])

    needs_external = any(cap.startswith(_EXTERNAL_CAPABILITY_PREFIXES) for cap in capability_needs)

    complexity = _infer_complexity_from_matches(
        matched_roles=matched_roles,
        needs_external=needs_external,
        top_score=top_score,
        word_count=len(text.split()),
    )

    skip = complexity in ("conversational", "intermediate") and not needs_external
    tier = "fast" if complexity != "complex" else "expert"

    return IntentSignals(
        needs_external_data=needs_external,
        complexity=complexity,
        capability_needs=capability_needs,
        skip_full_pipeline=skip,
        suggested_tier=tier,
        confidence=min(0.7, top_score + 0.2),
        source="graph",
        detail={
            "top_matches": [(did, round(s, 3)) for did, s in matches[:5]],
            "matched_roles": matched_roles[:5],
        },
    )


def _infer_complexity_from_matches(
    *,
    matched_roles: list[str],
    needs_external: bool,
    top_score: float,
    word_count: int,
) -> str:
    """Infere complexidade a partir dos matches do grafo."""
    if needs_external:
        return "complex"

    # Roles que indicam tarefas complexas (do bootstrap: planner, analyst, creator)
    complex_roles = {"planner", "creator", "debugger", "analyst"}
    simple_roles = {"responder"}

    matched_set = set(matched_roles[:3])

    if matched_set & complex_roles and top_score > 0.1:
        return "complex"

    if matched_set <= simple_roles and word_count <= 10 and top_score > 0.05:
        return "intermediate"

    if top_score < 0.03 and word_count <= 4:
        return "conversational"

    # Ambíguo → conservador: pipeline completo
    return "complex"


def _graph_no_match_result(text: str, corpus_size: int) -> IntentSignals:
    """Quando TF-IDF não encontra match → conservador."""
    word_count = len(text.split())
    if word_count <= 2:
        return IntentSignals(
            needs_external_data=False,
            complexity="conversational",
            capability_needs=[],
            skip_full_pipeline=True,
            suggested_tier="fast",
            confidence=0.3,
            source="graph",
            detail={"reason": "no_tfidf_match_short_input", "corpus_size": corpus_size},
        )
    return IntentSignals(
        needs_external_data=False,
        complexity="complex",
        capability_needs=[],
        skip_full_pipeline=False,
        suggested_tier="expert",
        confidence=0.25,
        source="graph",
        detail={"reason": "no_tfidf_match", "corpus_size": corpus_size},
    )
