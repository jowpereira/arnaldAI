"""Construção de agentes graph-native."""

from __future__ import annotations

import re
from typing import Any, Dict

from arnaldo.contracts import AgentGenome, CognitiveDecision, TaskIR, new_id
from arnaldo.utils.normalize import normalize_module_path as _normalize_module_path


def _graph_agent(agent_id: str, role: str, objective: str) -> AgentGenome:
    return AgentGenome(
        id=agent_id,
        species="graph_native_worker",
        role=role,
        objective=objective,
        epistemic_style="evidence_first",
        required_capabilities=[],
        forbidden_capabilities=[],
        output_contract={
            "schema": "generic_step_output",
            "required_sections": ["status", "evidence", "uncertainties"],
        },
        validation={
            "require_uncertainty_marking": True,
            "require_evidence_record": True,
        },
        lifecycle={
            "max_iterations": 1,
            "expires_after_task": False,
        },
    )


def _has_graph_agent(agents: list[AgentGenome], agent_id: str) -> bool:
    return any(agent.id == agent_id for agent in agents)


def _toolsmith_agent_for_capability(capability_id: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", capability_id.strip().lower().replace(".", "_"))
    slug = re.sub(r"_+", "_", slug).strip("_")
    return "toolsmith_%s" % (slug or "x")


def _toolrunner_agent_for_capability(capability_id: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", capability_id.strip().lower().replace(".", "_"))
    slug = re.sub(r"_+", "_", slug).strip("_")
    return "toolrunner_%s" % (slug or "x")


def _capability_module_path(payload: Dict[str, Any]) -> str:
    direct = _normalize_module_path(payload.get("module_path"))
    if direct:
        return direct
    policies = payload.get("policies") or {}
    if isinstance(policies, dict):
        return _normalize_module_path(policies.get("module_path"))
    return ""


def build_graph_native_agents(
    topology: str,
    task: TaskIR,
    capability_resolution: Dict[str, Any],
) -> list[AgentGenome]:
    """Constrói lista de agentes graph-native para a topologia."""
    if topology == "parallel_with_synthesis":
        agents = [
            _graph_agent("framer", "operator", "enquadrar objetivo e critérios executáveis"),
            _graph_agent("explorer_a", "explorer", "explorar alternativa A de execução"),
            _graph_agent("explorer_b", "explorer", "explorar alternativa B de execução"),
            _graph_agent("synthesizer", "synthesizer", "sintetizar alternativas em artefato único"),
            _graph_agent("critic", "critic", "revisar lacunas e consistência do plano"),
        ]
    elif topology == "pipeline_with_critic":
        agents = [
            _graph_agent("framer", "operator", "enquadrar objetivo e restrições"),
            _graph_agent("planner", "operator", "decompor e estruturar execução"),
            _graph_agent("critic", "critic", "revisar riscos e inconsistências"),
        ]
    else:
        agents = [
            _graph_agent("operator", "operator", "executar pipeline mínimo orientado a objetivo"),
        ]

    if len(task.uncertainty) >= 2 and not _has_graph_agent(agents, "clarifier"):
        agents.append(
            _graph_agent(
                "clarifier",
                "analyst",
                "transformar incertezas em hipóteses e perguntas operacionais",
            )
        )

    if str(task.risk.get("execution_risk", "low")) == "high" and not _has_graph_agent(
        agents, "risk_auditor"
    ):
        agents.append(
            _graph_agent(
                "risk_auditor",
                "critic",
                "isolar riscos críticos e pontos de falha antes da síntese final",
            )
        )

    tooling_capabilities = sorted(
        {
            str(item.get("id", "")).strip()
            for bucket in ("missing", "degraded")
            for item in (capability_resolution.get(bucket, []) or [])
            if str(item.get("id", "")).strip().startswith(("connector.", "tool."))
        }
    )
    for capability_id in tooling_capabilities:
        agent_id = _toolsmith_agent_for_capability(capability_id)
        if _has_graph_agent(agents, agent_id):
            continue
        agents.append(
            _graph_agent(
                agent_id,
                "operator",
                "especificar, forjar e estabilizar a capability dinâmica %s" % capability_id,
            )
        )

    toolrunner_capabilities = sorted(
        {
            str(item.get("id", "")).strip()
            for bucket in ("available", "degraded", "missing")
            for item in (capability_resolution.get(bucket, []) or [])
            if str(item.get("id", "")).strip().startswith(("connector.", "tool."))
            and _capability_module_path(item)
        }
    )
    for capability_id in toolrunner_capabilities:
        agent_id = _toolrunner_agent_for_capability(capability_id)
        if _has_graph_agent(agents, agent_id):
            continue
        agents.append(
            _graph_agent(
                agent_id,
                "operator",
                "executar e observar em runtime a capability dinâmica %s" % capability_id,
            )
        )

    workflow_composer_targets = sorted(
        {
            str(item.get("id", "")).strip()
            for bucket in ("available", "degraded", "missing")
            for item in (capability_resolution.get(bucket, []) or [])
            if str(item.get("id", "")).strip().startswith(("connector.", "tool."))
        }
    )
    if len(workflow_composer_targets) >= 2 and not _has_graph_agent(agents, "workflow_composer"):
        agents.append(
            _graph_agent(
                "workflow_composer",
                "synthesizer",
                "compor resultados das capacidades de tooling em fluxo integrado",
            )
        )
    return agents


def build_graph_native_checkpoints(
    decision: CognitiveDecision,
    capability_resolution: Dict[str, Any],
) -> list[Dict[str, Any]]:
    """Constrói checkpoints humanos baseados na decisão cognitiva."""
    checkpoints: list[Dict[str, Any]] = []
    if "human_checkpoint" in decision.selected_modes:
        checkpoints.append(
            {
                "id": new_id("checkpoint"),
                "reason": "cognitive_control_requested_human_checkpoint",
                "blocking": True,
            }
        )
    if capability_resolution.get("missing"):
        checkpoints.append(
            {
                "id": new_id("checkpoint"),
                "reason": "essential_capability_missing",
                "blocking": True,
            }
        )
    return checkpoints
