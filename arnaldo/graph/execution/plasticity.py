"""Registro de outcomes Hebbianos para arestas de execução."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import ExecutionEngine

from ..edges import EdgeKind, GraphEdge
from .context import SynapseExecutionResult


def _edge_success_from_result(result: SynapseExecutionResult | None) -> bool | None:
    if result is None:
        return None
    if result.degraded:
        return None
    return bool(result.success)


def _record_edge_outcome_between(
    engine: ExecutionEngine,
    *,
    source_id: str,
    target_id: str,
    kind: EdgeKind,
    success: bool,
    create_if_missing: bool,
) -> None:
    with engine._graph_lock:
        matched = False
        for edge in engine.graph.iter_edges_from(
            source_id,
            kinds=[kind],
            active_only=False,
        ):
            if edge.target_id != target_id:
                continue
            engine.graph.record_edge_outcome(edge.id, success=success)
            matched = True
        if matched or not create_if_missing:
            return
        new_edge = GraphEdge.connect(source_id, target_id, kind)
        engine.graph.add_edge(new_edge)
        engine.graph.record_edge_outcome(new_edge.id, success=success)


def _record_collaboration_edges(
    engine: ExecutionEngine,
    node_ids: list[str],
    *,
    success: bool,
) -> None:
    unique_ids = sorted({node_id for node_id in node_ids if node_id})
    if len(unique_ids) < 2:
        return
    for idx, left_id in enumerate(unique_ids):
        for right_id in unique_ids[idx + 1 :]:
            _record_edge_outcome_between(
                engine,
                source_id=left_id,
                target_id=right_id,
                kind=EdgeKind.COLLABORATED_WITH,
                success=success,
                create_if_missing=True,
            )
            _record_edge_outcome_between(
                engine,
                source_id=right_id,
                target_id=left_id,
                kind=EdgeKind.COLLABORATED_WITH,
                success=success,
                create_if_missing=True,
            )


def _record_path_transition_outcomes(
    engine: ExecutionEngine,
    path: list[str],
    results: list[SynapseExecutionResult],
) -> None:
    if len(path) < 2 or not results:
        return
    result_by_node = {result.node_id: result for result in results}
    for idx in range(1, len(path)):
        source_id = path[idx - 1]
        target_id = path[idx]
        target_result = result_by_node.get(target_id)
        success = _edge_success_from_result(target_result)
        if success is None:
            continue
        _record_edge_outcome_between(
            engine,
            source_id=source_id,
            target_id=target_id,
            kind=EdgeKind.ACTIVATES,
            success=success,
            create_if_missing=False,
        )


def _record_reachable_transition_outcomes(
    engine: ExecutionEngine,
    path: list[str],
    results: list[SynapseExecutionResult],
) -> None:
    if len(path) < 2 or not results:
        return
    order_by_node = {node_id: index for index, node_id in enumerate(path)}
    result_by_node = {result.node_id: result for result in results}
    with engine._graph_lock:
        for target_id in path:
            target_result = result_by_node.get(target_id)
            success = _edge_success_from_result(target_result)
            if success is None:
                continue
            target_index = order_by_node.get(target_id)
            if target_index is None:
                continue
            for edge in engine.graph.iter_edges_to(
                target_id,
                kinds=[EdgeKind.ACTIVATES],
                active_only=False,
            ):
                source_index = order_by_node.get(edge.source_id)
                if source_index is None:
                    continue
                if source_index >= target_index:
                    continue
                engine.graph.record_edge_outcome(edge.id, success=success)


def _record_level_transition_outcomes(
    engine: ExecutionEngine,
    previous_level: list[str],
    level_results: list[SynapseExecutionResult],
) -> None:
    if not previous_level or not level_results:
        return
    with engine._graph_lock:
        for result in level_results:
            success = _edge_success_from_result(result)
            if success is None:
                continue
            for source_id in previous_level:
                for edge in engine.graph.iter_edges_from(
                    source_id,
                    kinds=[EdgeKind.ACTIVATES],
                    active_only=False,
                ):
                    if edge.target_id != result.node_id:
                        continue
                    engine.graph.record_edge_outcome(edge.id, success=success)
