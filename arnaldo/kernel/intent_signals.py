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
import re
from typing import Any

from arnaldo.constants.discovery_terms import (
    FILESYSTEM_DISCOVERY_VERBS,
    LOCAL_CONTEXT_NOUNS,
    READONLY_SHELL_COMMAND_HINTS,
    SHELL_CONTEXT_NOUNS,
    SHELL_EXECUTION_VERBS,
)
from arnaldo.graph.text_similarity import node_searchable_text, tfidf_rank

from .execution_profile import select_execution_profile

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
            return _normalize_local_readonly_signals(text, result)

    # Camada 2: Graph TF-IDF — classificação aprendida
    if graph is not None:
        result = _classify_with_graph(text, graph)
        if result is not None:
            return _normalize_local_readonly_signals(text, result)

    # Camada 3: sem LLM nem grafo → heurística estrutural mínima
    words = text.split()
    if len(words) <= 3:
        # Frases muito curtas sem contexto → provavelmente conversacional
        return _normalize_local_readonly_signals(
            text,
            IntentSignals(
                needs_external_data=False,
                complexity="conversational",
                capability_needs=[],
                skip_full_pipeline=True,
                suggested_tier="fast",
                confidence=0.4,
                source="structural",
                detail={"reason": "short_no_context", "word_count": len(words)},
            ),
        )

    # Camada 4: conservador puro — pipeline completo
    return _normalize_local_readonly_signals(
        text,
        IntentSignals(
            needs_external_data=False,
            complexity="complex",
            capability_needs=[],
            skip_full_pipeline=False,
            suggested_tier="expert",
            confidence=0.2,
            source="conservative",
            detail={"reason": "no_llm_no_graph"},
        ),
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
    # Roles que indicam tarefas complexas (do bootstrap: planner, analyst, creator)
    complex_roles = {"planner", "creator", "debugger", "analyst"}
    simple_roles = {"responder"}

    matched_set = set(matched_roles[:3])

    if needs_external and not (matched_set & complex_roles):
        return "intermediate"

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


_LOCAL_INLINE_CAPABILITIES = frozenset({"filesystem.local.search", "shell.local.readonly"})


def _normalize_local_readonly_signals(text: str, signals: IntentSignals) -> IntentSignals:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return signals

    explicit_shell_command = _contains_readonly_shell_command(lowered)
    shell_execution_hint = explicit_shell_command or _contains_shell_execution_hint(lowered)
    filesystem_discovery_hint = _contains_filesystem_discovery_hint(lowered)
    capability_needs = _dedupe_capability_ids(signals.capability_needs)
    local_hint_present = shell_execution_hint or filesystem_discovery_hint
    removed_spurious_local_caps = False
    if not local_hint_present:
        filtered_capability_needs = [
            capability_id
            for capability_id in capability_needs
            if capability_id not in _LOCAL_INLINE_CAPABILITIES
        ]
        removed_spurious_local_caps = filtered_capability_needs != capability_needs
        capability_needs = filtered_capability_needs

    if not local_hint_present and not removed_spurious_local_caps:
        return signals

    mutated = False

    if explicit_shell_command:
        capability_needs = [
            "shell.local.readonly",
            *[
                capability_id
                for capability_id in capability_needs
                if capability_id not in {"shell.local.readonly", "filesystem.local.search"}
            ],
        ]
        mutated = True
    elif shell_execution_hint and "shell.local.readonly" not in capability_needs:
        capability_needs = ["shell.local.readonly", *capability_needs]
        mutated = True

    if filesystem_discovery_hint and not explicit_shell_command:
        if "filesystem.local.search" not in capability_needs:
            capability_needs.append("filesystem.local.search")
            mutated = True

    only_local_inline_caps = bool(capability_needs) and all(
        capability_id in _LOCAL_INLINE_CAPABILITIES for capability_id in capability_needs
    )
    needs_external_data = False if only_local_inline_caps else signals.needs_external_data
    complexity = signals.complexity
    if only_local_inline_caps and len(lowered.split()) <= 24:
        complexity = "intermediate"

    profile = select_execution_profile(
        level=complexity,
        needs_external_data=needs_external_data,
        capability_ids=capability_needs,
    )
    suggested_tier = "expert" if profile.name == "full_pipeline" else "fast"

    if (
        not mutated
        and complexity == signals.complexity
        and needs_external_data == signals.needs_external_data
        and capability_needs == signals.capability_needs
        and profile.skip_full_pipeline == signals.skip_full_pipeline
        and suggested_tier == signals.suggested_tier
    ):
        return signals

    detail = dict(signals.detail or {})
    if removed_spurious_local_caps:
        detail["spurious_local_capabilities_removed"] = True
    if explicit_shell_command:
        detail["explicit_shell_command"] = True
    elif shell_execution_hint:
        detail["shell_execution_hint"] = True
    if filesystem_discovery_hint:
        detail["filesystem_discovery_hint"] = True
    if only_local_inline_caps:
        detail["execution_profile"] = profile.name

    return IntentSignals(
        needs_external_data=needs_external_data,
        complexity=complexity,
        capability_needs=capability_needs,
        skip_full_pipeline=profile.skip_full_pipeline,
        suggested_tier=suggested_tier,
        confidence=signals.confidence,
        source=signals.source,
        detail=detail,
    )


def _contains_readonly_shell_command(text: str) -> bool:
    return any(
        re.search(rf"(?<![a-z0-9_-]){re.escape(term)}(?![a-z0-9_-])", text)
        for term in READONLY_SHELL_COMMAND_HINTS
    )


def _contains_shell_execution_hint(text: str) -> bool:
    has_shell_context = any(
        re.search(rf"\b{re.escape(term)}\b", text) for term in SHELL_CONTEXT_NOUNS
    )
    if not has_shell_context:
        return False
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in SHELL_EXECUTION_VERBS)


def _contains_filesystem_discovery_hint(text: str) -> bool:
    if any(re.search(rf"\b{re.escape(term)}\b", text) for term in FILESYSTEM_DISCOVERY_VERBS):
        return True
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in LOCAL_CONTEXT_NOUNS)


def _dedupe_capability_ids(capability_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for capability_id in capability_ids:
        current = str(capability_id or "").strip()
        if not current or current in seen:
            continue
        seen.add(current)
        normalized.append(current)
    return normalized
