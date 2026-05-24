"""Helpers do kernel — funções extraídas para manter kernel.py ≤ 300 linhas."""

from __future__ import annotations

import os
from typing import Any

from arnaldo.components import OrganizationGenerator
from arnaldo.contracts import CognitiveDecision, OrganizationIR, TaskIR
from arnaldo.graph.brain import BrainDecision
from arnaldo.proactivity import ProactivityManager
from arnaldo.runtime import GraphRuntime, LocalRuntime, MultiAgentRuntime, RuntimeAdapter

from . import organization as _org
from .classify import RequestComplexity


def resolve_runtime(
    mode_override: str | None,
    llm_client: Any,
) -> RuntimeAdapter:
    """Resolve o runtime baseado no modo configurado."""
    mode = (mode_override or os.environ.get("ARNALDO_RUNTIME_MODE", "graph")).strip().lower()
    if mode == "graph":
        return GraphRuntime(llm_client=llm_client)
    if mode == "multiagent":
        return MultiAgentRuntime()
    return LocalRuntime()


def decision_to_complexity(decision: BrainDecision) -> RequestComplexity:
    """Converte BrainDecision para RequestComplexity (interface legada)."""
    # GAP 3: needs_external_data cancela skip — dados externos exigem pipeline
    skip = decision.skip_full_pipeline and not decision.needs_external_data
    return RequestComplexity(
        decision.complexity,
        f"brain_activated:{decision.primary_synapse or 'none'}",
        skip_full_pipeline=skip,
        use_retrieval=decision.complexity != "conversational",
        suggested_tier=decision.tier,
        needs_external_data=decision.needs_external_data,
        capability_needs=decision.capability_needs,
    )


def pop_due_proactive_messages(
    proactivity: ProactivityManager, session_id: str, *, limit: int = 3,
) -> list[str]:
    """Return due proactive messages for the given session."""
    due = proactivity.pop_due(session_id=session_id, limit=limit)
    return [
        str(item.get("message", "")).strip()
        for item in due
        if str(item.get("message", "")).strip()
    ]


def pending_proactive_count(
    proactivity: ProactivityManager, session_id: str,
) -> int:
    """Return count of pending proactive items for the session."""
    return proactivity.pending_count(session_id=session_id)


def build_runtime_organization(
    runtime: RuntimeAdapter,
    organizations: OrganizationGenerator,
    task: TaskIR,
    decision: CognitiveDecision,
    capability_resolution: dict[str, Any],
) -> OrganizationIR:
    """Build organization IR based on runtime type."""
    if isinstance(runtime, GraphRuntime):
        return _org.build_graph_native_organization(task, decision, capability_resolution)
    return organizations.generate(task, decision, capability_resolution)
