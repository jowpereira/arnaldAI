"""Construção do grafo de execução para o GraphRuntime."""

from __future__ import annotations

from typing import Any, Dict

from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
)

from .classify import (
    _default_objective_for_action,
    _default_role_for_action,
)
from .models import (
    ACTION_CAPABILITY_HINTS,
    ACTION_MODEL_MAP,
    GenericStepOutput,
    ROLE_TIER_PREFERENCE,
)
from .capabilities import (
    _collect_capability_state,
    _upsert_capability_node,
)
from .nodes import (
    _ensure_branch,
    _ensure_dynamic_branches,
    _ensure_edge,
    _reinforce_memory_transitions,
    _upsert_synapse_node,
)
from .evolution import (
    _materialize_runtime_workflow_orchestrator,
    _should_skip_sequential_tooling_edge,
)
from .workflow import _materialize_runtime_workflow
from .infra import _synapse_node_id
from arnaldo.llm import ContractModelRegistry


def _build_execution_graph(
    contract_registry: ContractModelRegistry,
    organization: Any,
    *,
    task: Any,
    capability_resolution: Dict[str, Any],
    memory_hints: Dict[str, Any] | None = None,
    graph: CognitiveGraph | None = None,
) -> tuple[CognitiveGraph, dict[str, dict[str, Any]], list[str]]:
    graph = graph or CognitiveGraph()
    step_by_node: dict[str, dict[str, Any]] = {}
    path: list[str] = []

    agent_by_id = {agent.id: agent for agent in organization.agents}
    workflow = _materialize_runtime_workflow(
        organization=organization,
        task=task,
        capability_resolution=capability_resolution,
    )
    capability_state = _collect_capability_state(task, capability_resolution, organization)
    capability_node_by_capability: dict[str, str] = {}
    for capability_id, state in capability_state.items():
        capability_node = _upsert_capability_node(
            graph,
            capability_id,
            state=state.get("state", "missing"),
            maturity_hint=state.get("maturity"),
        )
        capability_node_by_capability[capability_id] = capability_node.id

    node_ids_by_action: dict[str, list[str]] = {}
    for item in workflow:
        agent = agent_by_id.get(item["agent_id"])
        model = ACTION_MODEL_MAP.get(item["action"], GenericStepOutput)
        contract_registry.register(model, name=model.__name__)
        role = agent.role if agent is not None else _default_role_for_action(item["action"])
        objective = str(item.get("objective", "")).strip() or (
            agent.objective
            if agent is not None
            else _default_objective_for_action(item["action"], item)
        )
        output_contract = item.get("output_contract")
        if not isinstance(output_contract, dict) or not output_contract:
            output_contract = (
                agent.output_contract
                if agent is not None
                else {
                    "schema": "generic_step_output",
                    "required_sections": ["status", "evidence", "uncertainties"],
                }
            )
        metadata = {
            "step_id": item["id"],
            "action": item["action"],
            "output": item["output"],
            "agent_id": item["agent_id"],
        }
        if item.get("capability_id"):
            metadata["capability_id"] = str(item["capability_id"])
        if item.get("module_path"):
            metadata["module_path"] = str(item["module_path"])
        if item.get("max_tokens"):
            metadata["max_tokens"] = int(item["max_tokens"])
        if item.get("timeout"):
            metadata["timeout"] = float(item["timeout"])
        if item.get("temperature") is not None:
            metadata["temperature"] = float(item["temperature"])
        if item.get("max_retries"):
            metadata["max_retries"] = int(item["max_retries"])
        if item.get("retry_attempts"):
            metadata["retry_attempts"] = int(item["retry_attempts"])
        if item.get("reasoning_effort"):
            metadata["reasoning_effort"] = str(item["reasoning_effort"])
        if item.get("reasoning_summary"):
            metadata["reasoning_summary"] = str(item["reasoning_summary"])
        synapse = _upsert_synapse_node(
            graph=graph,
            node_id=_synapse_node_id(
                item["agent_id"],
                item["action"],
                item.get("output"),
            ),
            label=f"{item['action']}::{item['agent_id']}",
            role=role,
            objective=objective,
            output_contract=output_contract,
            output_contract_model=model,
            tier_preference=str(
                item.get("tier_preference") or ROLE_TIER_PREFERENCE.get(role, "expert")
            ),
            metadata=metadata,
        )
        if synapse.id not in step_by_node:
            step_by_node[synapse.id] = item
            path.append(synapse.id)
        elif not step_by_node[synapse.id].get("capability_id") and item.get("capability_id"):
            step_by_node[synapse.id]["capability_id"] = item["capability_id"]
        node_ids_by_action.setdefault(item["action"], [])
        if synapse.id not in node_ids_by_action[item["action"]]:
            node_ids_by_action[item["action"]].append(synapse.id)

        # Liga synapse às capabilities mais prováveis para aquele step.
        hinted_capabilities = list(ACTION_CAPABILITY_HINTS.get(item["action"], []))
        if item.get("capability_id"):
            hinted_capabilities.append(str(item["capability_id"]))
        for capability_id in hinted_capabilities:
            cap_node_id = capability_node_by_capability.get(capability_id)
            if cap_node_id is None:
                capability_node = _upsert_capability_node(
                    graph,
                    capability_id,
                    state="missing",
                    maturity_hint=None,
                )
                capability_node_by_capability[capability_id] = capability_node.id
                cap_node_id = capability_node.id
            if cap_node_id:
                _ensure_edge(
                    graph=graph,
                    source_id=synapse.id,
                    target_id=cap_node_id,
                    kind=EdgeKind.REQUIRES,
                    weight=0.9,
                )

    # Conectividade base: sequência do workflow declarado.
    for idx in range(1, len(path)):
        source_id = path[idx - 1]
        target_id = path[idx]
        if _should_skip_sequential_tooling_edge(
            step_by_node.get(source_id, {}),
            step_by_node.get(target_id, {}),
        ):
            continue
        _ensure_edge(
            graph=graph,
            source_id=source_id,
            target_id=target_id,
            kind=EdgeKind.ACTIVATES,
            weight=max(0.3, 1.0 - (idx * 0.05)),
        )

    # Topologia paralela explícita: frame -> {a,b} -> synthesize.
    if organization.topology == "parallel_with_synthesis":
        _ensure_branch(
            graph=graph,
            source_action="frame_intent",
            target_action="explore_path_a",
            node_ids_by_action=node_ids_by_action,
            step_by_node=step_by_node,
            weight=0.95,
        )
        _ensure_branch(
            graph=graph,
            source_action="frame_intent",
            target_action="explore_path_b",
            node_ids_by_action=node_ids_by_action,
            step_by_node=step_by_node,
            weight=0.95,
        )
        _ensure_branch(
            graph=graph,
            source_action="explore_path_a",
            target_action="synthesize_artifact",
            node_ids_by_action=node_ids_by_action,
            step_by_node=step_by_node,
            weight=0.9,
        )
        _ensure_branch(
            graph=graph,
            source_action="explore_path_b",
            target_action="synthesize_artifact",
            node_ids_by_action=node_ids_by_action,
            step_by_node=step_by_node,
            weight=0.9,
        )

    _ensure_dynamic_branches(
        graph=graph,
        node_ids_by_action=node_ids_by_action,
        step_by_node=step_by_node,
    )
    _reinforce_memory_transitions(
        graph=graph,
        node_ids_by_action=node_ids_by_action,
        step_by_node=step_by_node,
        memory_hints=memory_hints or {},
    )
    _materialize_runtime_workflow_orchestrator(
        graph=graph,
        organization=organization,
        task=task,
        workflow=workflow,
        path=path,
    )

    return graph, step_by_node, path
