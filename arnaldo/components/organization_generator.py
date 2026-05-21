from __future__ import annotations

from typing import Any, Dict, List
import re

from arnaldo.contracts import (
    AgentGenome,
    CognitiveDecision,
    OrganizationIR,
    TaskIR,
    new_id,
    utc_now,
)


class OrganizationGenerator:
    """Creates temporary generic organizations from Task IR and cognitive decisions."""

    def generate(
        self,
        task: TaskIR,
        decision: CognitiveDecision,
        capability_resolution: Dict[str, Any],
    ) -> OrganizationIR:
        topology = choose_topology(decision)
        agents = build_agents(topology, task, capability_resolution)
        workflow = build_workflow(topology, agents, task, capability_resolution)
        return OrganizationIR(
            version="organization-ir/v0",
            id=new_id("org"),
            created_at=utc_now(),
            task_id=task.id,
            topology=topology,
            agents=agents,
            workflow=workflow,
            required_capabilities=[need["id"] for need in task.capability_needs],
            human_checkpoints=build_checkpoints(decision, capability_resolution),
        )


def choose_topology(decision: CognitiveDecision) -> str:
    if "parallel_exploration" in decision.selected_modes:
        return "parallel_with_synthesis"
    if "adversarial_review" in decision.selected_modes:
        return "pipeline_with_critic"
    return "minimal_pipeline"


def build_agents(
    topology: str,
    task: TaskIR,
    capability_resolution: Dict[str, Any],
) -> List[AgentGenome]:
    if topology == "parallel_with_synthesis":
        agents = [
            genome("framer", "operator", "enquadrar a intencao e separar fatos de inferencias"),
            genome("explorer_a", "explorer", "produzir uma decomposicao independente do trabalho"),
            genome("explorer_b", "explorer", "produzir uma segunda decomposicao independente"),
            genome("synthesizer", "synthesizer", "consolidar alternativas em um artefato unico"),
            genome("critic", "critic", "validar lacunas, riscos e criterios de sucesso"),
        ]
    elif topology == "pipeline_with_critic":
        agents = [
            genome("framer", "operator", "enquadrar a intencao como contrato executavel"),
            genome("planner", "operator", "decompor trabalho e preparar artefato"),
            genome("critic", "critic", "revisar incertezas, risco e proximas acoes"),
        ]
    else:
        agents = [
            genome("operator", "operator", "executar o menor workflow generico suficiente"),
        ]

    # Ajustes dinâmicos por contexto da task.
    uncertainty_count = len(task.uncertainty)
    execution_risk = str(task.risk.get("execution_risk", "low"))
    missing = capability_resolution.get("missing", []) or []
    has_tooling_gap = any(
        item.get("id", "").startswith(("connector.", "tool.")) for item in missing
    )

    if uncertainty_count >= 2 and not _has_agent(agents, "clarifier"):
        agents.append(
            genome(
                "clarifier",
                "analyst",
                "transformar incertezas em perguntas operacionais e hipóteses verificáveis",
            )
        )

    if execution_risk == "high" and not _has_agent(agents, "risk_auditor"):
        agents.append(
            genome(
                "risk_auditor",
                "critic",
                "isolar riscos críticos, dependências e pontos de falha antes da síntese final",
            )
        )

    if has_tooling_gap and not _has_agent(agents, "toolsmith"):
        agents.append(
            genome(
                "toolsmith",
                "operator",
                "definir especificação operacional de ferramentas/conectores que faltam",
            )
        )

    return agents


def genome(agent_id: str, role: str, objective: str) -> AgentGenome:
    return AgentGenome(
        id=agent_id,
        species="generic_worker",
        role=role,
        objective=objective,
        epistemic_style="evidence_first",
        required_capabilities=[],
        forbidden_capabilities=["send.external_message", "spend.money", "delete.user_data"],
        output_contract={
            "schema": "generic_step_output",
            "required_sections": ["result", "evidence", "uncertainties"],
        },
        validation={
            "require_uncertainty_marking": True,
            "require_evidence_record": True,
        },
        lifecycle={
            "max_iterations": 1,
            "expires_after_task": True,
        },
    )


def build_workflow(
    topology: str,
    agents: List[AgentGenome],
    task: TaskIR,
    capability_resolution: Dict[str, Any],
) -> List[Dict[str, Any]]:
    agent_ids = {agent.id for agent in agents}
    if topology == "parallel_with_synthesis":
        workflow = [
            step("frame_intent", "framer", "intent_frame"),
            step("explore_path_a", "explorer_a", "work_option_a"),
            step("explore_path_b", "explorer_b", "work_option_b"),
            step("synthesize_artifact", "synthesizer", "primary_artifact"),
            step("critic_review", "critic", "critic_review"),
        ]
    elif topology == "pipeline_with_critic":
        workflow = [
            step("frame_intent", "framer", "intent_frame"),
            step("decompose_work", "planner", "work_plan"),
            step("draft_artifact", "planner", "primary_artifact"),
            step("critic_review", "critic", "critic_review"),
        ]
    else:
        root_agent = agents[0].id
        workflow = [
            step("frame_intent", root_agent, "intent_frame"),
            step("decompose_work", root_agent, "work_plan"),
            step("draft_artifact", root_agent, "primary_artifact"),
        ]

    if "clarifier" in agent_ids:
        workflow.insert(1, step("clarify_uncertainties", "clarifier", "uncertainty_map"))

    missing = capability_resolution.get("missing", []) or []
    tooling_gaps = [
        item.get("id", "")
        for item in missing
        if item.get("id", "").startswith(("connector.", "tool."))
    ]
    if "toolsmith" in agent_ids and tooling_gaps:
        insert_idx = max(1, len(workflow) - 2)
        for capability_id in sorted(set(tooling_gaps))[:6]:
            workflow.insert(
                insert_idx,
                step(
                    "design_tooling",
                    "toolsmith",
                    "tool_specs_%s" % _slug(capability_id),
                ),
            )
            insert_idx += 1

    if "risk_auditor" in agent_ids:
        workflow.append(step("risk_review", "risk_auditor", "risk_report"))

    # Se tarefa pede avaliação/análise, adiciona estágio extra de síntese crítica.
    if (
        task.goal.get("type") in {"analyze_or_evaluate", "decide_or_compare"}
        and "critic" in agent_ids
    ):
        workflow.append(step("decision_synthesis", "critic", "decision_brief"))

    return workflow


def step(action: str, agent_id: str, output: str) -> Dict[str, Any]:
    return {
        "id": new_id("step"),
        "agent_id": agent_id,
        "action": action,
        "output": output,
    }


def build_checkpoints(
    decision: CognitiveDecision,
    capability_resolution: Dict[str, Any],
) -> List[Dict[str, Any]]:
    checkpoints = []
    if "human_checkpoint" in decision.selected_modes:
        checkpoints.append(
            {
                "id": new_id("checkpoint"),
                "reason": "cognitive_control_requested_human_checkpoint",
                "blocking": True,
            }
        )
    if capability_resolution["missing"]:
        checkpoints.append(
            {
                "id": new_id("checkpoint"),
                "reason": "essential_capability_missing",
                "blocking": True,
            }
        )
    return checkpoints


def _has_agent(agents: List[AgentGenome], agent_id: str) -> bool:
    return any(agent.id == agent_id for agent in agents)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower().replace(".", "_"))
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "x"
