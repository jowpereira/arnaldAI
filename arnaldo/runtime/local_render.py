"""local_render — funções de renderização e execução de steps do runtime local."""

from __future__ import annotations

from typing import Any, Dict, List


def execute_step(task: Any, item: Dict[str, Any]) -> Dict[str, Any]:
    action = item["action"]
    if action == "frame_intent":
        result = {
            "goal": task.goal["statement"],
            "goal_type": task.goal["type"],
            "constraints": task.constraints,
        }
    elif action in ("decompose_work", "explore_path_a", "explore_path_b"):
        result = {
            "steps": [
                "fixar contrato de saida",
                "selecionar capacidades necessarias",
                "executar menor workflow suficiente",
                "validar lacunas e criterios",
            ]
        }
    elif action in ("draft_artifact", "synthesize_artifact"):
        result = {
            "sections": [
                "objetivo",
                "plano de execucao",
                "criterios de sucesso",
                "evidencias",
                "proximas acoes",
            ]
        }
    elif action == "critic_review":
        result = {
            "status": "passed_with_warnings",
            "warnings": [
                "runtime local ainda nao usa ferramentas externas",
                "evidencias atuais sao internas ao processo",
            ],
        }
    else:
        result = {"status": "completed"}

    return {
        "step_id": item["id"],
        "agent_id": item["agent_id"],
        "action": action,
        "output": item["output"],
        "result": result,
        "uncertainties": [entry["question"] for entry in task.uncertainty],
    }


def render_artifact(
    task: Any,
    organization: Any,
    policy: Any,
    step_results: List[Dict[str, Any]],
) -> str:
    workflow_lines = "\n".join(
        "- `%s` por `%s` -> `%s`" % (step["action"], step["agent_id"], step["output"])
        for step in organization.workflow
    )
    criteria_lines = "\n".join(
        "- `%s`: %s" % (item["id"], item["description"]) for item in task.success_criteria
    )
    uncertainty_lines = (
        "\n".join("- %s" % item["question"] for item in task.uncertainty)
        or "- nenhuma incerteza relevante marcada neste corte"
    )
    result_lines = "\n".join(
        "- `%s`: %s" % (item["action"], item["output"]) for item in step_results
    )
    response_text = _derive_human_response(task, step_results)
    next_actions_lines = _derive_next_actions(step_results)

    return """# Artifact

## Resposta
%s

## Goal
%s

## Generic Execution Contract
- Goal type: `%s`
- Topology: `%s`
- Policy allowed: `%s`
- Approval required: `%s`

## Workflow
%s

## Step Outputs
%s

## Success Criteria
%s

## Uncertainties
%s

## Next Actions
- %s
""" % (
        response_text,
        task.goal["statement"],
        task.goal["type"],
        organization.topology,
        policy.allowed,
        policy.approval_required,
        workflow_lines,
        result_lines,
        criteria_lines,
        uncertainty_lines,
        next_actions_lines.replace("\n", "\n- "),
    )


def _derive_human_response(task: Any, step_results: List[Dict[str, Any]]) -> str:
    primary = _preferred_result_payload(step_results, preferred_outputs=("primary_artifact",))
    primary_text = _extract_response_text(primary)
    if primary_text:
        return primary_text

    latest = _latest_result_payload(step_results)
    latest_text = _extract_response_text(latest)
    if latest_text:
        return latest_text

    goal = str(task.goal.get("statement", "")).strip()
    if goal:
        return "Objetivo recebido: %s" % goal
    return "Execução concluída."


def _derive_next_actions(step_results: List[Dict[str, Any]]) -> str:
    latest = _preferred_result_payload(
        step_results,
        preferred_outputs=("critic_review", "risk_review", "decision_synthesis", "primary_artifact"),
    )
    uncertainties = latest.get("uncertainties")
    if isinstance(uncertainties, list):
        cleaned = [str(item).strip() for item in uncertainties if str(item).strip()]
        if cleaned:
            return "\n".join(cleaned[:3])
    return "Informe o próximo objetivo de forma direta para continuar."


def _latest_result_payload(step_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    for item in reversed(step_results):
        result = item.get("result")
        if isinstance(result, dict):
            return result
    return {}


def _preferred_result_payload(
    step_results: List[Dict[str, Any]],
    *,
    preferred_outputs: tuple[str, ...],
) -> Dict[str, Any]:
    for output_id in preferred_outputs:
        for item in reversed(step_results):
            if str(item.get("output", "")).strip() != output_id:
                continue
            result = item.get("result")
            if isinstance(result, dict):
                return result
    return _latest_result_payload(step_results)


def _extract_response_text(result: Dict[str, Any]) -> str:
    sections = result.get("sections")
    if isinstance(sections, list):
        for section in sections:
            text = str(section).strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered.startswith(
                (
                    "status:",
                    "evidence:",
                    "execution_evidence:",
                    "uncertainties:",
                    "incertezas:",
                    "warnings:",
                    "avisos:",
                    "next_actions:",
                )
            ):
                continue
            return text

    evidence = result.get("evidence")
    if isinstance(evidence, list):
        cleaned = [str(item).strip() for item in evidence if str(item).strip()]
        if cleaned:
            return cleaned[0]

    warnings = result.get("warnings")
    if isinstance(warnings, list):
        cleaned = [str(item).strip() for item in warnings if str(item).strip()]
        if cleaned:
            return cleaned[0]

    status = str(result.get("status", "")).strip()
    if status:
        return status
    return ""
