"""Utilitários puros e funções de infraestrutura base para o GraphRuntime."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from arnaldo.contracts import to_dict
from arnaldo.graph import CognitiveGraph

from .classify import (
    _extract_primary_user_request,
    _is_conversational_cli_turn,
    _is_lightweight_conversational_task,
)


def _result_summary(result_payload: Dict[str, Any]) -> str:
    for key in ("status", "result", "goal", "goal_type"):
        value = result_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return "resultado registrado"


def _synapse_node_id(agent_id: str, action: str, output_name: str | None = None) -> str:
    parts = ["syn", _slug(agent_id), _slug(action)]
    if output_name:
        parts.append(_slug(output_name))
    return "_".join(parts)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower().replace(".", "_"))
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "x"


def _load_seed_graph(seed_graph_path: Path | None) -> CognitiveGraph:
    if seed_graph_path is None or not seed_graph_path.exists():
        return CognitiveGraph()
    try:
        return CognitiveGraph.load(seed_graph_path)
    except Exception:
        return CognitiveGraph()


def _build_request(task: Any, capability_resolution: Dict[str, Any]) -> str:
    if _is_lightweight_conversational_task(task) or _is_conversational_cli_turn(
        task=task,
        capability_resolution=capability_resolution,
    ):
        context_raw = getattr(task, "context", {})
        context = context_raw if isinstance(context_raw, dict) else {}
        user_message = _extract_primary_user_request(task)
        if not user_message:
            goal = task.goal if isinstance(task.goal, dict) else {}
            user_message = str(goal.get("statement", "")).strip()
        session_user_name = str(context.get("session_user_name", "")).strip()
        lines = [
            "Mode: conversational_reply",
            "UserMessage: %s" % user_message,
            (
                "Instructions: responda em portugues (pt-BR), de forma natural e direta; "
                "nao descreva pipeline, goal, deliverables, capabilities, logs ou etapas internas."
            ),
        ]
        if session_user_name:
            lines.append("SessionMemory.user_name: %s" % session_user_name)
            lines.append(
                "Se o usuario perguntar sobre identidade/nome, use SessionMemory.user_name com prioridade."
            )
        return "\n".join(lines)

    capability_needs = [
        str(item.get("id", "")).strip()
        for item in task.capability_needs
        if str(item.get("id", "")).strip()
    ]
    missing = [
        str(item.get("id", "")).strip()
        for item in (capability_resolution.get("missing", []) or [])
        if str(item.get("id", "")).strip()
    ]
    degraded = [
        str(item.get("id", "")).strip()
        for item in (capability_resolution.get("degraded", []) or [])
        if str(item.get("id", "")).strip()
    ]
    uncertainties = [
        str(item.get("question", "")).strip()
        for item in task.uncertainty
        if str(item.get("question", "")).strip()
    ]
    deliverables = [
        str(item.get("id", "")).strip()
        for item in task.deliverables
        if str(item.get("id", "")).strip()
    ]

    return "\n".join(
        [
            "Goal: %s" % task.goal.get("statement", ""),
            "GoalType: %s" % task.goal.get("type", ""),
            "Deliverables: %s" % json.dumps(deliverables, ensure_ascii=True),
            "CapabilityNeeds: %s" % json.dumps(capability_needs, ensure_ascii=True),
            "MissingCapabilities: %s" % json.dumps(missing, ensure_ascii=True),
            "DegradedCapabilities: %s" % json.dumps(degraded, ensure_ascii=True),
            "Uncertainties: %s" % json.dumps(uncertainties, ensure_ascii=True),
        ]
    )


def _select_execution_mode(topology: str) -> str:
    if topology == "parallel_with_synthesis":
        return "activates_parallel_levels"
    return "activates_reachable"


def _normalize_execution_payload(result: Any) -> dict[str, Any]:
    if result.output is not None:
        normalized = to_dict(result.output)
    else:
        normalized = {}
    normalized["_meta"] = {
        "success": result.success,
        "fallback_used": result.fallback_used,
        "tier": result.tier,
        "refusal": result.refusal,
        "error": result.error,
    }
    return normalized


def _env_positive_int(name: str, *, default: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _normalize_positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _normalize_positive_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed > 0 else 0.0


def _normalize_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
