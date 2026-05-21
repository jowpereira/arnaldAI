"""Artefatos do pipeline — escrita de IRs e coleta de outputs."""

from __future__ import annotations

from typing import Any, Dict

from arnaldo.contracts import to_dict


def write_pipeline_artifacts(
    store: Any,
    sessions: Any,
    adaptive_plan: Any,
    intent: Any,
    task: Any,
    decision: Any,
    capability_resolution: Dict[str, Any],
    organization: Any,
    policy: Any,
    sandbox: Any,
    tool_forge_report: Dict[str, Any],
    session: Any,
) -> Dict[str, Any]:
    files: Dict[str, Any] = {
        "adaptive_plan": store.write_json("adaptive-plan.json", to_dict(adaptive_plan)),
        "intent_ir": store.write_json("intent-ir.json", to_dict(intent)),
        "task_ir": store.write_json("task-ir.json", to_dict(task)),
        "cognitive_decision": store.write_json("cognitive-decision.json", to_dict(decision)),
        "capability_resolution": store.write_json(
            "capability-resolution.json", capability_resolution
        ),
        "organization_ir": store.write_json("organization-ir.json", to_dict(organization)),
        "policy_decision": store.write_json("policy-decision.json", to_dict(policy)),
        "sandbox_state": store.write_json("sandbox-state.json", to_dict(sandbox)),
        "session_state": store.write_json("session-state.json", sessions.snapshot(session)),
    }
    if tool_forge_report["created"] or tool_forge_report["failed"]:
        files["tool_forge_report"] = store.write_json("tool-forge-report.json", tool_forge_report)
    return files


def build_memory_hints(
    memory: Any,
    request: str,
    task: Any,
    store: Any,
    files: Dict[str, Any],
) -> Dict[str, Any]:
    memory_hints: Dict[str, Any] = {}
    if not hasattr(memory, "build_workflow_hints"):
        return memory_hints
    goal_statement = ""
    if isinstance(task.goal, dict):
        goal_statement = str(task.goal.get("statement", "")).strip()
    composed_goal = " ".join(chunk for chunk in [request.strip(), goal_statement] if chunk).strip()
    try:
        memory_hints = dict(memory.build_workflow_hints(goal=composed_goal, limit=12))
    except Exception:
        memory_hints = {}
    if memory_hints:
        files["memory_hints"] = store.write_json("memory-hints.json", memory_hints)
    return memory_hints


def collect_runtime_outputs(
    files: Dict[str, Any],
    store: Any,
    runtime_result: Any,
) -> None:
    files["artifact"] = runtime_result.artifact_path
    files["trace"] = store.path("trace.jsonl")
    files["evidence"] = store.path("evidence.jsonl")
    prompts = store.path("prompts.jsonl")
    if prompts.exists():
        files["prompts"] = prompts
    graph_workflow = store.path("graph-workflow-materialized.json")
    if graph_workflow.exists():
        files["graph_workflow_materialized"] = graph_workflow
    if runtime_result.agent_bus_path:
        files["agent_bus"] = runtime_result.agent_bus_path
