"""Operações de nó, aresta e memória no grafo para o GraphRuntime."""

from __future__ import annotations

from typing import Any, Dict

from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
    GraphEdge,
    MemoryNode,
    NodeKind,
    NodeStatus,
    SourceRecord,
    SynapseNode,
)

from .infra import _normalize_positive_float, _result_summary, _slug


def _upsert_synapse_node(
    *,
    graph: CognitiveGraph,
    node_id: str,
    label: str,
    role: str,
    objective: str,
    output_contract: Dict[str, Any],
    output_contract_model: type[Any],
    tier_preference: str,
    metadata: Dict[str, Any],
) -> SynapseNode:
    existing = graph.get_node(node_id)
    if isinstance(existing, SynapseNode):
        updated = existing.with_status(NodeStatus.ACTIVE).with_payload_merge(
            role=role,
            objective=objective,
            output_contract=output_contract,
            output_contract_model=output_contract_model.__name__,
            output_schema=existing.payload.get("output_schema"),
            tier_preference=tier_preference,
            **metadata,
        )
        assert isinstance(updated, SynapseNode)
        graph.add_node(updated)
        return updated

    synapse = SynapseNode.specialist(
        label=label,
        id=node_id,
        role=role,
        objective=objective,
        output_contract=output_contract,
        output_contract_model=output_contract_model,
        tier_preference=tier_preference,
        **metadata,
    )
    graph.add_node(synapse)
    return synapse


def _ensure_edge(
    *,
    graph: CognitiveGraph,
    source_id: str,
    target_id: str,
    kind: EdgeKind,
    weight: float,
) -> None:
    for edge in graph.iter_edges_from(source_id, kinds=[kind]):
        if edge.target_id == target_id:
            return
    graph.add_edge(
        GraphEdge.connect(
            source_id,
            target_id,
            kind,
            weight=weight,
        )
    )


def _record_step_memory(
    *,
    graph: CognitiveGraph,
    run_id: str,
    node_id: str,
    step_item: Dict[str, Any],
    result_payload: Dict[str, Any],
    previous_memory_id: str | None = None,
) -> str:
    memory_id = "mem_%s_%s" % (_slug(run_id), _slug(step_item["id"]))
    if graph.get_node(memory_id) is None:
        summary = _result_summary(result_payload)
        memory = MemoryNode.semantic(
            label="%s :: %s" % (step_item["action"], summary),
            id=memory_id,
            source=SourceRecord.from_run(run_id, agent=step_item["agent_id"]),
            domain="procedural",
            payload={
                "step_id": step_item["id"],
                "agent_id": step_item["agent_id"],
                "action": step_item["action"],
                "capability_id": str(step_item.get("capability_id", "")).strip(),
                "channel": "tool" if step_item["action"] == "execute_tooling" else "llm",
                "output_name": step_item["output"],
                "result": result_payload,
            },
        )
        graph.add_node(memory)
    capability_id = str(step_item.get("capability_id", "")).strip()
    _ensure_edge(
        graph=graph,
        source_id=node_id,
        target_id=memory_id,
        kind=EdgeKind.MENTIONS,
        weight=0.6,
    )
    if (
        previous_memory_id
        and previous_memory_id != memory_id
        and graph.get_node(previous_memory_id)
    ):
        _ensure_edge(
            graph=graph,
            source_id=previous_memory_id,
            target_id=memory_id,
            kind=EdgeKind.TEMPORAL_BEFORE,
            weight=0.72,
        )
    if capability_id:
        for candidate in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False):
            if candidate.id == memory_id:
                continue
            payload = candidate.payload if isinstance(candidate.payload, dict) else {}
            if str(payload.get("capability_id", "")).strip() != capability_id:
                continue
            _ensure_edge(
                graph=graph,
                source_id=candidate.id,
                target_id=memory_id,
                kind=EdgeKind.SEMANTIC,
                weight=0.58,
            )
    return memory_id


def _ensure_branch(
    *,
    graph: CognitiveGraph,
    source_action: str,
    target_action: str,
    node_ids_by_action: Dict[str, list[str]],
    step_by_node: Dict[str, Dict[str, Any]],
    weight: float,
) -> None:
    source_ids = list(node_ids_by_action.get(source_action) or [])
    target_ids = list(node_ids_by_action.get(target_action) or [])
    if not source_ids or not target_ids:
        return
    for source_id in source_ids:
        source_item = step_by_node.get(source_id, {})
        source_capability = str(source_item.get("capability_id", "")).strip()
        preferred_targets: list[str] = []
        if source_capability:
            preferred_targets = [
                target_id
                for target_id in target_ids
                if str(step_by_node.get(target_id, {}).get("capability_id", "")).strip()
                == source_capability
            ]
        selected_targets = preferred_targets or target_ids
        for target_id in selected_targets:
            _ensure_edge(
                graph=graph,
                source_id=source_id,
                target_id=target_id,
                kind=EdgeKind.ACTIVATES,
                weight=weight,
            )


def _ensure_dynamic_branches(
    *,
    graph: CognitiveGraph,
    node_ids_by_action: Dict[str, list[str]],
    step_by_node: Dict[str, Dict[str, Any]],
) -> None:
    links = [
        ("frame_intent", "clarify_uncertainties", 0.92),
        ("clarify_uncertainties", "explore_path_a", 0.88),
        ("clarify_uncertainties", "explore_path_b", 0.88),
        ("clarify_uncertainties", "decompose_work", 0.88),
        ("clarify_uncertainties", "stabilize_tooling", 0.84),
        ("clarify_uncertainties", "execute_tooling", 0.82),
        ("decompose_work", "design_tooling", 0.86),
        ("decompose_work", "stabilize_tooling", 0.84),
        ("decompose_work", "execute_tooling", 0.82),
        ("explore_path_a", "design_tooling", 0.84),
        ("explore_path_b", "design_tooling", 0.84),
        ("explore_path_a", "stabilize_tooling", 0.82),
        ("explore_path_b", "stabilize_tooling", 0.82),
        ("explore_path_a", "execute_tooling", 0.8),
        ("explore_path_b", "execute_tooling", 0.8),
        ("design_tooling", "stabilize_tooling", 0.86),
        ("design_tooling", "execute_tooling", 0.88),
        ("design_tooling", "compose_tooling", 0.87),
        ("design_tooling", "synthesize_artifact", 0.86),
        ("design_tooling", "draft_artifact", 0.86),
        ("stabilize_tooling", "execute_tooling", 0.9),
        ("stabilize_tooling", "compose_tooling", 0.88),
        ("stabilize_tooling", "synthesize_artifact", 0.86),
        ("stabilize_tooling", "draft_artifact", 0.86),
        ("execute_tooling", "compose_tooling", 0.91),
        ("execute_tooling", "synthesize_artifact", 0.9),
        ("execute_tooling", "draft_artifact", 0.9),
        ("execute_tooling", "critic_review", 0.86),
        ("compose_tooling", "synthesize_artifact", 0.91),
        ("compose_tooling", "draft_artifact", 0.9),
        ("compose_tooling", "critic_review", 0.88),
        ("compose_tooling", "risk_review", 0.86),
        ("compose_tooling", "decision_synthesis", 0.86),
        ("draft_artifact", "critic_review", 0.85),
        ("synthesize_artifact", "critic_review", 0.85),
        ("critic_review", "risk_review", 0.83),
        ("risk_review", "decision_synthesis", 0.9),
        ("critic_review", "decision_synthesis", 0.82),
    ]
    for source_action, target_action, weight in links:
        _ensure_branch(
            graph=graph,
            source_action=source_action,
            target_action=target_action,
            node_ids_by_action=node_ids_by_action,
            step_by_node=step_by_node,
            weight=weight,
        )


def _reinforce_memory_transitions(
    *,
    graph: CognitiveGraph,
    node_ids_by_action: Dict[str, list[str]],
    step_by_node: Dict[str, Dict[str, Any]],
    memory_hints: Dict[str, Any],
) -> None:
    transitions = memory_hints.get("transitions", []) if isinstance(memory_hints, dict) else []
    if not isinstance(transitions, list):
        return
    for item in transitions:
        if not isinstance(item, dict):
            continue
        source_action = str(item.get("source_action", "")).strip()
        target_action = str(item.get("target_action", "")).strip()
        if not source_action or not target_action:
            continue
        if source_action == target_action:
            continue
        score = _normalize_positive_float(item.get("score"))
        if score <= 0:
            continue
        normalized_weight = max(0.45, min(0.95, 0.45 + (0.15 * score)))
        _ensure_branch(
            graph=graph,
            source_action=source_action,
            target_action=target_action,
            node_ids_by_action=node_ids_by_action,
            step_by_node=step_by_node,
            weight=normalized_weight,
        )
