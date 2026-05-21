"""Gestão de sessão, evidência e memória do kernel."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from arnaldo.components import CapabilityRegistry, ToolForge
from arnaldo.contracts import EvidenceRecord, TaskIR, new_id, to_dict, utc_now
from arnaldo.memory import MemoryRecord, MemoryStore
from arnaldo.session import SessionManager, SessionState
from arnaldo.storage import RunStore


def evidence(
    store: RunStore,
    run_id: str,
    task_id: str,
    record_type: str,
    summary: str,
    payload: Dict[str, Any] | None = None,
) -> None:
    """Registra evidência no ledger da run."""
    record = EvidenceRecord(
        id=new_id("evidence"),
        run_id=run_id,
        task_id=task_id,
        created_at=utc_now(),
        record_type=record_type,
        summary=summary,
        payload=payload or {},
    )
    store.append_jsonl("evidence.jsonl", to_dict(record))


def remember(
    memory: MemoryStore,
    run_id: str,
    task_goal: Dict[str, Any],
    files: Dict[str, Path],
    session_id: str,
    adaptive_plan: Any,
    *,
    step_results: list[Dict[str, Any]] | None = None,
) -> None:
    """Registra memórias episódicas, procedurais e prospectivas da run."""
    record = MemoryRecord(
        id=run_id,
        kind="episodic",
        payload={
            "run_id": run_id,
            "session_id": session_id,
            "goal": task_goal,
            "artifacts": {key: str(path) for key, path in files.items()},
        },
    )
    memory.append(record)

    # 4.3: Episodic chain — conecta run atual à anterior via TEMPORAL_BEFORE
    from .memory_ops import link_episodic_chain

    link_episodic_chain(memory, run_id, session_id)
    if adaptive_plan.inferred_objectives:
        memory.append(
            MemoryRecord(
                id=new_id("memory"),
                kind="semantic",
                payload={
                    "session_id": session_id,
                    "objectives": adaptive_plan.inferred_objectives,
                },
            )
        )
    for step in step_results or []:
        action = str(step.get("action", "")).strip()
        step_id = str(step.get("step_id", "")).strip()
        agent_id = str(step.get("agent_id", "")).strip()
        capability_id = str(step.get("capability_id", "")).strip()
        result = step.get("result")
        result_summary = (
            result
            if isinstance(result, str)
            else json.dumps(result, ensure_ascii=True)[:400]
            if isinstance(result, dict)
            else str(result)[:400]
        )
        memory.append(
            MemoryRecord(
                id=new_id("memory"),
                kind="procedural",
                payload={
                    "session_id": session_id,
                    "run_id": run_id,
                    "step_id": step_id,
                    "agent_id": agent_id,
                    "action": action,
                    "capability_id": capability_id,
                    "summary": "%s::%s" % (action or "step", result_summary),
                    "result": result if isinstance(result, dict) else {"value": result_summary},
                },
            )
        )
    prospective_questions = [
        str(item.get("question", "")).strip()
        for item in (task_goal.get("uncertainty", []) if isinstance(task_goal, dict) else [])
        if isinstance(item, dict) and str(item.get("question", "")).strip()
    ]
    if not prospective_questions:
        for step in step_results or []:
            for raw in (
                step.get("uncertainties", []) if isinstance(step.get("uncertainties"), list) else []
            ):
                question = str(raw).strip()
                if question:
                    prospective_questions.append(question)
    for question in prospective_questions[:3]:
        memory.append(
            MemoryRecord(
                id=new_id("memory"),
                kind="prospective",
                payload={
                    "session_id": session_id,
                    "run_id": run_id,
                    "topic": question,
                    "status": "pending",
                },
            )
        )
    if adaptive_plan.learning_updates:
        memory.append(
            MemoryRecord(
                id=new_id("memory"),
                kind="procedural",
                payload={
                    "session_id": session_id,
                    "preferences": adaptive_plan.learning_updates,
                },
            )
        )


def inject_task_runtime_context(
    *,
    task: TaskIR,
    request: str,
    session: SessionState,
    adaptive_plan: Any,
) -> None:
    """Injeta contexto de runtime no TaskIR."""
    context_raw = task.context if isinstance(task.context, dict) else {}
    context = dict(context_raw)

    raw_request = " ".join((request or "").strip().split())
    if raw_request:
        context["raw_request"] = raw_request

    user_name = str(session.learned_preferences.get("user_name", "")).strip()
    if user_name:
        context["session_user_name"] = user_name

    inferred = getattr(adaptive_plan, "inferred_objectives", None)
    if isinstance(inferred, list) and inferred:
        context["inferred_objectives"] = [
            str(item).strip() for item in inferred if str(item).strip()
        ][:3]

    task.context = context


def open_session(
    sessions: SessionManager,
    session_id: str | None,
    autonomy: str,
    terms_accepted: bool | None,
) -> SessionState:
    """Abre ou retoma sessão."""
    state = sessions.open(
        session_id=session_id,
        autonomy_mode=autonomy,
        terms_accepted=bool(terms_accepted),
    )
    if terms_accepted:
        state = sessions.accept_terms(state)
    return state


def sync_objectives(sessions: SessionManager, state: SessionState, objectives: Any) -> SessionState:
    """Sincroniza objetivos inferidos na sessão."""
    current = state
    for item in objectives:
        current = sessions.register_objective(current, item)
    return current


def apply_session_autonomy_overrides(
    autonomy: Dict[str, Any],
    constraints: Dict[str, Any],
    session: SessionState,
) -> None:
    """Ajusta autonomia se sessão é self-managed com termos aceitos."""
    if not session.terms_accepted:
        return
    if session.governance_profile == "self_managed":
        autonomy["max_level"] = max(int(autonomy.get("max_level", 3)), 6)
        constraints["external_side_effects"] = "allowed_if_policy_compliant"
        constraints["private_data"] = "user_terms_based"


def run_tool_forge(
    tool_forge: ToolForge,
    capabilities: CapabilityRegistry,
    sessions: SessionManager,
    missing: Any,
    session: SessionState,
    run_id: str,
    task_id: str,
    store: RunStore,
) -> Tuple[Dict[str, Any], SessionState]:
    """Executa forge para capabilities faltantes."""
    report = tool_forge.forge_missing(copy.deepcopy(missing), session.id)
    for capability in report["capabilities"]:
        capabilities.register(capability)
    for item in report["created"]:
        evidence(
            store,
            run_id,
            task_id,
            "tool_forged",
            "tool_forge scaffold criado para %s" % item["capability_id"],
        )
        session = sessions.record_tool_event(
            session,
            capability_id=item["capability_id"],
            status=item["status"],
            metadata={"module_path": item.get("module_path", "")},
        )
    for item in report["failed"]:
        evidence(
            store,
            run_id,
            task_id,
            "tool_forge_failed",
            "tool_forge falhou para %s" % item["capability_id"],
        )
        session = sessions.record_tool_event(
            session,
            capability_id=item["capability_id"],
            status="failed",
            metadata={"error": item.get("error", "")},
        )
    return (
        {
            "created": report["created"],
            "failed": report["failed"],
        },
        session,
    )


def collect_forge_targets(capability_resolution: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Coleta capabilities candidatas a forge."""
    targets: dict[str, Dict[str, Any]] = {}
    for item in capability_resolution.get("missing", []) or []:
        capability_id = str(item.get("id", "")).strip()
        if not capability_id:
            continue
        targets[capability_id] = {
            "id": capability_id,
            "reason": str(item.get("reason", "capability_not_registered")),
            "severity": str(item.get("severity", "high")),
        }
    for item in capability_resolution.get("degraded", []) or []:
        capability_id = str(item.get("id", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if not capability_id:
            continue
        if reason != "optional_capability_not_registered":
            continue
        if capability_id in targets:
            continue
        targets[capability_id] = {
            "id": capability_id,
            "reason": reason,
            "severity": str(item.get("severity", "low")),
        }
    return [targets[key] for key in sorted(targets.keys())]
