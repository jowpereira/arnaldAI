from __future__ import annotations

from typing import Any, Dict, List

from arnaldo.contracts import AgentGenome, CognitiveDecision, OrganizationIR, TaskIR, new_id, utc_now


class OrganizationGenerator:
    """Creates temporary generic organizations from Task IR and cognitive decisions."""

    def generate(
        self,
        task: TaskIR,
        decision: CognitiveDecision,
        capability_resolution: Dict[str, Any],
    ) -> OrganizationIR:
        topology = choose_topology(decision)
        agents = build_agents(topology, task)
        workflow = build_workflow(topology, agents)
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


def build_agents(topology: str, task: TaskIR) -> List[AgentGenome]:
    if topology == "parallel_with_synthesis":
        return [
            genome("framer", "operator", "enquadrar a intencao e separar fatos de inferencias"),
            genome("explorer_a", "explorer", "produzir uma decomposicao independente do trabalho"),
            genome("explorer_b", "explorer", "produzir uma segunda decomposicao independente"),
            genome("synthesizer", "synthesizer", "consolidar alternativas em um artefato unico"),
            genome("critic", "critic", "validar lacunas, riscos e criterios de sucesso"),
        ]
    if topology == "pipeline_with_critic":
        return [
            genome("framer", "operator", "enquadrar a intencao como contrato executavel"),
            genome("planner", "operator", "decompor trabalho e preparar artefato"),
            genome("critic", "critic", "revisar incertezas, risco e proximas acoes"),
        ]
    return [
        genome("operator", "operator", "executar o menor workflow generico suficiente"),
    ]


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


def build_workflow(topology: str, agents: List[AgentGenome]) -> List[Dict[str, Any]]:
    if topology == "parallel_with_synthesis":
        return [
            step("frame_intent", "framer", "intent_frame"),
            step("explore_path_a", "explorer_a", "work_option_a"),
            step("explore_path_b", "explorer_b", "work_option_b"),
            step("synthesize_artifact", "synthesizer", "primary_artifact"),
            step("critic_review", "critic", "critic_review"),
        ]
    if topology == "pipeline_with_critic":
        return [
            step("frame_intent", "framer", "intent_frame"),
            step("decompose_work", "planner", "work_plan"),
            step("draft_artifact", "planner", "primary_artifact"),
            step("critic_review", "critic", "critic_review"),
        ]
    return [
        step("frame_intent", agents[0].id, "intent_frame"),
        step("decompose_work", agents[0].id, "work_plan"),
        step("draft_artifact", agents[0].id, "primary_artifact"),
    ]


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
