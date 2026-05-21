"""Auto-forge de capabilities a partir do grafo de execução."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Tuple

from arnaldo.components import CapabilityRegistry, ToolForge
from arnaldo.session import SessionManager, SessionState
from arnaldo.storage import RunStore
from arnaldo.utils.normalize import normalize_module_path as _normalize_module_path

from . import session as _session


def auto_forge_graph_capabilities(
    tool_forge: ToolForge,
    capabilities: CapabilityRegistry,
    sessions: SessionManager,
    *,
    graph_path: Path,
    sync_report: Dict[str, Any],
    session: SessionState,
    run_id: str,
    task_id: str,
    store: RunStore,
) -> Tuple[Dict[str, Any], SessionState]:
    """Executa forge automático para capabilities do grafo sem module_path."""
    report: Dict[str, Any] = {"candidates": [], "created": [], "failed": [], "skipped": []}
    candidates: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in sync_report.get("synced", []) or []:
        capability_id = str(item.get("id", "")).strip()
        if not capability_id:
            continue
        if capability_id in seen:
            continue
        seen.add(capability_id)
        if not capability_id.startswith(("connector.", "tool.")):
            continue

        maturity = str(item.get("maturity", "")).strip().lower() or "draft"
        module_path = _normalize_module_path(item.get("module_path"))
        existing = capabilities.get(capability_id)
        if not module_path and existing is not None:
            module_path = _normalize_module_path(existing.policies.get("module_path"))
        if module_path:
            report["skipped"].append({"id": capability_id, "reason": "module_path_already_known"})
            continue

        report["candidates"].append({"id": capability_id, "maturity": maturity})
        candidates.append(
            {
                "id": capability_id,
                "reason": "graph_capability_missing_module",
                "severity": "medium",
            }
        )

    if not candidates:
        return report, session

    forge = tool_forge.forge_missing(copy.deepcopy(candidates), session.id)
    current = session
    for capability in forge["capabilities"]:
        capabilities.register(capability)
    report["created"] = list(forge["created"])
    report["failed"] = list(forge["failed"])

    for item in report["created"]:
        _session.evidence(
            store,
            run_id,
            task_id,
            "graph_tool_forged",
            "tool_forge do grafo criou scaffold para %s" % item["capability_id"],
            {
                "capability_id": item["capability_id"],
                "module_path": item.get("module_path", ""),
                "status": item.get("status", ""),
            },
        )
        current = sessions.record_tool_event(
            current,
            capability_id=item["capability_id"],
            status=item.get("status", "draft"),
            metadata={
                "source": "graph_tool_forge",
                "module_path": item.get("module_path", ""),
            },
        )

    for item in report["failed"]:
        _session.evidence(
            store,
            run_id,
            task_id,
            "graph_tool_forge_failed",
            "tool_forge do grafo falhou para %s" % item["capability_id"],
            {
                "capability_id": item["capability_id"],
                "error": item.get("error", ""),
            },
        )
        current = sessions.record_tool_event(
            current,
            capability_id=item["capability_id"],
            status="failed",
            metadata={"source": "graph_tool_forge", "error": item.get("error", "")},
        )

    if report["created"]:
        report["graph_update"] = apply_forge_results_to_graph(
            graph_path=graph_path,
            created=report["created"],
        )

    return report, current


def apply_forge_results_to_graph(
    *,
    graph_path: Path,
    created: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Atualiza nós de capability no grafo com resultados do forge."""
    from arnaldo.graph import CapabilityNode, CognitiveGraph, NodeKind

    report: Dict[str, Any] = {"updated": [], "missing": []}
    try:
        graph = CognitiveGraph.load(graph_path)
    except Exception as exc:
        report["error"] = str(exc)
        return report

    by_capability: Dict[str, Dict[str, Any]] = {}
    for item in created:
        capability_id = str(item.get("capability_id", "")).strip()
        if capability_id:
            by_capability[capability_id] = item

    touched: set[str] = set()
    for node in graph.iter_nodes(kind=NodeKind.CAPABILITY, active_only=False):
        if not isinstance(node, CapabilityNode):
            continue
        capability_id = str(node.payload.get("capability_id") or node.label).strip()
        metadata = by_capability.get(capability_id)
        if metadata is None:
            continue
        module_path = _normalize_module_path(metadata.get("module_path"))
        maturity = str(metadata.get("status", "draft")).strip().lower() or "draft"
        if maturity not in set(CapabilityNode.MATURITY_LEVELS):
            maturity = "draft"
        updated = node.with_payload_merge(
            module_path=module_path,
            maturity=maturity,
            risk_level="low" if maturity in {"tested", "trusted"} else "medium",
            state="available",
        )
        assert isinstance(updated, CapabilityNode)
        graph.add_node(updated)
        touched.add(capability_id)
        report["updated"].append(
            {
                "id": capability_id,
                "graph_node_id": node.id,
                "module_path": module_path,
                "maturity": maturity,
            }
        )

    for capability_id in sorted(by_capability.keys()):
        if capability_id not in touched:
            report["missing"].append({"id": capability_id, "reason": "capability_node_not_found"})

    graph.persist(graph_path)
    return report
