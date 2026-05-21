"""Organização, topologia e policy do runtime."""

from __future__ import annotations

from typing import Any, Dict

from arnaldo.contracts import (
    CognitiveDecision,
    OrganizationIR,
    PolicyDecision,
    TaskIR,
    new_id,
    utc_now,
)
from arnaldo.runtime import GraphRuntime, RuntimeAdapter
from arnaldo.session import SessionManager, SessionState

from . import agents as _agents


def select_runtime_topology(decision: CognitiveDecision) -> str:
    """Seleciona topologia de runtime a partir da decisão cognitiva."""
    selected = set(decision.selected_modes)
    if "parallel_exploration" in selected:
        return "parallel_with_synthesis"
    if "adversarial_review" in selected:
        return "pipeline_with_critic"
    return "minimal_pipeline"


def build_graph_native_organization(
    task: TaskIR,
    decision: CognitiveDecision,
    capability_resolution: Dict[str, Any],
) -> OrganizationIR:
    """Constrói OrganizationIR para runtime graph-native."""
    topology = select_runtime_topology(decision)
    agents = _agents.build_graph_native_agents(topology, task, capability_resolution)
    required_capabilities = sorted(
        {
            str(item.get("id", "")).strip()
            for item in task.capability_needs
            if str(item.get("id", "")).strip()
        }
        | {
            str(item.get("id", "")).strip()
            for bucket in ("available", "missing", "degraded")
            for item in (capability_resolution.get(bucket, []) or [])
            if str(item.get("id", "")).strip()
        }
    )
    return OrganizationIR(
        version="organization-ir/v0",
        id=new_id("org"),
        created_at=utc_now(),
        task_id=task.id,
        topology=topology,
        agents=agents,
        workflow=[],
        required_capabilities=required_capabilities,
        human_checkpoints=_agents.build_graph_native_checkpoints(decision, capability_resolution),
    )


def evaluate_runtime_policy(
    runtime: RuntimeAdapter,
    policy_engine: Any,
    sessions: SessionManager,
    task: TaskIR,
    organization: OrganizationIR,
    session: SessionState,
) -> PolicyDecision:
    """Avalia policy de runtime considerando o tipo de runtime."""
    if isinstance(runtime, GraphRuntime):
        return build_graph_runtime_policy(sessions, task, organization, session)
    return policy_engine.evaluate(task, organization, session=sessions.snapshot(session))


def build_graph_runtime_policy(
    sessions: SessionManager,
    task: TaskIR,
    organization: OrganizationIR,
    session: SessionState,
) -> PolicyDecision:
    """Constrói policy permissiva para graph runtime."""
    snapshot = sessions.snapshot(session)
    return PolicyDecision(
        version="policy-decision/v0",
        id=new_id("policy"),
        task_id=task.id,
        organization_id=organization.id,
        allowed=True,
        approval_required=False,
        reasons=["graph_runtime_governance_disabled"],
        constraints={
            "network": "read_write",
            "filesystem": "workspace_write",
            "external_messages": "allowed",
            "spend_money": "blocked_unless_budget_defined",
            "unsafe_actions": "blocked",
        },
        escalation_plan={
            "contact": "human_on_demand",
            "channels": ["cli"],
            "timeout_minutes": 240,
        },
        notes=["governance bypass ativo no modo graph"],
        telemetry={
            "runtime_mode": "graph",
            "governance_enabled": False,
            "session_id": snapshot.get("id", ""),
            "terms_accepted": bool(snapshot.get("terms_accepted", False)),
        },
    )
