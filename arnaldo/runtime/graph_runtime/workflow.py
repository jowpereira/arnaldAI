"""Materialização de workflow para o GraphRuntime."""

from __future__ import annotations

from typing import Any, Dict

from arnaldo.contracts import new_id

from .classify import (
    _default_agent_for_action,
    _default_output_for_action,
    _extract_primary_user_request,
    _is_conversational_cli_turn,
    _is_latency_sensitive_cli_turn,
    _is_lightweight_conversational_task,
    _toolrunner_agent_for_capability,
    _toolsmith_agent_for_capability,
    _word_count,
)
from .capabilities import (
    _capability_module_path,
    _infer_capability_id_from_output,
)
from .infra import (
    _normalize_float,
    _normalize_positive_float,
    _normalize_positive_int,
    _slug,
)
from .workflow_helpers import (
    _has_workflow_step,
    _inject_tooling_and_review_steps,
    _insert_workflow_step,
    _lightweight_conversation_objective,
    _lightweight_conversation_output_contract,
    _upsert_workflow_step,
    _workflow_seed_for_latency_sensitive_cli_turn,
    _workflow_seed_for_lightweight_conversation,
    _workflow_seed_for_topology,
)

# Campos herdáveis que podem vazar entre steps de materialização
_INHERITABLE_PARAMS = (
    "max_tokens",
    "timeout",
    "temperature",
    "max_retries",
    "retry_attempts",
    "reasoning_effort",
    "reasoning_summary",
    "tier_preference",
    "objective",
    "output_contract",
)


def _strip_inherited_params(item: Dict[str, Any]) -> None:
    """Remove campos herdados de steps anteriores para evitar payload leak."""
    for key in _INHERITABLE_PARAMS:
        item.pop(key, None)


def _materialize_runtime_workflow(
    *,
    organization: Any,
    task: Any,
    capability_resolution: Dict[str, Any],
) -> list[Dict[str, Any]]:
    lightweight_conversation = _is_lightweight_conversational_task(task)
    conversational_cli = _is_conversational_cli_turn(
        task=task,
        capability_resolution=capability_resolution,
    )
    latency_sensitive_cli = _is_latency_sensitive_cli_turn(
        task=task,
        capability_resolution=capability_resolution,
    )
    source = list(organization.workflow or [])
    if not source:
        if lightweight_conversation:
            source = _workflow_seed_for_lightweight_conversation()
        elif latency_sensitive_cli:
            source = _workflow_seed_for_latency_sensitive_cli_turn()
        else:
            source = _workflow_seed_for_topology(organization.topology)

    tooling_id_by_slug: dict[str, str] = {}
    module_path_by_capability: dict[str, str] = {}
    for bucket in ("available", "degraded", "missing"):
        for item in capability_resolution.get(bucket, []) or []:
            capability_id = str(item.get("id", "")).strip()
            if capability_id.startswith(("connector.", "tool.", "search.")):
                tooling_id_by_slug[_slug(capability_id)] = capability_id
                module_path = _capability_module_path(item)
                if module_path:
                    module_path_by_capability[capability_id] = module_path
    for item in task.capability_needs:
        capability_id = str(item.get("id", "")).strip()
        if capability_id.startswith(("connector.", "tool.", "search.")):
            tooling_id_by_slug[_slug(capability_id)] = capability_id

    workflow: list[Dict[str, Any]] = []
    for item in source:
        action = str(item.get("action", "")).strip()
        if not action:
            continue
        output = str(item.get("output") or _default_output_for_action(action))
        capability_id = str(item.get("capability_id", "")).strip()
        if not capability_id and action in {
            "design_tooling",
            "stabilize_tooling",
            "execute_tooling",
        }:
            capability_id = _infer_capability_id_from_output(
                action=action,
                output=output,
                tooling_id_by_slug=tooling_id_by_slug,
            )
        agent_id = str(item.get("agent_id") or _default_agent_for_action(action))
        if action in {"design_tooling", "stabilize_tooling"} and capability_id:
            if agent_id in {"", "toolsmith", _default_agent_for_action(action)}:
                agent_id = _toolsmith_agent_for_capability(capability_id)
        if action == "execute_tooling" and capability_id:
            if agent_id in {"", "toolrunner", _default_agent_for_action(action)}:
                agent_id = _toolrunner_agent_for_capability(capability_id)
        module_path = _capability_module_path(item)
        if not module_path and capability_id:
            module_path = module_path_by_capability.get(capability_id, "")
        normalized: Dict[str, Any] = {
            "id": str(item.get("id") or new_id("step")),
            "agent_id": agent_id,
            "action": action,
            "output": output,
        }
        objective = str(item.get("objective", "")).strip()
        if objective:
            normalized["objective"] = objective
        output_contract = item.get("output_contract")
        if isinstance(output_contract, dict) and output_contract:
            normalized["output_contract"] = output_contract
        tier_preference = str(item.get("tier_preference", "")).strip()
        if tier_preference:
            normalized["tier_preference"] = tier_preference
        max_tokens = _normalize_positive_int(item.get("max_tokens"))
        if max_tokens > 0:
            normalized["max_tokens"] = max_tokens
        timeout = _normalize_positive_float(item.get("timeout"))
        if timeout > 0:
            normalized["timeout"] = timeout
        step_temperature = _normalize_float(item.get("temperature"))
        if step_temperature is not None:
            normalized["temperature"] = step_temperature
        max_retries = _normalize_positive_int(item.get("max_retries"))
        if max_retries > 0:
            normalized["max_retries"] = max_retries
        retry_attempts = _normalize_positive_int(item.get("retry_attempts"))
        if retry_attempts > 0:
            normalized["retry_attempts"] = retry_attempts
        reasoning_effort = str(item.get("reasoning_effort", "")).strip()
        if reasoning_effort:
            normalized["reasoning_effort"] = reasoning_effort
        reasoning_summary = str(item.get("reasoning_summary", "")).strip()
        if reasoning_summary:
            normalized["reasoning_summary"] = reasoning_summary
        if capability_id:
            normalized["capability_id"] = capability_id
        if module_path:
            normalized["module_path"] = module_path
        workflow.append(normalized)

    if not workflow:
        if lightweight_conversation:
            workflow = _workflow_seed_for_lightweight_conversation()
        elif latency_sensitive_cli:
            workflow = _workflow_seed_for_latency_sensitive_cli_turn()
        else:
            workflow = _workflow_seed_for_topology(organization.topology)

    if lightweight_conversation:
        compact = [
            item for item in workflow if str(item.get("action", "")).strip() == "draft_artifact"
        ]
        if not compact:
            compact = _workflow_seed_for_lightweight_conversation()
        item = compact[0]
        _strip_inherited_params(item)
        item.setdefault("agent_id", _default_agent_for_action("draft_artifact"))
        item["action"] = "draft_artifact"
        item.setdefault("output", _default_output_for_action("draft_artifact"))
        item["tier_preference"] = "fast"
        item["max_tokens"] = 320
        item["timeout"] = 18.0
        item["temperature"] = 0.2
        item["max_retries"] = 0
        item["retry_attempts"] = 1
        item["objective"] = _lightweight_conversation_objective()
        item["output_contract"] = _lightweight_conversation_output_contract()
        return [item]

    if conversational_cli:
        compact = [
            item for item in workflow if str(item.get("action", "")).strip() == "draft_artifact"
        ]
        if not compact:
            compact = _workflow_seed_for_lightweight_conversation()
        item = compact[0]
        _strip_inherited_params(item)
        request = _extract_primary_user_request(task)
        words = _word_count(request)
        item.setdefault("agent_id", _default_agent_for_action("draft_artifact"))
        item["action"] = "draft_artifact"
        item.setdefault("output", _default_output_for_action("draft_artifact"))
        item["tier_preference"] = "fast" if words <= 18 else "expert"
        item["max_tokens"] = 420 if words <= 12 else 900
        item["timeout"] = 25.0 if words <= 12 else 50.0
        item["temperature"] = 0.2
        item["max_retries"] = 0
        item["retry_attempts"] = 1
        item["objective"] = _lightweight_conversation_objective()
        item["output_contract"] = _lightweight_conversation_output_contract()
        return [item]

    if latency_sensitive_cli:
        compact = [
            item for item in workflow if str(item.get("action", "")).strip() == "draft_artifact"
        ]
        if not compact:
            compact = _workflow_seed_for_latency_sensitive_cli_turn()
        item = compact[0]
        item.setdefault("agent_id", _default_agent_for_action("draft_artifact"))
        item["action"] = "draft_artifact"
        item.setdefault("output", _default_output_for_action("draft_artifact"))
        item.setdefault("tier_preference", "fast")
        item.setdefault("max_tokens", 700)
        item.setdefault("timeout", 25.0)
        item.setdefault("temperature", 0.2)
        item.setdefault("max_retries", 0)
        item.setdefault("retry_attempts", 1)
        return [item]

    if not _has_workflow_step(workflow, "frame_intent"):
        _insert_workflow_step(
            workflow,
            0,
            action="frame_intent",
            agent_id=_default_agent_for_action("frame_intent"),
            output=_default_output_for_action("frame_intent"),
        )

    if len(task.uncertainty) >= 2 and not _has_workflow_step(workflow, "clarify_uncertainties"):
        insert_at = 1 if workflow else 0
        _insert_workflow_step(
            workflow,
            insert_at,
            action="clarify_uncertainties",
            agent_id=_default_agent_for_action("clarify_uncertainties"),
            output=_default_output_for_action("clarify_uncertainties"),
        )

    if organization.topology == "parallel_with_synthesis":
        for action in ("explore_path_a", "explore_path_b", "synthesize_artifact"):
            _upsert_workflow_step(
                workflow,
                action=action,
                agent_id=_default_agent_for_action(action),
                output=_default_output_for_action(action),
            )
    else:
        for action in ("decompose_work", "draft_artifact"):
            _upsert_workflow_step(
                workflow,
                action=action,
                agent_id=_default_agent_for_action(action),
                output=_default_output_for_action(action),
            )

    _inject_tooling_and_review_steps(workflow, task, capability_resolution)

    return workflow
