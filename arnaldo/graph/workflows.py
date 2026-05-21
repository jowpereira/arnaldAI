"""Utilidades para workflows composicionais sobre ``CognitiveGraph``.

Este módulo materializa workflow como ``SynapseNode`` orquestrador com sub-grafo
OWNED/SHARED, e permite composição workflow-of-workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import re

from .edges import EdgeKind, GraphEdge
from .nodes import SynapseNode
from .refs import GraphRef, GraphRefKind
from .store import CognitiveGraph


@dataclass(slots=True)
class WorkflowStepSpec:
    action: str
    agent_id: str
    output: str
    role: str = "operator"
    objective: str = ""
    tier_preference: str = "expert"
    capability_id: str | None = None
    module_path: str | None = None

    @classmethod
    def from_mapping(cls, item: dict[str, Any]) -> "WorkflowStepSpec":
        action = str(item.get("action", "")).strip()
        if not action:
            raise ValueError("workflow step sem action")
        output = str(item.get("output", "")).strip() or f"{action}_output"
        objective = str(item.get("objective", "")).strip() or f"executar etapa {action}"
        capability_id = str(item.get("capability_id", "")).strip() or None
        module_path = str(item.get("module_path", "")).strip() or None
        return cls(
            action=action,
            agent_id=str(item.get("agent_id", "operator")).strip() or "operator",
            output=output,
            role=str(item.get("role", "operator")).strip() or "operator",
            objective=objective,
            tier_preference=str(item.get("tier_preference", "expert")).strip() or "expert",
            capability_id=capability_id,
            module_path=module_path,
        )


def make_workflow(
    graph: CognitiveGraph,
    *,
    workflow_id: str,
    label: str,
    steps: Iterable[WorkflowStepSpec | dict[str, Any]],
    kind: GraphRefKind = GraphRefKind.OWNED,
    uri: Path | str | None = None,
) -> tuple[SynapseNode, CognitiveGraph, GraphRef]:
    """Materializa um workflow como synapse orquestrador + sub-grafo.

    O workflow é representado por:
    1. ``SynapseNode`` orquestrador no grafo pai.
    2. Sub-grafo com ``SynapseNode`` por step e arestas ``ACTIVATES`` em sequência.
    3. ``GraphRef`` conectando o orquestrador ao sub-grafo.
    """
    step_specs = _normalize_steps(steps)
    if not step_specs:
        raise ValueError("workflow sem steps")

    existing = graph.get_node(workflow_id)
    if isinstance(existing, SynapseNode):
        orchestrator = existing.with_payload_merge(
            role="orchestrator",
            objective=f"orquestrar workflow {label}",
            workflow_step_count=len(step_specs),
            workflow_kind=kind.value,
        )
        assert isinstance(orchestrator, SynapseNode)
        graph.add_node(orchestrator)
    else:
        orchestrator = SynapseNode.specialist(
            label=label,
            id=workflow_id,
            role="orchestrator",
            objective=f"orquestrar workflow {label}",
            epistemic_style="workflow_composition",
            tier_preference="expert",
            action="workflow_orchestrator",
            workflow_step_count=len(step_specs),
            workflow_kind=kind.value,
        )
        graph.add_node(orchestrator)

    subgraph = CognitiveGraph(registry=graph.registry)
    node_ids: list[str] = []
    for index, step in enumerate(step_specs, start=1):
        node_id = f"{workflow_id}__step_{index:02d}_{_slug(step.action)}"
        payload: dict[str, Any] = {
            "action": step.action,
            "agent_id": step.agent_id,
            "output": step.output,
        }
        if step.capability_id:
            payload["capability_id"] = step.capability_id
        if step.module_path:
            payload["module_path"] = step.module_path
        node = SynapseNode.specialist(
            label=f"{step.action}::{step.agent_id}",
            id=node_id,
            role=step.role,
            objective=step.objective,
            tier_preference=step.tier_preference,
            **payload,
        )
        subgraph.add_node(node)
        node_ids.append(node.id)

    for idx in range(1, len(node_ids)):
        subgraph.add_edge(
            GraphEdge.connect(
                source_id=node_ids[idx - 1],
                target_id=node_ids[idx],
                kind=EdgeKind.ACTIVATES,
                weight=max(0.35, 0.92 - (0.04 * idx)),
            )
        )

    ref = graph.attach_subgraph(
        orchestrator.id,
        subgraph,
        kind=kind,
        bridge_nodes=[node_ids[0], node_ids[-1]],
        uri=Path(uri) if uri is not None else None,
    )
    return orchestrator, subgraph, ref


def compose_workflows(
    graph: CognitiveGraph,
    *,
    composition_id: str,
    label: str,
    workflow_ids: Iterable[str],
) -> SynapseNode:
    """Compõe múltiplos workflows existentes em um meta-workflow.

    Regras:
    - cria synapse orquestrador de composição;
    - conecta workflows em cadeia via ``ACTIVATES``;
    - compartilha refs dos sub-grafos dos workflows filhos no orquestrador pai.
    """
    workflow_nodes = [graph.get_node(workflow_id) for workflow_id in workflow_ids]
    workflows = [node for node in workflow_nodes if isinstance(node, SynapseNode)]
    if len(workflows) < 2:
        raise ValueError("compose_workflows exige pelo menos 2 workflows válidos")

    existing = graph.get_node(composition_id)
    if isinstance(existing, SynapseNode):
        composed = existing.with_payload_merge(
            role="orchestrator",
            objective=f"compor workflows em {label}",
            composed_workflows=[node.id for node in workflows],
            action="workflow_composition",
        )
        assert isinstance(composed, SynapseNode)
        graph.add_node(composed)
    else:
        composed = SynapseNode.specialist(
            label=label,
            id=composition_id,
            role="orchestrator",
            objective=f"compor workflows em {label}",
            epistemic_style="workflow_composition",
            tier_preference="expert",
            action="workflow_composition",
            composed_workflows=[node.id for node in workflows],
        )
        graph.add_node(composed)

    for idx in range(1, len(workflows)):
        graph.add_edge(
            GraphEdge.connect(
                workflows[idx - 1].id,
                workflows[idx].id,
                EdgeKind.ACTIVATES,
                weight=max(0.40, 0.90 - (0.05 * idx)),
            )
        )

    first = workflows[0]
    last = workflows[-1]
    graph.add_edge(GraphEdge.connect(composed.id, first.id, EdgeKind.ACTIVATES, weight=0.93))
    graph.add_edge(GraphEdge.connect(last.id, composed.id, EdgeKind.DERIVED_FROM, weight=0.60))

    for workflow in workflows:
        for ref in workflow.subgraph_refs:
            subgraph = graph.resolve_subgraph(ref)
            if subgraph is None:
                continue
            try:
                graph.attach_subgraph(
                    composed.id,
                    subgraph,
                    kind=GraphRefKind.SHARED,
                    bridge_nodes=list(ref.bridge_nodes),
                    uri=Path(ref.uri) if ref.uri else None,
                )
            except ValueError:
                # SHARED pode ser anexado mais de uma vez ao mesmo grafo; duplicatas
                # exatas são ignoradas por ``GraphNode.attach_ref``.
                continue

    return composed


def _normalize_steps(steps: Iterable[WorkflowStepSpec | dict[str, Any]]) -> list[WorkflowStepSpec]:
    normalized: list[WorkflowStepSpec] = []
    for step in steps:
        if isinstance(step, WorkflowStepSpec):
            normalized.append(step)
            continue
        if isinstance(step, dict):
            normalized.append(WorkflowStepSpec.from_mapping(step))
            continue
        raise TypeError(f"step inválido para workflow: {type(step)!r}")
    return normalized


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    cleaned = cleaned.strip("_")
    return cleaned or "step"
