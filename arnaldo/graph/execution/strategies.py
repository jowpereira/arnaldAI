"""Estratégias de execução: cadeia, alcançável e paralela."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import ExecutionEngine

from ..edges import EdgeKind
from ..nodes import NodeStatus, SynapseNode

# Threshold mínimo de peso para um synapse ser executável (gating neural)
WEIGHT_GATE_THRESHOLD = 0.10


def _resolve_runnable_synapse(
    engine: ExecutionEngine,
    node_id: str,
    *,
    allowed_node_ids: set[str] | None = None,
) -> SynapseNode | None:
    if allowed_node_ids is not None and node_id not in allowed_node_ids:
        return None
    node = engine.graph.get_node(node_id)
    if not isinstance(node, SynapseNode):
        return None
    if node.status in {NodeStatus.STALE, NodeStatus.ARCHIVED}:
        return None
    # Weight gating: synapse com peso abaixo do threshold é skipado
    if node.weight < WEIGHT_GATE_THRESHOLD:
        return None
    # INHIBITS gating: se há edge INHIBITS forte apontando para este nó, skip
    inhibit_edges = list(engine.graph.iter_edges_to(node_id, kinds=[EdgeKind.INHIBITS]))
    if any(e.weight >= 0.7 for e in inhibit_edges):
        return None
    return node


def plan_activates_path(
    engine: ExecutionEngine,
    root_synapse_id: str,
    *,
    max_steps: int = 16,
    allowed_node_ids: set[str] | None = None,
) -> list[str]:
    if max_steps < 1:
        raise ValueError("max_steps deve ser >= 1")
    if engine.graph.get_node(root_synapse_id) is None:
        raise KeyError(f"SynapseNode '{root_synapse_id}' não encontrado")
    if (
        _resolve_runnable_synapse(engine, root_synapse_id, allowed_node_ids=allowed_node_ids)
        is None
    ):
        return []

    path: list[str] = [root_synapse_id]
    visited: set[str] = {root_synapse_id}
    current = root_synapse_id

    while len(path) < max_steps:
        candidates = []
        for edge in engine.graph.iter_edges_from(current, kinds=[EdgeKind.ACTIVATES]):
            if edge.target_id in visited:
                continue
            target = _resolve_runnable_synapse(
                engine,
                edge.target_id,
                allowed_node_ids=allowed_node_ids,
            )
            if target is None:
                continue
            candidates.append((edge.weight, target.id))
        if not candidates:
            break
        candidates.sort(key=lambda item: item[0], reverse=True)
        next_id = candidates[0][1]
        path.append(next_id)
        visited.add(next_id)
        current = next_id

    return path


def plan_activates_reachable(
    engine: ExecutionEngine,
    root_synapse_id: str,
    *,
    max_steps: int = 64,
    allowed_node_ids: set[str] | None = None,
) -> list[str]:
    """Planeja ordem de execução BFS de todos os nós alcançáveis por ACTIVATES."""
    if max_steps < 1:
        raise ValueError("max_steps deve ser >= 1")
    if engine.graph.get_node(root_synapse_id) is None:
        raise KeyError(f"SynapseNode '{root_synapse_id}' não encontrado")
    if (
        _resolve_runnable_synapse(engine, root_synapse_id, allowed_node_ids=allowed_node_ids)
        is None
    ):
        return []

    order: list[str] = []
    queue: list[str] = [root_synapse_id]
    seen: set[str] = set()

    while queue and len(order) < max_steps:
        current = queue.pop(0)
        if current in seen:
            continue
        node = _resolve_runnable_synapse(
            engine,
            current,
            allowed_node_ids=allowed_node_ids,
        )
        if node is None:
            continue
        seen.add(current)
        order.append(current)

        children: list[tuple[float, str]] = []
        for edge in engine.graph.iter_edges_from(current, kinds=[EdgeKind.ACTIVATES]):
            target = _resolve_runnable_synapse(
                engine,
                edge.target_id,
                allowed_node_ids=allowed_node_ids,
            )
            if target is None:
                continue
            if target.id in seen:
                continue
            children.append((edge.weight, target.id))
        children.sort(key=lambda item: item[0], reverse=True)
        queue.extend([target_id for _, target_id in children])

    return order


def plan_activates_levels(
    engine: ExecutionEngine,
    root_synapse_id: str,
    *,
    max_steps: int = 64,
    allowed_node_ids: set[str] | None = None,
) -> list[list[str]]:
    """Planeja níveis BFS de ACTIVATES para execução com paralelismo por camada."""
    if max_steps < 1:
        raise ValueError("max_steps deve ser >= 1")
    if engine.graph.get_node(root_synapse_id) is None:
        raise KeyError(f"SynapseNode '{root_synapse_id}' não encontrado")
    if (
        _resolve_runnable_synapse(engine, root_synapse_id, allowed_node_ids=allowed_node_ids)
        is None
    ):
        return []

    levels: list[list[str]] = []
    seen: set[str] = set()
    current_level: list[str] = [root_synapse_id]
    total = 0

    while current_level and total < max_steps:
        normalized_level: list[str] = []
        for node_id in current_level:
            if node_id in seen:
                continue
            node = _resolve_runnable_synapse(
                engine,
                node_id,
                allowed_node_ids=allowed_node_ids,
            )
            if node is not None:
                normalized_level.append(node_id)
        if not normalized_level:
            break

        levels.append(normalized_level)
        total += len(normalized_level)
        for node_id in normalized_level:
            seen.add(node_id)

        next_candidates: list[tuple[float, str]] = []
        for parent_id in normalized_level:
            for edge in engine.graph.iter_edges_from(parent_id, kinds=[EdgeKind.ACTIVATES]):
                target = _resolve_runnable_synapse(
                    engine,
                    edge.target_id,
                    allowed_node_ids=allowed_node_ids,
                )
                if target is None:
                    continue
                if target.id in seen:
                    continue
                next_candidates.append((edge.weight, target.id))

        next_candidates.sort(key=lambda item: item[0], reverse=True)
        dedup: set[str] = set()
        next_level: list[str] = []
        for _, node_id in next_candidates:
            if node_id in dedup:
                continue
            dedup.add(node_id)
            next_level.append(node_id)
        current_level = next_level

    return levels


# Re-exports para compatibilidade (implementações movidas para executors.py)
from .executors import (  # noqa: F401, E402
    execute_activates_chain,
    execute_activates_reachable,
    execute_activates_parallel,
)

__all__ = [
    "WEIGHT_GATE_THRESHOLD",
    "plan_activates_path",
    "plan_activates_reachable",
    "plan_activates_levels",
    "execute_activates_chain",
    "execute_activates_reachable",
    "execute_activates_parallel",
]
