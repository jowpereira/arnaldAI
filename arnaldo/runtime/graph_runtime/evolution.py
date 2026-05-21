"""Evolução de capabilities e orquestrador de workflow para o GraphRuntime."""

from __future__ import annotations

from typing import Any, Dict

from arnaldo.graph import (
    CapabilityNode,
    CognitiveGraph,
    EdgeKind,
    make_workflow,
)

from .capabilities import (
    _capability_weight_for_maturity,
)
from .nodes import _ensure_edge
from .infra import _env_positive_int, _slug


def _materialize_runtime_workflow_orchestrator(
    *,
    graph: CognitiveGraph,
    organization: Any,
    task: Any,
    workflow: list[Dict[str, Any]],
    path: list[str],
) -> None:
    if not workflow:
        return
    workflow_id = "synwf_%s_%s" % (
        _slug(str(getattr(organization, "id", "org"))),
        _slug(str(getattr(task, "id", "task"))),
    )
    try:
        orchestrator, _, _ = make_workflow(
            graph,
            workflow_id=workflow_id,
            label="workflow::%s" % str(getattr(organization, "topology", "dynamic")),
            steps=workflow,
        )
    except (ValueError, TypeError):
        return
    if not path:
        return
    _ensure_edge(
        graph=graph,
        source_id=orchestrator.id,
        target_id=path[0],
        kind=EdgeKind.ACTIVATES,
        weight=0.93,
    )
    _ensure_edge(
        graph=graph,
        source_id=path[-1],
        target_id=orchestrator.id,
        kind=EdgeKind.DERIVED_FROM,
        weight=0.65,
    )


def _should_skip_sequential_tooling_edge(
    source_item: Dict[str, Any],
    target_item: Dict[str, Any],
) -> bool:
    tooling_actions = {"design_tooling", "stabilize_tooling", "execute_tooling"}
    source_action = str(source_item.get("action", "")).strip()
    target_action = str(target_item.get("action", "")).strip()
    if source_action not in tooling_actions or target_action not in tooling_actions:
        return False
    source_capability = str(source_item.get("capability_id", "")).strip()
    target_capability = str(target_item.get("capability_id", "")).strip()
    if not source_capability or not target_capability:
        return False
    return source_capability != target_capability


def _evolve_capability_nodes(
    *,
    graph: CognitiveGraph,
    node_id: str,
    step_item: Dict[str, Any],
    exec_result: Any,
) -> None:
    action = str(step_item.get("action", ""))
    if action not in {"design_tooling", "stabilize_tooling", "execute_tooling"}:
        return
    if action in {"design_tooling", "stabilize_tooling"} and (
        not bool(exec_result.success) or bool(exec_result.fallback_used)
    ):
        return
    capability_id = str(step_item.get("capability_id", "")).strip()
    if not capability_id:
        return
    capability_node = graph.get_node("cap_%s" % _slug(capability_id))
    if not isinstance(capability_node, CapabilityNode):
        return

    base_node = capability_node
    if action == "execute_tooling":
        status = _tool_execution_status(exec_result.output)
        if not bool(exec_result.success) or bool(exec_result.fallback_used):
            degraded = _degrade_capability_after_tool_execution(
                capability_node,
                status or "failed",
            )
            graph.add_node(degraded)
            _ensure_edge(
                graph=graph,
                source_id=degraded.id,
                target_id=node_id,
                kind=EdgeKind.FORGED_BY,
                weight=0.6,
            )
            return
        if not _tool_execution_is_real(exec_result.output):
            degraded = _degrade_capability_after_tool_execution(
                capability_node,
                status or "not_implemented",
            )
            graph.add_node(degraded)
            _ensure_edge(
                graph=graph,
                source_id=degraded.id,
                target_id=node_id,
                kind=EdgeKind.FORGED_BY,
                weight=0.65,
            )
            return
        success_count = int(capability_node.payload.get("real_execution_successes", 0)) + 1
        updated_base = capability_node.with_payload_merge(
            real_execution_successes=success_count,
            last_tool_execution_status=status or "executed",
            state="available",
            risk_level="low",
        )
        if not isinstance(updated_base, CapabilityNode):
            return
        base_node = updated_base
        target_maturity = _target_maturity_for_tool_execution(base_node, success_count)
    else:
        target_maturity = "tested" if action == "design_tooling" else "trusted"

    promoted = _promote_capability_node(base_node, target_maturity=target_maturity)
    graph.add_node(promoted)
    _ensure_edge(
        graph=graph,
        source_id=promoted.id,
        target_id=node_id,
        kind=EdgeKind.FORGED_BY,
        weight=0.85
        if action == "stabilize_tooling"
        else (0.82 if action == "execute_tooling" else 0.75),
    )


def _tool_execution_is_real(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    status = str(output.get("status", "")).strip().lower()
    if not status:
        return False
    if status in {"not_implemented", "fallback", "failed", "error"}:
        return False
    return True


def _tool_execution_status(output: Any) -> str:
    if not isinstance(output, dict):
        return ""
    return str(output.get("status", "")).strip().lower()


def _degrade_capability_after_tool_execution(
    node: CapabilityNode,
    status: str,
) -> CapabilityNode:
    levels = [lvl for lvl in CapabilityNode.MATURITY_LEVELS if lvl != "deprecated"]
    current = str(node.maturity)
    if current not in levels:
        current = "draft"
    current_idx = levels.index(current)
    target_idx = max(0, current_idx - 1)
    demoted_maturity = levels[target_idx]
    current_successes = int(node.payload.get("real_execution_successes", 0))
    adjusted_successes = max(0, current_successes - 1)
    updated = node.with_payload_merge(
        maturity=demoted_maturity,
        state="degraded",
        risk_level="high" if status in {"failed", "error"} else "medium",
        last_tool_execution_status=status,
        real_execution_successes=adjusted_successes,
    )
    assert isinstance(updated, CapabilityNode)
    weighted = updated.with_weight(_capability_weight_for_maturity(updated.maturity))
    assert isinstance(weighted, CapabilityNode)
    return weighted


def _target_maturity_for_tool_execution(
    node: CapabilityNode,
    success_count: int,
) -> str:
    if node.maturity == "deprecated":
        return "deprecated"
    tested_threshold = _env_positive_int("ARNALDO_TOOL_EXEC_SUCCESSES_FOR_TESTED", default=2)
    trusted_threshold = _env_positive_int("ARNALDO_TOOL_EXEC_SUCCESSES_FOR_TRUSTED", default=4)
    if success_count >= max(trusted_threshold, tested_threshold):
        return "trusted"
    if success_count >= tested_threshold:
        return "tested"
    return node.maturity


def _promote_capability_node(
    node: CapabilityNode,
    *,
    target_maturity: str,
) -> CapabilityNode:
    levels = list(CapabilityNode.MATURITY_LEVELS)
    if node.maturity == "deprecated":
        return node
    if target_maturity not in levels:
        return node

    updated: CapabilityNode = node
    while (
        updated.maturity in levels
        and levels.index(updated.maturity) < levels.index(target_maturity)
        and updated.maturity != "trusted"
    ):
        promoted = updated.promote()
        assert isinstance(promoted, CapabilityNode)
        updated = promoted

    adjusted = updated.with_weight(_capability_weight_for_maturity(updated.maturity))
    assert isinstance(adjusted, CapabilityNode)
    return adjusted
