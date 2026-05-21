"""Helpers de workflow: seed functions e operações CRUD de steps."""

from __future__ import annotations

from typing import Any, Dict

from arnaldo.contracts import new_id

from .classify import (
    _default_agent_for_action,
    _default_output_for_action,
    _toolrunner_agent_for_capability,
    _toolsmith_agent_for_capability,
)
from .capabilities import (
    _collect_tool_execution_targets,
    _collect_tooling_targets,
    _collect_workflow_tooling_capabilities,
)


def _workflow_seed_for_topology(topology: str) -> list[Dict[str, Any]]:
    if topology == "parallel_with_synthesis":
        return [
            _insert_workflow_step(
                [], 0, action="frame_intent", agent_id="framer", output="intent_frame"
            ),
            _insert_workflow_step(
                [], 0, action="explore_path_a", agent_id="explorer_a", output="work_option_a"
            ),
            _insert_workflow_step(
                [], 0, action="explore_path_b", agent_id="explorer_b", output="work_option_b"
            ),
            _insert_workflow_step(
                [],
                0,
                action="synthesize_artifact",
                agent_id="synthesizer",
                output="primary_artifact",
            ),
            _insert_workflow_step(
                [], 0, action="critic_review", agent_id="critic", output="critic_review"
            ),
        ]
    if topology == "pipeline_with_critic":
        return [
            _insert_workflow_step(
                [], 0, action="frame_intent", agent_id="framer", output="intent_frame"
            ),
            _insert_workflow_step(
                [], 0, action="decompose_work", agent_id="planner", output="work_plan"
            ),
            _insert_workflow_step(
                [], 0, action="draft_artifact", agent_id="planner", output="primary_artifact"
            ),
            _insert_workflow_step(
                [], 0, action="critic_review", agent_id="critic", output="critic_review"
            ),
        ]
    return [
        _insert_workflow_step(
            [], 0, action="frame_intent", agent_id="operator", output="intent_frame"
        ),
        _insert_workflow_step(
            [], 0, action="decompose_work", agent_id="operator", output="work_plan"
        ),
        _insert_workflow_step(
            [], 0, action="draft_artifact", agent_id="operator", output="primary_artifact"
        ),
    ]


def _workflow_seed_for_lightweight_conversation() -> list[Dict[str, Any]]:
    return [
        _insert_workflow_step(
            [],
            0,
            action="draft_artifact",
            agent_id="operator",
            output="primary_artifact",
            tier_preference="fast",
            max_tokens=320,
            timeout=18.0,
            temperature=0.2,
            max_retries=0,
            retry_attempts=1,
            objective=_lightweight_conversation_objective(),
            output_contract=_lightweight_conversation_output_contract(),
        ),
    ]


def _workflow_seed_for_latency_sensitive_cli_turn() -> list[Dict[str, Any]]:
    return [
        _insert_workflow_step(
            [],
            0,
            action="draft_artifact",
            agent_id="operator",
            output="primary_artifact",
            tier_preference="fast",
            max_tokens=700,
            timeout=25.0,
            temperature=0.2,
            max_retries=0,
            retry_attempts=1,
        ),
    ]


def _lightweight_conversation_objective() -> str:
    return (
        "responder diretamente ao usuario em tom conversacional claro, "
        "sem metalinguagem de pipeline, priorizando memoria de sessao quando houver"
    )


def _lightweight_conversation_output_contract() -> Dict[str, Any]:
    return {
        "schema": "chat_turn_output",
        "required_sections": ["sections", "evidence", "uncertainties"],
        "rules": [
            "sections[0] deve conter a resposta final ao usuario",
            "resposta deve ser natural e curta (1-4 frases)",
            "nao mencionar goaltype, deliverables, capabilityneeds ou logs",
        ],
    }


def _upsert_workflow_step(
    workflow: list[Dict[str, Any]],
    *,
    action: str,
    agent_id: str,
    output: str,
    capability_id: str | None = None,
    module_path: str | None = None,
) -> None:
    if _has_workflow_step(workflow, action, capability_id=capability_id):
        return
    workflow.append(
        _insert_workflow_step(
            [],
            0,
            action=action,
            agent_id=agent_id,
            output=output,
            capability_id=capability_id,
            module_path=module_path,
        )
    )


def _has_workflow_step(
    workflow: list[Dict[str, Any]],
    action: str,
    *,
    capability_id: str | None = None,
) -> bool:
    for item in workflow:
        if item.get("action") != action:
            continue
        if capability_id is None:
            return True
        if str(item.get("capability_id", "")).strip() == capability_id:
            return True
    return False


def _insert_workflow_step(
    workflow: list[Dict[str, Any]],
    index: int,
    *,
    action: str,
    agent_id: str,
    output: str,
    capability_id: str | None = None,
    module_path: str | None = None,
    tier_preference: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    temperature: float | None = None,
    max_retries: int | None = None,
    retry_attempts: int | None = None,
    objective: str | None = None,
    output_contract: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "id": new_id("step"),
        "agent_id": agent_id,
        "action": action,
        "output": output,
    }
    if objective:
        item["objective"] = str(objective).strip()
    if isinstance(output_contract, dict) and output_contract:
        item["output_contract"] = dict(output_contract)
    if tier_preference:
        item["tier_preference"] = str(tier_preference)
    if isinstance(max_tokens, int) and max_tokens > 0:
        item["max_tokens"] = max_tokens
    if isinstance(timeout, (int, float)) and timeout > 0:
        item["timeout"] = float(timeout)
    if isinstance(temperature, (int, float)):
        item["temperature"] = float(temperature)
    if isinstance(max_retries, int) and max_retries >= 0:
        item["max_retries"] = max_retries
    if isinstance(retry_attempts, int) and retry_attempts > 0:
        item["retry_attempts"] = retry_attempts
    if capability_id:
        item["capability_id"] = capability_id
    if module_path:
        item["module_path"] = module_path
    if workflow is not None:
        workflow.insert(index, item)
    return item


def _inject_tooling_and_review_steps(
    workflow: list[Dict[str, Any]],
    task: Any,
    capability_resolution: Dict[str, Any],
) -> None:
    from .infra import _slug

    tooling_targets = _collect_tooling_targets(capability_resolution)
    insert_before = min(
        [
            idx
            for idx, item in enumerate(workflow)
            if item["action"] in {"synthesize_artifact", "draft_artifact", "critic_review"}
        ]
        or [len(workflow)]
    )
    for capability_id in tooling_targets["missing"]:
        if _has_workflow_step(workflow, "design_tooling", capability_id=capability_id):
            continue
        _insert_workflow_step(
            workflow,
            insert_before,
            action="design_tooling",
            agent_id=_toolsmith_agent_for_capability(capability_id),
            output="tool_specs_%s" % _slug(capability_id),
            capability_id=capability_id,
        )
        insert_before += 1

    for capability_id in tooling_targets["degraded"]:
        if _has_workflow_step(workflow, "stabilize_tooling", capability_id=capability_id):
            continue
        _insert_workflow_step(
            workflow,
            insert_before,
            action="stabilize_tooling",
            agent_id=_toolsmith_agent_for_capability(capability_id),
            output="tool_stability_%s" % _slug(capability_id),
            capability_id=capability_id,
        )
        insert_before += 1

    for target in _collect_tool_execution_targets(capability_resolution):
        capability_id = target["id"]
        if _has_workflow_step(workflow, "execute_tooling", capability_id=capability_id):
            continue
        _insert_workflow_step(
            workflow,
            insert_before,
            action="execute_tooling",
            agent_id=_toolrunner_agent_for_capability(capability_id),
            output="tool_exec_%s" % _slug(capability_id),
            capability_id=capability_id,
            module_path=target["module_path"],
        )
        insert_before += 1

    tooling_compose_targets = _collect_workflow_tooling_capabilities(workflow)
    if len(tooling_compose_targets) >= 2 and not _has_workflow_step(workflow, "compose_tooling"):
        compose_insert_before = min(
            [
                idx
                for idx, item in enumerate(workflow)
                if item["action"]
                in {
                    "synthesize_artifact",
                    "draft_artifact",
                    "critic_review",
                    "risk_review",
                    "decision_synthesis",
                }
            ]
            or [len(workflow)]
        )
        _insert_workflow_step(
            workflow,
            compose_insert_before,
            action="compose_tooling",
            agent_id=_default_agent_for_action("compose_tooling"),
            output=_default_output_for_action("compose_tooling"),
        )

    _upsert_workflow_step(
        workflow,
        action="critic_review",
        agent_id=_default_agent_for_action("critic_review"),
        output=_default_output_for_action("critic_review"),
    )
    if str(task.risk.get("execution_risk", "low")) == "high":
        _upsert_workflow_step(
            workflow,
            action="risk_review",
            agent_id=_default_agent_for_action("risk_review"),
            output=_default_output_for_action("risk_review"),
        )
    if task.goal.get("type") in {"analyze_or_evaluate", "decide_or_compare"}:
        _upsert_workflow_step(
            workflow,
            action="decision_synthesis",
            agent_id=_default_agent_for_action("decision_synthesis"),
            output=_default_output_for_action("decision_synthesis"),
        )
