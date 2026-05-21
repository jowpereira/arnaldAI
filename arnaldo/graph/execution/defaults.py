"""Funções utilitárias e defaults para execução de synapses."""

from __future__ import annotations

import json
from typing import Any

from .context import StepContext, SynapseExecutionResult
from ..nodes import SynapseNode


def _format_exception_detail(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    status = getattr(exc, "status", None)
    body = str(getattr(exc, "body", "") or "").strip()
    if isinstance(status, int):
        message = f"{message} (status={status})"
    if not body:
        return message
    compact_body = " ".join(body.split())
    if len(compact_body) > 600:
        compact_body = compact_body[:600] + "..."
    return f"{message} | body={compact_body}"


def _resolve_payload_positive_int(value: Any, *, fallback: int | None = None) -> int | None:
    if value is None:
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    if parsed <= 0:
        return fallback
    return parsed


def _resolve_payload_positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _resolve_payload_float(value: Any, *, fallback: float) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _resolve_payload_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _default_timeout_for_tier(tier: str) -> float:
    normalized = str(tier).strip().lower()
    if normalized == "fast":
        return 30.0
    if normalized == "god":
        return 120.0
    if normalized == "codex":
        return 120.0
    return 90.0


def _default_max_tokens_for_action(*, action: str, tier: str) -> int:
    normalized_action = str(action).strip()
    by_action: dict[str, int] = {
        "frame_intent": 900,
        "clarify_uncertainties": 1200,
        "decompose_work": 1200,
        "explore_path_a": 1200,
        "explore_path_b": 1200,
        "design_tooling": 1200,
        "stabilize_tooling": 1200,
        "compose_tooling": 1400,
        "draft_artifact": 1600,
        "synthesize_artifact": 1600,
        "critic_review": 1400,
        "risk_review": 1400,
        "decision_synthesis": 1400,
    }
    if normalized_action in by_action:
        return by_action[normalized_action]
    normalized_tier = str(tier).strip().lower()
    if normalized_tier == "fast":
        return 800
    if normalized_tier == "god":
        return 2000
    if normalized_tier == "codex":
        return 1800
    return 1400


def _default_reasoning_effort_for_action(*, action: str, tier: str) -> str:
    normalized_tier = str(tier).strip().lower()
    if normalized_tier not in {"expert", "god", "codex"}:
        return ""
    if normalized_tier == "god":
        return "high"
    normalized_action = str(action).strip()
    if normalized_action in {
        "frame_intent",
        "clarify_uncertainties",
        "decompose_work",
        "explore_path_a",
        "explore_path_b",
        "design_tooling",
        "stabilize_tooling",
        "draft_artifact",
        "synthesize_artifact",
    }:
        return "low"
    if normalized_action in {"critic_review", "risk_review", "decision_synthesis"}:
        return "medium"
    return "medium"


def _build_chat_kwargs(
    node: SynapseNode,
    action: str,
    tier: str,
    max_retries: int,
    temperature: float,
) -> dict[str, Any]:
    step_max_retries = _resolve_payload_positive_int(
        node.payload.get("max_retries"),
        fallback=max_retries,
    )
    step_temperature = _resolve_payload_float(
        node.payload.get("temperature"),
        fallback=temperature,
    )
    chat_kwargs: dict[str, Any] = {
        "max_retries": step_max_retries,
        "temperature": step_temperature,
    }
    step_retry_attempts = _resolve_payload_positive_int(
        node.payload.get("retry_attempts"),
        fallback=1,
    )
    if step_retry_attempts is not None:
        chat_kwargs["retry_attempts"] = step_retry_attempts
    step_max_tokens = _resolve_payload_positive_int(node.payload.get("max_tokens"))
    if step_max_tokens is None:
        step_max_tokens = _default_max_tokens_for_action(action=action, tier=tier)
    if step_max_tokens is not None:
        chat_kwargs["max_tokens"] = step_max_tokens
    step_timeout = _resolve_payload_positive_float(node.payload.get("timeout"))
    if step_timeout is None:
        step_timeout = _default_timeout_for_tier(tier)
    if step_timeout is not None:
        chat_kwargs["timeout"] = step_timeout
    reasoning_effort = _resolve_payload_str(node.payload.get("reasoning_effort"))
    if not reasoning_effort:
        reasoning_effort = _default_reasoning_effort_for_action(action=action, tier=tier)
    if reasoning_effort:
        chat_kwargs["reasoning_effort"] = reasoning_effort
    reasoning_summary = _resolve_payload_str(node.payload.get("reasoning_summary"))
    if reasoning_summary:
        chat_kwargs["reasoning_summary"] = reasoning_summary
    return chat_kwargs


def _build_messages(
    *,
    node: SynapseNode,
    request: str,
    context: StepContext,
) -> list[dict[str, str]]:
    system_parts = [
        "Você é um synapse especializado do Arnaldo.",
        f"Role: {node.payload.get('role', 'generic')}.",
        f"Action: {node.payload.get('action', '')}.",
        f"Objective: {node.payload.get('objective', '')}.",
        f"Epistemic style: {node.payload.get('epistemic_style', 'evidence_first')}.",
        "Responda de forma estritamente estruturada conforme o contrato de saída.",
    ]
    output_contract = node.payload.get("output_contract")
    if output_contract:
        system_parts.append(
            "Contrato declarativo de saída: "
            + json.dumps(output_contract, ensure_ascii=True, separators=(",", ":"))
        )
    user_content = request
    previous = context.snapshot_recent_outputs(limit=3)
    if previous:
        user_content += "\n\nContexto prévio (últimos outputs): " + json.dumps(
            previous, ensure_ascii=True, separators=(",", ":")
        )
    tool_outputs = context.snapshot_recent_tool_outputs(limit=3)
    if tool_outputs:
        user_content += "\n\nSaidas de ferramentas recentes: " + json.dumps(
            tool_outputs, ensure_ascii=True, separators=(",", ":")
        )
    related = context.snapshot_related_outputs(
        action=str(node.payload.get("action", "")),
        capability_id=str(node.payload.get("capability_id", "")),
        limit=4,
    )
    if related:
        user_content += "\n\nContexto relacionado (acao/capability): " + json.dumps(
            related, ensure_ascii=True, separators=(",", ":")
        )
    return [
        {"role": "system", "content": " ".join(system_parts)},
        {"role": "user", "content": user_content},
    ]


def _fallback_result(
    *,
    node: SynapseNode,
    tier: str,
    context: StepContext,
    reason: str,
    request: str,
) -> SynapseExecutionResult:
    payload = {
        "status": "fallback",
        "reason": reason,
        "role": node.payload.get("role", "generic"),
        "objective": node.payload.get("objective", ""),
        "request_excerpt": request[:180],
    }
    context.write(
        node.id,
        payload,
        action=str(node.payload.get("action", "")),
        agent_id=str(node.payload.get("agent_id", "")),
        capability_id=str(node.payload.get("capability_id", "")),
        channel="fallback",
    )
    return SynapseExecutionResult(
        node_id=node.id,
        tier=tier,
        success=False,
        output=payload,
        fallback_used=True,
    )
