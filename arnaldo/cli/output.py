"""Funções de saída/impressão para a CLI."""

from __future__ import annotations

from typing import Any

from .builders import build_agent_response_preview, build_chat_response
from .utils import (
    as_int,
    count_by_key,
    duration_from_trace,
    safe_read_json,
    safe_read_jsonl,
    sorted_counts,
)


def print_chat_result(result: Any) -> None:
    response = build_chat_response(result)
    if response:
        print(f"arnaldo> {response}")
    else:
        print("arnaldo> (sem resposta legivel)")
    print("")


def print_run_result(result: Any, compact: bool = False) -> None:
    summary = build_run_summary(result)
    agent_response = build_agent_response_preview(result)
    print("=" * 72)
    print("ARNALDO - EXECUCAO CONCLUIDA")
    print("=" * 72)
    print(f"Run ID        : {result.run_id}")
    print(f"Session       : {result.session_id or '-'}")
    print(f"Run Dir       : {result.run_dir}")
    print(f"Topologia     : {summary['topology']}")
    print(f"Execucao      : {summary['execution_mode']}")
    if summary["duration_seconds"] is not None:
        print(f"Duracao       : {summary['duration_seconds']:.2f}s")
    print("-" * 72)
    print(
        "Workflow      : %d planejados | %d executados"
        % (summary["planned_steps"], summary["executed_steps"])
    )
    print(
        "Evidencias    : %d total | recusas=%d | erros=%d | degraded=%d"
        % (
            summary["evidence_total"],
            summary["refusal_count"],
            summary["error_count"],
            summary["degraded_count"],
        )
    )
    print(
        "Capabilities  : available=%d | missing=%d | degraded=%d"
        % (
            summary["capabilities_available"],
            summary["capabilities_missing"],
            summary["capabilities_degraded"],
        )
    )
    if summary["tool_forge_created"] or summary["tool_forge_failed"]:
        print(
            "Tool Forge    : created=%d | failed=%d"
            % (summary["tool_forge_created"], summary["tool_forge_failed"])
        )
    if summary["graph_capability_synced"] or summary["graph_capability_sync_skipped"]:
        print(
            "Graph Sync    : synced=%d | skipped=%d"
            % (summary["graph_capability_synced"], summary["graph_capability_sync_skipped"])
        )
    print("-" * 72)
    print(f"Artifact      : {summary['artifact_path']}")
    print(f"Evidence      : {summary['evidence_path']}")
    print(f"Trace         : {summary['trace_path']}")
    if summary["prompts_path"]:
        print(f"Prompts       : {summary['prompts_path']}")
    print("-" * 72)
    print("Resposta do Agente")
    if agent_response:
        print(agent_response)
    else:
        print("(vazia - artifact sem secao legivel)")

    if compact:
        print("=" * 72)
        return

    if summary["evidence_by_type"]:
        print("-" * 72)
        print("Evidence by Type")
        for record_type, count in summary["evidence_by_type"].items():
            print(f"- {record_type}: {count}")

    if summary["trace_by_event"]:
        print("-" * 72)
        print("Trace by Event")
        for event_type, count in summary["trace_by_event"].items():
            print(f"- {event_type}: {count}")

    print("-" * 72)
    print("Arquivos da Run")
    for key in sorted(result.files.keys()):
        print(f"- {key}: {result.files[key]}")
    print("=" * 72)


def print_runtime_error(exc: Exception) -> None:
    message = str(exc).strip() or repr(exc)
    body = str(getattr(exc, "body", "") or "").strip()
    if body:
        compact_body = " ".join(body.split())
        if len(compact_body) > 320:
            compact_body = compact_body[:320].rstrip() + "..."
    else:
        compact_body = ""
    print("=" * 72)
    print("ERRO DE EXECUCAO (modo real, strict)")
    print("=" * 72)
    print(f"Tipo          : {exc.__class__.__name__}")
    print(f"Mensagem      : {message}")
    if compact_body:
        print(f"Detalhe       : {compact_body}")
    print("-" * 72)
    print("Checklist rapido")
    print("- Configure LLM Azure no ambiente (.env) com endpoint, key e model/deployment.")
    print("- Verifique conectividade com a Azure OpenAI.")
    print("- Confirme se o deployment/tier requisitado existe e aceita requests.")
    print("- Se o erro for refusal, revise o pedido para reduzir bloqueios de safety.")
    print("=" * 72)


def build_run_summary(result: Any) -> dict[str, Any]:
    files = dict(result.files or {})
    organization = safe_read_json(files.get("organization_ir"))
    workflow = safe_read_json(files.get("graph_workflow_materialized"))
    capability_resolution = safe_read_json(files.get("capability_resolution"))
    graph_tool_forge = safe_read_json(files.get("graph_tool_forge"))
    graph_capability_sync = safe_read_json(files.get("graph_capability_sync"))
    trace = safe_read_jsonl(files.get("trace"))
    evidence = safe_read_jsonl(files.get("evidence"))

    trace_by_event = sorted_counts(count_by_key(trace, "event_type"))
    evidence_by_type = sorted_counts(count_by_key(evidence, "record_type"))

    planned_steps = as_int(workflow.get("step_count"))
    executed_steps = as_int(trace_by_event.get("step_completed"))
    duration_seconds = duration_from_trace(trace)

    return {
        "topology": str(workflow.get("topology") or organization.get("topology") or "-"),
        "execution_mode": str(workflow.get("execution_mode") or "-"),
        "planned_steps": planned_steps,
        "executed_steps": executed_steps,
        "evidence_total": len(evidence),
        "refusal_count": as_int(evidence_by_type.get("llm_refusal")),
        "error_count": as_int(evidence_by_type.get("step_failed")),
        "degraded_count": as_int(evidence_by_type.get("step_degraded")),
        "capabilities_available": len(capability_resolution.get("available", []) or []),
        "capabilities_missing": len(capability_resolution.get("missing", []) or []),
        "capabilities_degraded": len(capability_resolution.get("degraded", []) or []),
        "tool_forge_created": len(graph_tool_forge.get("created", []) or []),
        "tool_forge_failed": len(graph_tool_forge.get("failed", []) or []),
        "graph_capability_synced": len(graph_capability_sync.get("synced", []) or []),
        "graph_capability_sync_skipped": len(graph_capability_sync.get("skipped", []) or []),
        "duration_seconds": duration_seconds,
        "artifact_path": str(files.get("artifact") or files.get("response") or ""),
        "evidence_path": str(files.get("evidence", "")),
        "trace_path": str(files.get("trace", "")),
        "prompts_path": str(files.get("prompts", "")),
        "evidence_by_type": evidence_by_type,
        "trace_by_event": trace_by_event,
    }
