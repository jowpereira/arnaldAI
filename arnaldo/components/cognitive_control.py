from __future__ import annotations

from typing import Dict, List

from arnaldo.contracts import CognitiveDecision, TaskIR, new_id


class CognitiveControlPlane:
    """Chooses how the system should think before choosing who acts."""

    def decide(self, task: TaskIR) -> CognitiveDecision:
        ambiguity = task.risk["execution_risk"]
        sensitivity = task.risk["data_sensitivity"]
        reversibility = task.risk["reversibility"]
        external_impact = "medium" if task.autonomy["max_level"] >= 3 else "low"

        selected_modes = select_modes(ambiguity, sensitivity, reversibility)
        return CognitiveDecision(
            version="cognitive-decision/v0",
            id=new_id("cog"),
            task_id=task.id,
            ambiguity=ambiguity,
            reversibility=reversibility,
            external_impact=external_impact,
            data_sensitivity=sensitivity,
            required_confidence="high" if ambiguity == "high" else "medium",
            selected_modes=selected_modes,
            rejected_modes=rejected_modes(selected_modes),
            budget={
                "depth": depth_for(ambiguity, sensitivity),
                "max_iterations": 3 if ambiguity != "high" else 5,
                "stop_when": "deliverables_validated",
            },
            stop_conditions=[
                "success_criteria_met",
                "human_approval_required",
                "essential_capability_missing",
                "residual_uncertainty_marked",
            ],
        )


def select_modes(ambiguity: str, sensitivity: str, reversibility: str) -> List[str]:
    if ambiguity == "low" and sensitivity == "low":
        return ["known_workflow", "single_specialist"]
    if ambiguity == "high" or sensitivity == "high":
        return ["parallel_exploration", "adversarial_review", "reality_gap_detection"]
    if reversibility == "low":
        return ["known_workflow", "adversarial_review", "human_checkpoint"]
    return ["known_workflow", "single_specialist", "adversarial_review"]


def rejected_modes(selected_modes: List[str]) -> List[Dict[str, str]]:
    candidates = {
        "direct_answer": "a execucao minima deve produzir artefato e evidencias",
        "tool_forge": "nenhuma capacidade essencial esta ausente neste corte local",
        "simulation": "risco atual nao justifica simulacao",
    }
    return [
        {"mode": mode, "reason": reason}
        for mode, reason in candidates.items()
        if mode not in selected_modes
    ]


def depth_for(ambiguity: str, sensitivity: str) -> str:
    if ambiguity == "high" or sensitivity == "high":
        return "deep"
    if ambiguity == "medium" or sensitivity == "medium":
        return "standard"
    return "shallow"
