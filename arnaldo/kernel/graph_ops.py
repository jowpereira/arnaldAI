"""Operações de grafo cognitivo — sync de capabilities e pós-processamento."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from arnaldo.components import CapabilityRegistry
from arnaldo.contracts import Capability
from arnaldo.session import SessionManager, SessionState
from arnaldo.storage import RunStore
from arnaldo.utils.normalize import normalize_module_path as _normalize_module_path

from . import forge as _forge
from . import session as _session


def sync_capabilities_from_graph(
    capabilities: CapabilityRegistry,
    sessions: SessionManager,
    graph_path: Path,
    *,
    session: SessionState,
    run_id: str,
    task_id: str,
    store: RunStore,
) -> Tuple[Dict[str, Any], SessionState]:
    """Sincroniza capabilities do grafo de execução para o registry."""
    from arnaldo.graph import CapabilityNode, CognitiveGraph, NodeKind

    report: Dict[str, Any] = {"synced": [], "skipped": []}
    try:
        graph = CognitiveGraph.load(graph_path)
    except Exception as exc:
        report["error"] = str(exc)
        return report, session

    seen: set[str] = set()
    current = session
    for node in graph.iter_nodes(kind=NodeKind.CAPABILITY, active_only=False):
        if not isinstance(node, CapabilityNode):
            continue
        capability_id = str(node.payload.get("capability_id") or node.label).strip()
        if not capability_id:
            continue
        if capability_id in seen:
            continue
        seen.add(capability_id)

        if not capability_id.startswith(("connector.", "tool.", "search.")):
            report["skipped"].append({"id": capability_id, "reason": "non_dynamic_capability"})
            continue

        maturity = str(node.payload.get("maturity", node.maturity)).strip() or "draft"
        module_path = _normalize_module_path(node.payload.get("module_path"))
        real_execution_successes = _normalize_positive_int(
            node.payload.get("real_execution_successes")
        )
        last_tool_execution_status = str(node.payload.get("last_tool_execution_status", "")).strip()
        existing = capabilities.get(capability_id)
        if not module_path and existing is not None:
            module_path = _normalize_module_path(existing.policies.get("module_path"))
        if real_execution_successes <= 0 and existing is not None:
            real_execution_successes = _normalize_positive_int(
                existing.policies.get("real_execution_successes")
            )
        if not last_tool_execution_status and existing is not None:
            last_tool_execution_status = str(
                existing.policies.get("last_tool_execution_status", "")
            ).strip()
        health = _resolve_capability_health(
            maturity=maturity,
            last_tool_execution_status=last_tool_execution_status,
        )
        policies: Dict[str, Any] = {
            "requires_approval": False,
            "maturity": maturity,
            "source": "execution_graph",
            "graph_node_id": node.id,
        }
        if module_path:
            policies["module_path"] = module_path
        if real_execution_successes > 0:
            policies["real_execution_successes"] = real_execution_successes
        if last_tool_execution_status:
            policies["last_tool_execution_status"] = last_tool_execution_status
        capability = Capability(
            id=capability_id,
            name="Graph %s" % capability_id,
            description="Capability sincronizada do grafo de execução.",
            inputs={"payload": "object"},
            outputs={"status": "object", "data": "object"},
            risk={
                "level": str(node.payload.get("risk_level", "medium")),
                "health": health,
                "reasons": ["graph_runtime_sync"],
            },
            policies=policies,
        )
        capabilities.register(capability)
        item: Dict[str, Any] = {
            "id": capability_id,
            "maturity": maturity,
            "health": health,
            "graph_node_id": node.id,
        }
        if module_path:
            item["module_path"] = module_path
        if real_execution_successes > 0:
            item["real_execution_successes"] = real_execution_successes
        if last_tool_execution_status:
            item["last_tool_execution_status"] = last_tool_execution_status
        report["synced"].append(item)
        event_metadata: Dict[str, Any] = {"source": "graph_sync", "graph_node_id": node.id}
        if real_execution_successes > 0:
            event_metadata["real_execution_successes"] = real_execution_successes
        if last_tool_execution_status:
            event_metadata["last_tool_execution_status"] = last_tool_execution_status
        current = sessions.record_tool_event(
            current,
            capability_id=capability_id,
            status=maturity,
            metadata=event_metadata,
        )

    if report["synced"]:
        _session.evidence(
            store,
            run_id,
            task_id,
            "capability_graph_synced",
            "%d capabilities sincronizadas do grafo de execução." % len(report["synced"]),
            {"capabilities": report["synced"]},
        )

    return report, current


def _normalize_positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _resolve_capability_health(*, maturity: str, last_tool_execution_status: str) -> str:
    status = last_tool_execution_status.strip().lower()
    if status in {"failed", "error", "not_implemented", "fallback"}:
        return "degraded"
    return "stable" if maturity in {"tested", "trusted"} else "degraded"


def post_process_graph(
    capabilities: CapabilityRegistry,
    sessions: SessionManager,
    tool_forge: Any,
    execution_graph: Path,
    *,
    files: Dict[str, Any],
    session: SessionState,
    run_id: str,
    task: Any,
    store: RunStore,
    adaptive_plan: Any,
) -> SessionState:
    """Pós-processa grafo de execução: sync capabilities + auto-forge."""
    graph_sync_report, session = sync_capabilities_from_graph(
        capabilities,
        sessions,
        execution_graph,
        session=session,
        run_id=run_id,
        task_id=task.id,
        store=store,
    )
    graph_tool_forge_report: Dict[str, Any] = {
        "candidates": [],
        "created": [],
        "failed": [],
        "skipped": [],
    }
    if adaptive_plan.should_forge_tools:
        graph_tool_forge_report, session = _forge.auto_forge_graph_capabilities(
            tool_forge,
            capabilities,
            sessions,
            graph_path=execution_graph,
            sync_report=graph_sync_report,
            session=session,
            run_id=run_id,
            task_id=task.id,
            store=store,
        )
        if graph_tool_forge_report["created"] or graph_tool_forge_report["failed"]:
            graph_sync_report, session = sync_capabilities_from_graph(
                capabilities,
                sessions,
                execution_graph,
                session=session,
                run_id=run_id,
                task_id=task.id,
                store=store,
            )
    if graph_sync_report["synced"] or graph_sync_report["skipped"]:
        files["graph_capability_sync"] = store.write_json(
            "graph-capability-sync.json",
            graph_sync_report,
        )
    if (
        graph_tool_forge_report["candidates"]
        or graph_tool_forge_report["created"]
        or graph_tool_forge_report["failed"]
        or graph_tool_forge_report["skipped"]
    ):
        files["graph_tool_forge"] = store.write_json(
            "graph-tool-forge.json",
            graph_tool_forge_report,
        )
    return session
