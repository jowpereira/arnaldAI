from __future__ import annotations

from dataclasses import dataclass
import os
import json
from pathlib import Path
import re
from typing import Any, Dict

from arnaldo.contracts import (
    EvidenceRecord,
    RuntimeEvent,
    new_id,
    to_dict,
    utc_now,
)
from arnaldo.graph import (
    CapabilityNode,
    CognitiveGraph,
    EdgeKind,
    ExecutionEngine,
    GraphEdge,
    MemoryNode,
    NodeKind,
    NodeStatus,
    StepContext,
    SynapseExecutionResult,
    SynapseNode,
    SourceRecord,
    make_workflow,
)
from arnaldo.llm import ContractModelRegistry
from arnaldo.storage import RunStore

from .base import RuntimeAdapter, RuntimeContext, RuntimeResult
from .local import render_artifact


@dataclass
class IntentFrameOutput:
    goal: str
    goal_type: str
    constraints: list[str]
    evidence: list[str]
    uncertainties: list[str]


@dataclass
class WorkPlanOutput:
    steps: list[str]
    evidence: list[str]
    uncertainties: list[str]


@dataclass
class ArtifactDraftOutput:
    sections: list[str]
    evidence: list[str]
    uncertainties: list[str]


@dataclass
class CriticReviewOutput:
    status: str
    warnings: list[str]
    evidence: list[str]
    uncertainties: list[str]


@dataclass
class GenericStepOutput:
    status: str
    evidence: list[str]
    uncertainties: list[str]


ACTION_MODEL_MAP: dict[str, type[Any]] = {
    "frame_intent": IntentFrameOutput,
    "decompose_work": WorkPlanOutput,
    "explore_path_a": WorkPlanOutput,
    "explore_path_b": WorkPlanOutput,
    "clarify_uncertainties": WorkPlanOutput,
    "design_tooling": WorkPlanOutput,
    "stabilize_tooling": WorkPlanOutput,
    "execute_tooling": GenericStepOutput,
    "compose_tooling": WorkPlanOutput,
    "draft_artifact": ArtifactDraftOutput,
    "synthesize_artifact": ArtifactDraftOutput,
    "critic_review": CriticReviewOutput,
    "risk_review": CriticReviewOutput,
    "decision_synthesis": CriticReviewOutput,
}

ACTION_CAPABILITY_HINTS: dict[str, list[str]] = {
    "frame_intent": ["intent.structure"],
    "decompose_work": ["work.decompose"],
    "explore_path_a": ["work.decompose"],
    "explore_path_b": ["work.decompose"],
    "clarify_uncertainties": ["validation.critic_review"],
    "design_tooling": ["tool.dynamic.build", "connector.http.generic"],
    "stabilize_tooling": ["tool.dynamic.build", "connector.http.generic"],
    "execute_tooling": ["tool.dynamic.build", "connector.http.generic"],
    "compose_tooling": ["tool.dynamic.build", "connector.http.generic", "artifact.draft"],
    "draft_artifact": ["artifact.draft"],
    "synthesize_artifact": ["artifact.draft"],
    "critic_review": ["validation.critic_review"],
    "risk_review": ["validation.critic_review"],
    "decision_synthesis": ["validation.critic_review"],
}

ROLE_TIER_PREFERENCE: dict[str, str] = {
    "operator": "expert",
    "explorer": "expert",
    "synthesizer": "expert",
    "critic": "god",
    "analyst": "expert",
}


class GraphRuntime(RuntimeAdapter):
    """Runtime baseado em `CognitiveGraph` + `ExecutionEngine` tipado."""

    def __init__(self, llm_client: Any | None = None, strict_real: bool = True) -> None:
        self.llm_client = llm_client
        self.strict_real = bool(strict_real)
        self.seed_graph_path: Path | None = None
        self.contract_registry = ContractModelRegistry()
        self.contract_registry.register_many(
            {
                model.__name__: model
                for model in {
                    IntentFrameOutput,
                    WorkPlanOutput,
                    ArtifactDraftOutput,
                    CriticReviewOutput,
                    GenericStepOutput,
                }
            }
        )

    def set_seed_graph(self, graph_path: str | Path | None) -> None:
        if graph_path is None:
            self.seed_graph_path = None
            return
        self.seed_graph_path = Path(str(graph_path))

    def run(self, context: RuntimeContext, store: RunStore) -> RuntimeResult:
        run_id = context.run_id
        task = context.task
        organization = context.organization
        policy = context.policy
        if self.strict_real and not bool(self.llm_client and getattr(self.llm_client, "is_configured", False)):
            raise RuntimeError(
                "strict_real habilitado: GraphRuntime exige LLM configurado (sem fallback)."
            )
        sandbox = context.sandbox or {}
        workspace_path = self._resolve_sandbox_dir(sandbox.get("workspace_path"))
        artifacts_path = self._resolve_sandbox_dir(sandbox.get("artifacts_path"))
        temp_path = self._resolve_sandbox_dir(sandbox.get("temp_path"))

        self._trace(
            store,
            run_id,
            "graph_runtime_started",
            {
                "organization_id": organization.id,
                "topology": organization.topology,
                "llm_enabled": bool(self.llm_client and getattr(self.llm_client, "is_configured", False)),
                "sandbox_workspace": sandbox.get("workspace_path", ""),
                "sandbox_artifacts": sandbox.get("artifacts_path", ""),
            },
        )
        if workspace_path:
            (workspace_path / "runtime-session.txt").write_text(
                "run_id=%s\ntask_id=%s\norganization_id=%s\nruntime=graph\n"
                % (run_id, task.id, organization.id),
                encoding="utf-8",
            )
            self._trace(
                store,
                run_id,
                "sandbox_prepared",
                {"workspace": str(workspace_path), "artifacts": str(artifacts_path or "")},
            )

        memory_hints = context.memory_hints if isinstance(context.memory_hints, dict) else {}
        if memory_hints:
            self._trace(
                store,
                run_id,
                "memory_hints_loaded",
                {
                    "preferred_actions": len(memory_hints.get("preferred_actions", []) or []),
                    "transitions": len(memory_hints.get("transitions", []) or []),
                    "candidate_synapses": len(memory_hints.get("candidate_synapses", []) or []),
                },
            )

        base_graph = self._load_seed_graph()
        graph, step_by_node, path = self._build_execution_graph(
            organization,
            task=task,
            capability_resolution=context.capability_resolution or {},
            memory_hints=memory_hints,
            graph=base_graph,
        )
        store.write_text("prompts.jsonl", "")
        engine = ExecutionEngine(
            graph=graph,
            llm_client=self.llm_client,
            contract_registry=self.contract_registry,
            strict_real=self.strict_real,
            on_prompt_prepared=lambda payload: self._record_prompt_payload(
                store=store,
                run_id=run_id,
                payload=payload,
            ),
        )

        request = self._build_request(task, context.capability_resolution or {})
        execution_mode = self._select_execution_mode(organization.topology)
        materialized_steps = [
            {
                "index": idx,
                "node_id": node_id,
                **step_by_node[node_id],
            }
            for idx, node_id in enumerate(path, start=1)
            if node_id in step_by_node
        ]
        store.write_json(
            "graph-workflow-materialized.json",
            {
                "topology": organization.topology,
                "execution_mode": execution_mode,
                "root_synapse": path[0] if path else "",
                "step_count": len(materialized_steps),
                "steps": materialized_steps,
            },
        )
        self._trace(
            store,
            run_id,
            "graph_workflow_materialized",
            {
                "topology": organization.topology,
                "execution_mode": execution_mode,
                "step_count": len(materialized_steps),
            },
        )
        self._trace(
            store,
            run_id,
            "graph_execution_planned",
            {
                "mode": execution_mode,
                "root_synapse": path[0] if path else "",
                "workflow_steps": len(path),
            },
        )

        allowed_node_ids = set(step_by_node.keys())
        step_context, bootstrap_payload = self._bootstrap_step_context(
            graph=graph,
            path=path,
        )
        self._trace(store, run_id, "graph_context_bootstrapped", bootstrap_payload)
        execution_results: list[SynapseExecutionResult] = []
        if path:
            if execution_mode == "activates_parallel_levels":
                _, step_context, execution_results = engine.execute_activates_parallel(
                    path[0],
                    request=request,
                    context=step_context,
                    max_steps=max(16, len(path) * 3),
                    max_parallel=4,
                    allowed_node_ids=allowed_node_ids,
                )
            else:
                _, step_context, execution_results = engine.execute_activates_reachable(
                    path[0],
                    request=request,
                    context=step_context,
                    max_steps=max(16, len(path) * 3),
                    allowed_node_ids=allowed_node_ids,
                )

        step_results: list[dict[str, Any]] = []
        previous_memory_node_id: str | None = None
        for index, exec_result in enumerate(execution_results, start=1):
            item = step_by_node.get(exec_result.node_id)
            if item is None:
                self._trace(
                    store,
                    run_id,
                    "orphan_synapse_skipped",
                    {"node_id": exec_result.node_id, "index": index},
                )
                continue
            result_payload = self._normalize_execution_payload(exec_result)
            step_result = {
                "step_id": item["id"],
                "agent_id": item["agent_id"],
                "action": item["action"],
                "output": item["output"],
                "result": result_payload,
                "uncertainties": [entry["question"] for entry in task.uncertainty],
            }
            if item.get("capability_id"):
                step_result["capability_id"] = item["capability_id"]
            step_artifact = self._write_step_artifact(
                artifacts_path,
                index=index,
                action=item["action"],
                payload=step_result,
            )
            if step_artifact:
                step_result["sandbox_artifact"] = str(step_artifact)
            step_results.append(step_result)
            current_memory_node_id = self._record_step_memory(
                graph=graph,
                run_id=run_id,
                node_id=exec_result.node_id,
                step_item=item,
                result_payload=result_payload,
                previous_memory_id=previous_memory_node_id,
            )
            if current_memory_node_id:
                previous_memory_node_id = current_memory_node_id
            self._evolve_capability_nodes(
                graph=graph,
                node_id=exec_result.node_id,
                step_item=item,
                exec_result=exec_result,
            )

            self._trace(store, run_id, "step_completed", step_result)

            if exec_result.refusal is not None:
                self._evidence(
                    store,
                    run_id,
                    task.id,
                    "llm_refusal",
                    "Synapse %s recusou a execução." % item["agent_id"],
                    {
                        "node_id": exec_result.node_id,
                        "step_id": item["id"],
                        "action": item["action"],
                        "reason": exec_result.refusal,
                    },
                )
            elif exec_result.error is not None:
                self._evidence(
                    store,
                    run_id,
                    task.id,
                    "step_failed",
                    "Etapa %s falhou no runtime de grafo." % item["action"],
                    {
                        "node_id": exec_result.node_id,
                        "step_id": item["id"],
                        "action": item["action"],
                        "error": exec_result.error,
                    },
                )
            elif exec_result.fallback_used:
                self._evidence(
                    store,
                    run_id,
                    task.id,
                    "step_fallback",
                    "Etapa %s executada em fallback deterministico." % item["action"],
                    {
                        "node_id": exec_result.node_id,
                        "step_id": item["id"],
                        "action": item["action"],
                        "result": result_payload,
                    },
                )
            else:
                self._evidence(
                    store,
                    run_id,
                    task.id,
                    "step_completed",
                    "Etapa %s executada via synapse tipado." % item["action"],
                    {
                        "node_id": exec_result.node_id,
                        "step_id": item["id"],
                        "action": item["action"],
                        "result": result_payload,
                    },
                )

        artifact = render_artifact(task, organization, policy, step_results)
        artifact_path = store.write_text("artifact.md", artifact)
        if artifacts_path:
            (artifacts_path / "artifact.md").write_text(artifact, encoding="utf-8")

        if step_context.refusals:
            self._trace(
                store,
                run_id,
                "graph_runtime_refusals",
                {"count": len(step_context.refusals), "items": step_context.refusals},
            )
        if step_context.errors:
            self._trace(
                store,
                run_id,
                "graph_runtime_errors",
                {"count": len(step_context.errors), "items": step_context.errors},
            )

        if temp_path:
            (temp_path / "runtime-finished.txt").write_text("completed=true\n", encoding="utf-8")

        retention = self._apply_graph_retention(graph=graph, run_id=run_id, keep_synapse_ids=allowed_node_ids)
        self._trace(store, run_id, "graph_retention_applied", retention)

        graph_path = store.path("execution-graph.msgpack")
        graph.persist(graph_path)
        self._trace(
            store,
            run_id,
            "graph_persisted",
            {"path": str(graph_path), "node_count": graph.node_count, "edge_count": graph.edge_count},
        )

        self._trace(
            store,
            run_id,
            "graph_runtime_completed",
            {"artifact": str(artifact_path), "executed_steps": len(step_results)},
        )

        agent_bus = store.write_text("agent_bus.jsonl", "")
        return RuntimeResult(
            artifact_path=artifact_path,
            step_results=step_results,
            agent_bus_path=agent_bus,
        )

    def _apply_graph_retention(
        self,
        *,
        graph: CognitiveGraph,
        run_id: str,
        keep_synapse_ids: set[str],
    ) -> Dict[str, Any]:
        decay_counters = graph.sweep_decay()
        max_memory_nodes = self._env_positive_int("ARNALDO_GRAPH_MAX_MEMORY_NODES", default=256)
        max_archived_nodes = self._env_positive_int("ARNALDO_GRAPH_MAX_ARCHIVED_NODES", default=128)

        removed_memory = 0
        run_memory_prefix = "mem_%s_" % self._slug(run_id)
        memory_nodes = [
            node
            for node in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False)
        ]
        memory_nodes.sort(key=lambda node: node.bitemp.recorded_at)
        memory_overflow = max(0, len(memory_nodes) - max_memory_nodes)
        if memory_overflow > 0:
            removable_memory = [node for node in memory_nodes if not node.id.startswith(run_memory_prefix)]
            for node in removable_memory:
                if memory_overflow <= 0:
                    break
                graph.remove_node(node.id)
                removed_memory += 1
                memory_overflow -= 1
            if memory_overflow > 0:
                for node in memory_nodes:
                    if memory_overflow <= 0:
                        break
                    if graph.get_node(node.id) is None:
                        continue
                    graph.remove_node(node.id)
                    removed_memory += 1
                    memory_overflow -= 1

        removed_archived = 0
        archived_nodes = [
            node
            for node in graph.iter_nodes(active_only=False)
            if node.status == NodeStatus.ARCHIVED
        ]
        archived_nodes.sort(key=lambda node: node.bitemp.recorded_at)
        archived_overflow = max(0, len(archived_nodes) - max_archived_nodes)
        if archived_overflow > 0:
            for node in archived_nodes:
                if archived_overflow <= 0:
                    break
                if node.id in keep_synapse_ids:
                    continue
                graph.remove_node(node.id)
                removed_archived += 1
                archived_overflow -= 1

        return {
            "decay": decay_counters,
            "max_memory_nodes": max_memory_nodes,
            "max_archived_nodes": max_archived_nodes,
            "removed_memory_nodes": removed_memory,
            "removed_archived_nodes": removed_archived,
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
        }

    def _bootstrap_step_context(
        self,
        *,
        graph: CognitiveGraph,
        path: list[str],
    ) -> tuple[StepContext, Dict[str, Any]]:
        context = StepContext()
        if not path:
            return context, {
                "path_synapses": 0,
                "candidate_synapses": 0,
                "loaded_synapses": 0,
                "context_limit": 0,
            }

        latest_by_synapse: Dict[str, tuple[Any, Dict[str, Any], Dict[str, str]]] = {}
        for synapse_id in path:
            latest_at = None
            latest_result: Dict[str, Any] | None = None
            latest_meta: Dict[str, str] = {}
            for edge in graph.iter_edges_from(
                synapse_id,
                kinds=[EdgeKind.MENTIONS],
                active_only=False,
            ):
                memory_node = graph.get_node(edge.target_id)
                if not isinstance(memory_node, MemoryNode):
                    continue
                memory_payload = memory_node.payload if isinstance(memory_node.payload, dict) else {}
                result_payload = memory_payload.get("result")
                if not isinstance(result_payload, dict):
                    continue
                recorded_at = memory_node.bitemp.recorded_at
                if latest_at is None or recorded_at > latest_at:
                    latest_at = recorded_at
                    latest_result = result_payload
                    latest_meta = {
                        "action": str(memory_payload.get("action", "")).strip(),
                        "agent_id": str(memory_payload.get("agent_id", "")).strip(),
                        "capability_id": str(memory_payload.get("capability_id", "")).strip(),
                        "channel": str(memory_payload.get("channel", "")).strip(),
                    }
            if latest_at is not None and latest_result is not None:
                latest_by_synapse[synapse_id] = (latest_at, latest_result, latest_meta)

        context_limit = self._env_positive_int("ARNALDO_GRAPH_BOOTSTRAP_CONTEXT_LIMIT", default=6)
        selected = sorted(
            latest_by_synapse.items(),
            key=lambda item: item[1][0],
            reverse=True,
        )[:context_limit]
        selected.reverse()

        loaded_tool_context = 0
        for synapse_id, (_, result_payload, meta) in selected:
            action = str(meta.get("action", "")).strip()
            channel = str(meta.get("channel", "")).strip()
            if not channel:
                channel = "tool" if action == "execute_tooling" else "llm"
            if channel == "tool":
                loaded_tool_context += 1
            context.write(
                synapse_id,
                result_payload,
                action=action,
                agent_id=str(meta.get("agent_id", "")).strip(),
                capability_id=str(meta.get("capability_id", "")).strip(),
                channel=channel,
            )

        return context, {
            "path_synapses": len(path),
            "candidate_synapses": len(latest_by_synapse),
            "loaded_synapses": len(selected),
            "loaded_tool_context": loaded_tool_context,
            "context_limit": context_limit,
            "context_version": context.version,
        }

    @staticmethod
    def _env_positive_int(name: str, *, default: int) -> int:
        raw = str(os.environ.get(name, "")).strip()
        if not raw:
            return default
        try:
            parsed = int(raw)
        except ValueError:
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _normalize_positive_int(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0

    @staticmethod
    def _normalize_positive_float(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.0
        return parsed if parsed > 0 else 0.0

    @staticmethod
    def _normalize_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_execution_graph(
        self,
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
        workflow = self._materialize_runtime_workflow(
            organization=organization,
            task=task,
            capability_resolution=capability_resolution,
        )
        capability_state = self._collect_capability_state(task, capability_resolution, organization)
        capability_node_by_capability: dict[str, str] = {}
        for capability_id, state in capability_state.items():
            capability_node = self._upsert_capability_node(
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
            self.contract_registry.register(model, name=model.__name__)
            role = agent.role if agent is not None else self._default_role_for_action(item["action"])
            objective = (
                str(item.get("objective", "")).strip()
                or (
                agent.objective
                if agent is not None
                else self._default_objective_for_action(item["action"], item)
                )
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
            synapse = self._upsert_synapse_node(
                graph=graph,
                node_id=self._synapse_node_id(
                    item["agent_id"],
                    item["action"],
                    item.get("output"),
                ),
                label=f"{item['action']}::{item['agent_id']}",
                role=role,
                objective=objective,
                output_contract=output_contract,
                output_contract_model=model,
                tier_preference=str(item.get("tier_preference") or ROLE_TIER_PREFERENCE.get(role, "expert")),
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
                    capability_node = self._upsert_capability_node(
                        graph,
                        capability_id,
                        state="missing",
                        maturity_hint=None,
                    )
                    capability_node_by_capability[capability_id] = capability_node.id
                    cap_node_id = capability_node.id
                if cap_node_id:
                    self._ensure_edge(
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
            if self._should_skip_sequential_tooling_edge(
                step_by_node.get(source_id, {}),
                step_by_node.get(target_id, {}),
            ):
                continue
            self._ensure_edge(
                graph=graph,
                source_id=source_id,
                target_id=target_id,
                kind=EdgeKind.ACTIVATES,
                weight=max(0.3, 1.0 - (idx * 0.05)),
            )

        # Topologia paralela explícita: frame -> {a,b} -> synthesize.
        if organization.topology == "parallel_with_synthesis":
            self._ensure_branch(
                graph=graph,
                source_action="frame_intent",
                target_action="explore_path_a",
                node_ids_by_action=node_ids_by_action,
                step_by_node=step_by_node,
                weight=0.95,
            )
            self._ensure_branch(
                graph=graph,
                source_action="frame_intent",
                target_action="explore_path_b",
                node_ids_by_action=node_ids_by_action,
                step_by_node=step_by_node,
                weight=0.95,
            )
            self._ensure_branch(
                graph=graph,
                source_action="explore_path_a",
                target_action="synthesize_artifact",
                node_ids_by_action=node_ids_by_action,
                step_by_node=step_by_node,
                weight=0.9,
            )
            self._ensure_branch(
                graph=graph,
                source_action="explore_path_b",
                target_action="synthesize_artifact",
                node_ids_by_action=node_ids_by_action,
                step_by_node=step_by_node,
                weight=0.9,
            )

        self._ensure_dynamic_branches(
            graph=graph,
            node_ids_by_action=node_ids_by_action,
            step_by_node=step_by_node,
        )
        self._reinforce_memory_transitions(
            graph=graph,
            node_ids_by_action=node_ids_by_action,
            step_by_node=step_by_node,
            memory_hints=memory_hints or {},
        )
        self._materialize_runtime_workflow_orchestrator(
            graph=graph,
            organization=organization,
            task=task,
            workflow=workflow,
            path=path,
        )

        return graph, step_by_node, path

    def _materialize_runtime_workflow(
        self,
        *,
        organization: Any,
        task: Any,
        capability_resolution: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        lightweight_conversation = self._is_lightweight_conversational_task(task)
        conversational_cli = self._is_conversational_cli_turn(
            task=task,
            capability_resolution=capability_resolution,
        )
        latency_sensitive_cli = self._is_latency_sensitive_cli_turn(
            task=task,
            capability_resolution=capability_resolution,
        )
        source = list(organization.workflow or [])
        if not source:
            if lightweight_conversation:
                source = self._workflow_seed_for_lightweight_conversation()
            elif latency_sensitive_cli:
                source = self._workflow_seed_for_latency_sensitive_cli_turn()
            else:
                source = self._workflow_seed_for_topology(organization.topology)

        tooling_id_by_slug: dict[str, str] = {}
        module_path_by_capability: dict[str, str] = {}
        for bucket in ("available", "degraded", "missing"):
            for item in capability_resolution.get(bucket, []) or []:
                capability_id = str(item.get("id", "")).strip()
                if capability_id.startswith(("connector.", "tool.")):
                    tooling_id_by_slug[self._slug(capability_id)] = capability_id
                    module_path = self._capability_module_path(item)
                    if module_path:
                        module_path_by_capability[capability_id] = module_path
        for item in task.capability_needs:
            capability_id = str(item.get("id", "")).strip()
            if capability_id.startswith(("connector.", "tool.")):
                tooling_id_by_slug[self._slug(capability_id)] = capability_id

        workflow: list[Dict[str, Any]] = []
        for item in source:
            action = str(item.get("action", "")).strip()
            if not action:
                continue
            output = str(item.get("output") or self._default_output_for_action(action))
            capability_id = str(item.get("capability_id", "")).strip()
            if not capability_id and action in {"design_tooling", "stabilize_tooling", "execute_tooling"}:
                capability_id = self._infer_capability_id_from_output(
                    action=action,
                    output=output,
                    tooling_id_by_slug=tooling_id_by_slug,
                )
            agent_id = str(item.get("agent_id") or self._default_agent_for_action(action))
            if action in {"design_tooling", "stabilize_tooling"} and capability_id:
                if agent_id in {"", "toolsmith", self._default_agent_for_action(action)}:
                    agent_id = self._toolsmith_agent_for_capability(capability_id)
            if action == "execute_tooling" and capability_id:
                if agent_id in {"", "toolrunner", self._default_agent_for_action(action)}:
                    agent_id = self._toolrunner_agent_for_capability(capability_id)
            module_path = self._capability_module_path(item)
            if not module_path and capability_id:
                module_path = module_path_by_capability.get(capability_id, "")
            normalized: Dict[str, Any] = {
                "id": str(item.get("id") or new_id("step")),
                "agent_id": agent_id,
                "action": action,
                "output": output,
            }
            objective = str(item.get("objective", "")).strip()
            if objective:
                normalized["objective"] = objective
            output_contract = item.get("output_contract")
            if isinstance(output_contract, dict) and output_contract:
                normalized["output_contract"] = output_contract
            tier_preference = str(item.get("tier_preference", "")).strip()
            if tier_preference:
                normalized["tier_preference"] = tier_preference
            max_tokens = self._normalize_positive_int(item.get("max_tokens"))
            if max_tokens > 0:
                normalized["max_tokens"] = max_tokens
            timeout = self._normalize_positive_float(item.get("timeout"))
            if timeout > 0:
                normalized["timeout"] = timeout
            step_temperature = self._normalize_float(item.get("temperature"))
            if step_temperature is not None:
                normalized["temperature"] = step_temperature
            max_retries = self._normalize_positive_int(item.get("max_retries"))
            if max_retries > 0:
                normalized["max_retries"] = max_retries
            retry_attempts = self._normalize_positive_int(item.get("retry_attempts"))
            if retry_attempts > 0:
                normalized["retry_attempts"] = retry_attempts
            reasoning_effort = str(item.get("reasoning_effort", "")).strip()
            if reasoning_effort:
                normalized["reasoning_effort"] = reasoning_effort
            reasoning_summary = str(item.get("reasoning_summary", "")).strip()
            if reasoning_summary:
                normalized["reasoning_summary"] = reasoning_summary
            if capability_id:
                normalized["capability_id"] = capability_id
            if module_path:
                normalized["module_path"] = module_path
            workflow.append(normalized)

        if not workflow:
            if lightweight_conversation:
                workflow = self._workflow_seed_for_lightweight_conversation()
            elif latency_sensitive_cli:
                workflow = self._workflow_seed_for_latency_sensitive_cli_turn()
            else:
                workflow = self._workflow_seed_for_topology(organization.topology)

        if lightweight_conversation:
            compact = [
                item
                for item in workflow
                if str(item.get("action", "")).strip() == "draft_artifact"
            ]
            if not compact:
                compact = self._workflow_seed_for_lightweight_conversation()
            item = compact[0]
            item.setdefault("agent_id", self._default_agent_for_action("draft_artifact"))
            item["action"] = "draft_artifact"
            item.setdefault("output", self._default_output_for_action("draft_artifact"))
            item["tier_preference"] = "fast"
            item["max_tokens"] = 320
            item["timeout"] = 18.0
            item["temperature"] = 0.2
            item["max_retries"] = 0
            item["retry_attempts"] = 1
            item["objective"] = self._lightweight_conversation_objective()
            item["output_contract"] = self._lightweight_conversation_output_contract()
            return [item]

        if conversational_cli:
            compact = [
                item
                for item in workflow
                if str(item.get("action", "")).strip() == "draft_artifact"
            ]
            if not compact:
                compact = self._workflow_seed_for_lightweight_conversation()
            item = compact[0]
            request = self._extract_primary_user_request(task)
            words = self._word_count(request)
            item.setdefault("agent_id", self._default_agent_for_action("draft_artifact"))
            item["action"] = "draft_artifact"
            item.setdefault("output", self._default_output_for_action("draft_artifact"))
            item["tier_preference"] = "fast" if words <= 18 else "expert"
            item["max_tokens"] = 420 if words <= 12 else 900
            item["timeout"] = 25.0 if words <= 12 else 50.0
            item["temperature"] = 0.2
            item["max_retries"] = 0
            item["retry_attempts"] = 1
            item["objective"] = self._lightweight_conversation_objective()
            item["output_contract"] = self._lightweight_conversation_output_contract()
            return [item]

        if latency_sensitive_cli:
            compact = [
                item
                for item in workflow
                if str(item.get("action", "")).strip() == "draft_artifact"
            ]
            if not compact:
                compact = self._workflow_seed_for_latency_sensitive_cli_turn()
            item = compact[0]
            item.setdefault("agent_id", self._default_agent_for_action("draft_artifact"))
            item["action"] = "draft_artifact"
            item.setdefault("output", self._default_output_for_action("draft_artifact"))
            item.setdefault("tier_preference", "fast")
            item.setdefault("max_tokens", 700)
            item.setdefault("timeout", 25.0)
            item.setdefault("temperature", 0.2)
            item.setdefault("max_retries", 0)
            item.setdefault("retry_attempts", 1)
            return [item]

        if not self._has_workflow_step(workflow, "frame_intent"):
            self._insert_workflow_step(
                workflow,
                0,
                action="frame_intent",
                agent_id=self._default_agent_for_action("frame_intent"),
                output=self._default_output_for_action("frame_intent"),
            )

        if len(task.uncertainty) >= 2 and not self._has_workflow_step(workflow, "clarify_uncertainties"):
            insert_at = 1 if workflow else 0
            self._insert_workflow_step(
                workflow,
                insert_at,
                action="clarify_uncertainties",
                agent_id=self._default_agent_for_action("clarify_uncertainties"),
                output=self._default_output_for_action("clarify_uncertainties"),
            )

        if organization.topology == "parallel_with_synthesis":
            for action in ("explore_path_a", "explore_path_b", "synthesize_artifact"):
                self._upsert_workflow_step(
                    workflow,
                    action=action,
                    agent_id=self._default_agent_for_action(action),
                    output=self._default_output_for_action(action),
                )
        else:
            for action in ("decompose_work", "draft_artifact"):
                self._upsert_workflow_step(
                    workflow,
                    action=action,
                    agent_id=self._default_agent_for_action(action),
                    output=self._default_output_for_action(action),
                )

        tooling_targets = self._collect_tooling_targets(capability_resolution)
        insert_before = min(
            [
                idx
                for idx, item in enumerate(workflow)
                if item["action"] in {"synthesize_artifact", "draft_artifact", "critic_review"}
            ]
            or [len(workflow)]
        )
        for capability_id in tooling_targets["missing"]:
            if self._has_workflow_step(workflow, "design_tooling", capability_id=capability_id):
                continue
            self._insert_workflow_step(
                workflow,
                insert_before,
                action="design_tooling",
                agent_id=self._toolsmith_agent_for_capability(capability_id),
                output="tool_specs_%s" % self._slug(capability_id),
                capability_id=capability_id,
            )
            insert_before += 1

        for capability_id in tooling_targets["degraded"]:
            if self._has_workflow_step(workflow, "stabilize_tooling", capability_id=capability_id):
                continue
            self._insert_workflow_step(
                workflow,
                insert_before,
                action="stabilize_tooling",
                agent_id=self._toolsmith_agent_for_capability(capability_id),
                output="tool_stability_%s" % self._slug(capability_id),
                capability_id=capability_id,
            )
            insert_before += 1

        for target in self._collect_tool_execution_targets(capability_resolution):
            capability_id = target["id"]
            if self._has_workflow_step(workflow, "execute_tooling", capability_id=capability_id):
                continue
            self._insert_workflow_step(
                workflow,
                insert_before,
                action="execute_tooling",
                agent_id=self._toolrunner_agent_for_capability(capability_id),
                output="tool_exec_%s" % self._slug(capability_id),
                capability_id=capability_id,
                module_path=target["module_path"],
            )
            insert_before += 1

        tooling_compose_targets = self._collect_workflow_tooling_capabilities(workflow)
        if len(tooling_compose_targets) >= 2 and not self._has_workflow_step(workflow, "compose_tooling"):
            compose_insert_before = min(
                [
                    idx
                    for idx, item in enumerate(workflow)
                    if item["action"] in {
                        "synthesize_artifact",
                        "draft_artifact",
                        "critic_review",
                        "risk_review",
                        "decision_synthesis",
                    }
                ]
                or [len(workflow)]
            )
            self._insert_workflow_step(
                workflow,
                compose_insert_before,
                action="compose_tooling",
                agent_id=self._default_agent_for_action("compose_tooling"),
                output=self._default_output_for_action("compose_tooling"),
            )

        self._upsert_workflow_step(
            workflow,
            action="critic_review",
            agent_id=self._default_agent_for_action("critic_review"),
            output=self._default_output_for_action("critic_review"),
        )
        if str(task.risk.get("execution_risk", "low")) == "high":
            self._upsert_workflow_step(
                workflow,
                action="risk_review",
                agent_id=self._default_agent_for_action("risk_review"),
                output=self._default_output_for_action("risk_review"),
            )
        if task.goal.get("type") in {"analyze_or_evaluate", "decide_or_compare"}:
            self._upsert_workflow_step(
                workflow,
                action="decision_synthesis",
                agent_id=self._default_agent_for_action("decision_synthesis"),
                output=self._default_output_for_action("decision_synthesis"),
            )

        return workflow

    def _workflow_seed_for_topology(self, topology: str) -> list[Dict[str, Any]]:
        if topology == "parallel_with_synthesis":
            return [
                self._insert_workflow_step([], 0, action="frame_intent", agent_id="framer", output="intent_frame"),
                self._insert_workflow_step([], 0, action="explore_path_a", agent_id="explorer_a", output="work_option_a"),
                self._insert_workflow_step([], 0, action="explore_path_b", agent_id="explorer_b", output="work_option_b"),
                self._insert_workflow_step([], 0, action="synthesize_artifact", agent_id="synthesizer", output="primary_artifact"),
                self._insert_workflow_step([], 0, action="critic_review", agent_id="critic", output="critic_review"),
            ]
        if topology == "pipeline_with_critic":
            return [
                self._insert_workflow_step([], 0, action="frame_intent", agent_id="framer", output="intent_frame"),
                self._insert_workflow_step([], 0, action="decompose_work", agent_id="planner", output="work_plan"),
                self._insert_workflow_step([], 0, action="draft_artifact", agent_id="planner", output="primary_artifact"),
                self._insert_workflow_step([], 0, action="critic_review", agent_id="critic", output="critic_review"),
            ]
        return [
            self._insert_workflow_step([], 0, action="frame_intent", agent_id="operator", output="intent_frame"),
            self._insert_workflow_step([], 0, action="decompose_work", agent_id="operator", output="work_plan"),
            self._insert_workflow_step([], 0, action="draft_artifact", agent_id="operator", output="primary_artifact"),
        ]

    def _workflow_seed_for_lightweight_conversation(self) -> list[Dict[str, Any]]:
        return [
            self._insert_workflow_step(
                [],
                0,
                action="draft_artifact",
                agent_id="operator",
                output="primary_artifact",
                tier_preference="fast",
                max_tokens=320,
                timeout=18.0,
                temperature=0.2,
                max_retries=0,
                retry_attempts=1,
                objective=self._lightweight_conversation_objective(),
                output_contract=self._lightweight_conversation_output_contract(),
            ),
        ]

    def _workflow_seed_for_latency_sensitive_cli_turn(self) -> list[Dict[str, Any]]:
        return [
            self._insert_workflow_step(
                [],
                0,
                action="draft_artifact",
                agent_id="operator",
                output="primary_artifact",
                tier_preference="fast",
                max_tokens=700,
                timeout=25.0,
                temperature=0.2,
                max_retries=0,
                retry_attempts=1,
            ),
        ]

    @staticmethod
    def _lightweight_conversation_objective() -> str:
        return (
            "responder diretamente ao usuario em tom conversacional claro, "
            "sem metalinguagem de pipeline, priorizando memoria de sessao quando houver"
        )

    @staticmethod
    def _lightweight_conversation_output_contract() -> Dict[str, Any]:
        return {
            "schema": "chat_turn_output",
            "required_sections": ["sections", "evidence", "uncertainties"],
            "rules": [
                "sections[0] deve conter a resposta final ao usuario",
                "resposta deve ser natural e curta (1-4 frases)",
                "nao mencionar goaltype, deliverables, capabilityneeds ou logs",
            ],
        }

    def _upsert_workflow_step(
        self,
        workflow: list[Dict[str, Any]],
        *,
        action: str,
        agent_id: str,
        output: str,
        capability_id: str | None = None,
        module_path: str | None = None,
    ) -> None:
        if self._has_workflow_step(workflow, action, capability_id=capability_id):
            return
        workflow.append(
            self._insert_workflow_step(
                [],
                0,
                action=action,
                agent_id=agent_id,
                output=output,
                capability_id=capability_id,
                module_path=module_path,
            )
        )

    def _has_workflow_step(
        self,
        workflow: list[Dict[str, Any]],
        action: str,
        *,
        capability_id: str | None = None,
    ) -> bool:
        for item in workflow:
            if item.get("action") != action:
                continue
            if capability_id is None:
                return True
            if str(item.get("capability_id", "")).strip() == capability_id:
                return True
        return False

    def _insert_workflow_step(
        self,
        workflow: list[Dict[str, Any]],
        index: int,
        *,
        action: str,
        agent_id: str,
        output: str,
        capability_id: str | None = None,
        module_path: str | None = None,
        tier_preference: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
        retry_attempts: int | None = None,
        objective: str | None = None,
        output_contract: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "id": new_id("step"),
            "agent_id": agent_id,
            "action": action,
            "output": output,
        }
        if objective:
            item["objective"] = str(objective).strip()
        if isinstance(output_contract, dict) and output_contract:
            item["output_contract"] = dict(output_contract)
        if tier_preference:
            item["tier_preference"] = str(tier_preference)
        if isinstance(max_tokens, int) and max_tokens > 0:
            item["max_tokens"] = max_tokens
        if isinstance(timeout, (int, float)) and timeout > 0:
            item["timeout"] = float(timeout)
        if isinstance(temperature, (int, float)):
            item["temperature"] = float(temperature)
        if isinstance(max_retries, int) and max_retries >= 0:
            item["max_retries"] = max_retries
        if isinstance(retry_attempts, int) and retry_attempts > 0:
            item["retry_attempts"] = retry_attempts
        if capability_id:
            item["capability_id"] = capability_id
        if module_path:
            item["module_path"] = module_path
        if workflow is not None:
            workflow.insert(index, item)
        return item

    @staticmethod
    def _default_agent_for_action(action: str) -> str:
        return {
            "frame_intent": "framer",
            "clarify_uncertainties": "clarifier",
            "explore_path_a": "explorer_a",
            "explore_path_b": "explorer_b",
            "decompose_work": "planner",
            "design_tooling": "toolsmith",
            "stabilize_tooling": "toolsmith",
            "execute_tooling": "toolrunner",
            "compose_tooling": "workflow_composer",
            "synthesize_artifact": "synthesizer",
            "draft_artifact": "planner",
            "critic_review": "critic",
            "risk_review": "risk_auditor",
            "decision_synthesis": "critic",
        }.get(action, "operator")

    @staticmethod
    def _toolsmith_agent_for_capability(capability_id: str) -> str:
        return "toolsmith_%s" % GraphRuntime._slug(capability_id)

    @staticmethod
    def _toolrunner_agent_for_capability(capability_id: str) -> str:
        return "toolrunner_%s" % GraphRuntime._slug(capability_id)

    @staticmethod
    def _default_role_for_action(action: str) -> str:
        return {
            "frame_intent": "operator",
            "clarify_uncertainties": "analyst",
            "explore_path_a": "explorer",
            "explore_path_b": "explorer",
            "decompose_work": "operator",
            "design_tooling": "operator",
            "stabilize_tooling": "operator",
            "execute_tooling": "operator",
            "compose_tooling": "synthesizer",
            "synthesize_artifact": "synthesizer",
            "draft_artifact": "operator",
            "critic_review": "critic",
            "risk_review": "critic",
            "decision_synthesis": "critic",
        }.get(action, "operator")

    @staticmethod
    def _default_objective_for_action(action: str, item: Dict[str, Any]) -> str:
        if action == "design_tooling":
            capability_id = str(item.get("capability_id", "")).strip()
            return "definir e especificar a capability ausente %s" % capability_id if capability_id else "definir especificacao de tooling"
        if action == "stabilize_tooling":
            capability_id = str(item.get("capability_id", "")).strip()
            return "estabilizar e validar a capability degradada %s" % capability_id if capability_id else "estabilizar tooling degradado"
        if action == "execute_tooling":
            capability_id = str(item.get("capability_id", "")).strip()
            return "executar e validar em runtime a capability dinâmica %s" % capability_id if capability_id else "executar tooling dinâmico"
        if action == "compose_tooling":
            return "compor os resultados das sinapses de tooling em um plano integrado de execução"
        return {
            "frame_intent": "enquadrar objetivo e critérios operacionais",
            "clarify_uncertainties": "transformar incertezas em perguntas acionáveis",
            "explore_path_a": "propor primeira alternativa de execução",
            "explore_path_b": "propor segunda alternativa de execução",
            "decompose_work": "decompor o trabalho em etapas executáveis",
            "synthesize_artifact": "sintetizar alternativas em um artefato único",
            "draft_artifact": "construir artefato inicial executável",
            "critic_review": "revisar lacunas e evidências",
            "risk_review": "revisar riscos e pontos de falha",
            "decision_synthesis": "produzir síntese de decisão",
        }.get(action, action)

    @staticmethod
    def _default_output_for_action(action: str) -> str:
        return {
            "frame_intent": "intent_frame",
            "clarify_uncertainties": "uncertainty_map",
            "explore_path_a": "work_option_a",
            "explore_path_b": "work_option_b",
            "decompose_work": "work_plan",
            "design_tooling": "tool_specs",
            "stabilize_tooling": "tool_stability",
            "execute_tooling": "tool_exec",
            "compose_tooling": "tooling_composition",
            "synthesize_artifact": "primary_artifact",
            "draft_artifact": "primary_artifact",
            "critic_review": "critic_review",
            "risk_review": "risk_report",
            "decision_synthesis": "decision_brief",
        }.get(action, "step_output")

    @staticmethod
    def _is_lightweight_conversational_task(task: Any) -> bool:
        goal = task.goal if isinstance(task.goal, dict) else {}
        goal_type = str(goal.get("type", "")).strip()
        if goal_type != "open_ended_execution":
            return False

        candidate = GraphRuntime._extract_primary_user_request(task).lower()
        if candidate and re.match(r"^(oi|ol[aá]|hello|hi|bom dia|boa tarde|boa noite)\b", candidate):
            return True
        identity_patterns = (
            r"\bquem sou eu\b",
            r"\bqual (?:e|é) meu nome\b",
            r"\bcomo eu me chamo\b",
            r"\blembra do meu nome\b",
            r"\bmeu nome (?:e|é)\b",
            r"\bme chama de\b",
            r"\bpode me chamar de\b",
            r"\bme chama assim\b",
            r"\bpode me chamar assim\b",
        )
        if candidate and any(re.search(pattern, candidate) for pattern in identity_patterns):
            return True

        statement = str(goal.get("statement", "")).strip().lower()
        if statement:
            markers = (
                "sauda",
                "cumpriment",
                "conversa inicial",
                "greeting",
                "olá",
                "ola",
                "oi",
                "identidade no contexto da conversa",
                "nome informado",
            )
            if any(marker in statement for marker in markers):
                return True
        return False

    @staticmethod
    def _extract_primary_user_request(task: Any) -> str:
        context_raw = getattr(task, "context", {})
        context = context_raw if isinstance(context_raw, dict) else {}
        raw = str(context.get("raw_request") or context.get("original_request") or "").strip()
        if not raw:
            return ""
        cleaned = " ".join(raw.split())
        markers = (
            "contexto_objetivos_ativos:",
            "objetivos_extraidos_no_turno:",
            "continuidade_sessao:",
        )
        lower_cleaned = cleaned.lower()
        cut = len(cleaned)
        for marker in markers:
            pos = lower_cleaned.find(marker)
            if pos >= 0:
                cut = min(cut, pos)
        primary = cleaned[:cut].strip(" |;-")
        return primary or cleaned

    @staticmethod
    def _is_latency_sensitive_cli_turn(
        *,
        task: Any,
        capability_resolution: Dict[str, Any],
    ) -> bool:
        goal = task.goal if isinstance(task.goal, dict) else {}
        goal_type = str(goal.get("type", "")).strip()
        if goal_type not in {"analyze_or_evaluate", "decide_or_compare"}:
            return False

        context_raw = getattr(task, "context", {})
        context = context_raw if isinstance(context_raw, dict) else {}
        source = str(context.get("source", "")).strip().lower()
        if source != "cli":
            return False
        request = GraphRuntime._extract_primary_user_request(task)
        if not request:
            return False
        word_count = GraphRuntime._word_count(request)
        if word_count > 6:
            return False

        for bucket in ("missing", "degraded"):
            for item in capability_resolution.get(bucket, []) or []:
                capability_id = str(item.get("id", "")).strip()
                if capability_id.startswith(("connector.", "tool.")):
                    return False
        return True

    @staticmethod
    def _is_conversational_cli_turn(
        *,
        task: Any,
        capability_resolution: Dict[str, Any] | None = None,
    ) -> bool:
        goal = task.goal if isinstance(task.goal, dict) else {}
        if str(goal.get("type", "")).strip() != "open_ended_execution":
            return False
        context_raw = getattr(task, "context", {})
        context = context_raw if isinstance(context_raw, dict) else {}
        source = str(context.get("source", "")).strip().lower()
        if source != "cli":
            return False
        context_text = str(context.get("original_request", "")).strip().lower()
        continuity_markers = (
            "contexto_objetivos_ativos:",
            "objetivos_extraidos_no_turno:",
            "continuidade_sessao:",
        )
        has_chat_continuity = any(marker in context_text for marker in continuity_markers)
        has_raw_chat_turn = bool(str(context.get("raw_request", "")).strip())
        if not has_chat_continuity and not has_raw_chat_turn and not GraphRuntime._is_lightweight_conversational_task(task):
            return False
        request = GraphRuntime._extract_primary_user_request(task)
        if not request:
            return False
        if GraphRuntime._contains_structured_execution_intent(request):
            return False
        if capability_resolution:
            for bucket in ("missing", "degraded"):
                for item in capability_resolution.get(bucket, []) or []:
                    capability_id = str(item.get("id", "")).strip()
                    if capability_id.startswith(("connector.", "tool.")):
                        return False
        if GraphRuntime._word_count(request) > 36 and not GraphRuntime._is_lightweight_conversational_task(task):
            return False
        return True

    @staticmethod
    def _word_count(text: str) -> int:
        return len([chunk for chunk in str(text).split() if chunk.strip()])

    @staticmethod
    def _contains_structured_execution_intent(text: str) -> bool:
        candidate = str(text).lower()
        if not candidate:
            return False
        patterns = (
            r"\bapi\b",
            r"\bconector\b",
            r"\bconnector\b",
            r"\bworkflow\b",
            r"\bferramenta\b",
            r"\btool(?:ing)?\b",
            r"\bintegrar\b",
            r"\bimplement(?:ar|acao|ação)\b",
            r"\bdesenvolver\b",
            r"\bcriar\b",
            r"\bprojetar\b",
            r"\barquitetura\b",
            r"\bmem[oó]ria\b",
            r"\bgrafo\b",
            r"\bsistema\b",
            r"\bc[oó]digo\b",
            r"\bbackend\b",
            r"\bfrontend\b",
            r"\brl\b",
            r"\breinforcement\b",
        )
        return any(re.search(pattern, candidate) for pattern in patterns)

    @staticmethod
    def _infer_capability_id_from_output(
        *,
        action: str,
        output: str,
        tooling_id_by_slug: Dict[str, str],
    ) -> str:
        output_lower = output.strip().lower()
        prefix = {
            "design_tooling": "tool_specs_",
            "stabilize_tooling": "tool_stability_",
            "execute_tooling": "tool_exec_",
        }.get(action, "")
        if not prefix or not output_lower.startswith(prefix):
            return ""
        slug = output_lower[len(prefix):].strip("_")
        if not slug:
            return ""
        return tooling_id_by_slug.get(slug, "")

    @staticmethod
    def _collect_tooling_targets(capability_resolution: Dict[str, Any]) -> Dict[str, list[str]]:
        missing: set[str] = set()
        degraded: set[str] = set()
        for item in capability_resolution.get("missing", []) or []:
            capability_id = str(item.get("id", "")).strip()
            if capability_id.startswith(("connector.", "tool.")):
                missing.add(capability_id)
        for item in capability_resolution.get("degraded", []) or []:
            capability_id = str(item.get("id", "")).strip()
            if capability_id.startswith(("connector.", "tool.")):
                degraded.add(capability_id)
        return {
            "missing": sorted(missing),
            "degraded": sorted(degraded),
        }

    @classmethod
    def _collect_tool_execution_targets(
        cls,
        capability_resolution: Dict[str, Any],
    ) -> list[Dict[str, str]]:
        targets: dict[str, str] = {}
        for bucket in ("available", "degraded", "missing"):
            for item in capability_resolution.get(bucket, []) or []:
                capability_id = str(item.get("id", "")).strip()
                if not capability_id.startswith(("connector.", "tool.")):
                    continue
                module_path = cls._capability_module_path(item)
                if not module_path:
                    continue
                targets[capability_id] = module_path
        return [
            {"id": capability_id, "module_path": targets[capability_id]}
            for capability_id in sorted(targets.keys())
        ]

    @staticmethod
    def _collect_workflow_tooling_capabilities(workflow: list[Dict[str, Any]]) -> set[str]:
        tooling_actions = {"design_tooling", "stabilize_tooling", "execute_tooling"}
        capabilities: set[str] = set()
        for item in workflow:
            action = str(item.get("action", "")).strip()
            if action not in tooling_actions:
                continue
            capability_id = str(item.get("capability_id", "")).strip()
            if capability_id:
                capabilities.add(capability_id)
        return capabilities

    @classmethod
    def _capability_module_path(cls, item: Dict[str, Any]) -> str:
        direct = cls._normalize_module_path(item.get("module_path"))
        if direct:
            return direct
        policies = item.get("policies") or {}
        if isinstance(policies, dict):
            return cls._normalize_module_path(policies.get("module_path"))
        return ""

    @staticmethod
    def _normalize_module_path(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        normalized = value.strip()
        if normalized.lower() in {"none", "null"}:
            return ""
        return normalized

    def _collect_capability_state(
        self,
        task: Any,
        capability_resolution: Dict[str, Any],
        organization: Any,
    ) -> dict[str, dict[str, str]]:
        state_by_id: dict[str, dict[str, str]] = {}
        state_rank = {"missing": 0, "degraded": 1, "available": 2}

        def merge(capability_id: str, state: str, *, maturity: str | None = None) -> None:
            if not capability_id:
                return
            current = state_by_id.get(capability_id)
            if current is None or state_rank[state] > state_rank[current["state"]]:
                state_by_id[capability_id] = {"state": state}
            if maturity:
                bucket = state_by_id.setdefault(capability_id, {"state": state})
                existing_maturity = str(bucket.get("maturity", "")).strip()
                bucket["maturity"] = (
                    maturity
                    if not existing_maturity
                    else self._max_maturity(existing_maturity, maturity)
                )

        for item in task.capability_needs:
            capability_id = str(item.get("id", "")).strip()
            if not capability_id:
                continue
            inferred_state = "missing" if bool(item.get("required", True)) else "degraded"
            merge(capability_id, inferred_state)

        for item in capability_resolution.get("available", []) or []:
            capability_id = str(item.get("id", "")).strip()
            merge(capability_id, "available", maturity=self._capability_maturity_hint(item))
        for item in capability_resolution.get("degraded", []) or []:
            capability_id = str(item.get("id", "")).strip()
            merge(capability_id, "degraded", maturity=self._capability_maturity_hint(item))
        for item in capability_resolution.get("missing", []) or []:
            capability_id = str(item.get("id", "")).strip()
            merge(capability_id, "missing", maturity=self._capability_maturity_hint(item))

        for capability_id in organization.required_capabilities:
            merge(str(capability_id).strip(), "missing")

        return {key: state_by_id[key] for key in sorted(state_by_id)}

    @staticmethod
    def _capability_maturity_hint(item: Dict[str, Any]) -> str | None:
        direct = str(item.get("maturity", "")).strip()
        if direct:
            return direct
        policies = item.get("policies") or {}
        hinted = str(policies.get("maturity", "")).strip()
        return hinted or None

    def _upsert_capability_node(
        self,
        graph: CognitiveGraph,
        capability_id: str,
        *,
        state: str,
        maturity_hint: str | None,
    ) -> CapabilityNode:
        node_id = f"cap_{self._slug(capability_id)}"
        target_maturity = self._resolve_capability_maturity(
            capability_id=capability_id,
            state=state,
            maturity_hint=maturity_hint,
        )
        existing = graph.get_node(node_id)
        if isinstance(existing, CapabilityNode):
            merged_maturity = self._max_maturity(existing.maturity, target_maturity)
            updated = existing.with_payload_merge(
                maturity=merged_maturity,
                state=state,
                risk_level=self._risk_level_for_state(state),
            )
            assert isinstance(updated, CapabilityNode)
            updated = updated.with_weight(self._capability_weight_for_maturity(merged_maturity))
            assert isinstance(updated, CapabilityNode)
            graph.add_node(updated)
            return updated

        description = "Capability dinâmica observada no fluxo de execução (%s)" % state
        capability = CapabilityNode.tool(
            capability_id,
            id=node_id,
            description=description,
            maturity=target_maturity,
            risk_level=self._risk_level_for_state(state),
            payload={"state": state},
        )
        graph.add_node(capability)
        return capability

    @staticmethod
    def _resolve_capability_maturity(
        *,
        capability_id: str,
        state: str,
        maturity_hint: str | None,
    ) -> str:
        levels = set(CapabilityNode.MATURITY_LEVELS)
        hinted = str(maturity_hint or "").strip().lower()
        if hinted in levels:
            return hinted
        is_tooling = capability_id.startswith(("connector.", "tool."))
        if state == "available":
            return "tested" if is_tooling else "trusted"
        if state == "degraded":
            return "draft" if is_tooling else "tested"
        return "scaffolded" if is_tooling else "draft"

    @staticmethod
    def _max_maturity(current: str, candidate: str) -> str:
        levels = list(CapabilityNode.MATURITY_LEVELS)
        current_idx = levels.index(current) if current in levels else 0
        candidate_idx = levels.index(candidate) if candidate in levels else 0
        if current == "deprecated":
            return current
        return levels[max(current_idx, candidate_idx)]

    @staticmethod
    def _capability_weight_for_maturity(maturity: str) -> float:
        return {
            "scaffolded": 0.10,
            "draft": 0.25,
            "tested": 0.55,
            "trusted": 0.85,
            "deprecated": 0.05,
        }.get(maturity, 0.25)

    @staticmethod
    def _risk_level_for_state(state: str) -> str:
        return {
            "available": "low",
            "degraded": "medium",
            "missing": "high",
        }.get(state, "medium")

    def _upsert_synapse_node(
        self,
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
        self,
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
        self,
        *,
        graph: CognitiveGraph,
        run_id: str,
        node_id: str,
        step_item: Dict[str, Any],
        result_payload: Dict[str, Any],
        previous_memory_id: str | None = None,
    ) -> str:
        memory_id = "mem_%s_%s" % (self._slug(run_id), self._slug(step_item["id"]))
        if graph.get_node(memory_id) is None:
            summary = self._result_summary(result_payload)
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
        self._ensure_edge(
            graph=graph,
            source_id=node_id,
            target_id=memory_id,
            kind=EdgeKind.MENTIONS,
            weight=0.6,
        )
        if previous_memory_id and previous_memory_id != memory_id and graph.get_node(previous_memory_id):
            self._ensure_edge(
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
                self._ensure_edge(
                    graph=graph,
                    source_id=candidate.id,
                    target_id=memory_id,
                    kind=EdgeKind.SEMANTIC,
                    weight=0.58,
                )
        return memory_id

    def _ensure_branch(
        self,
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
                    if str(step_by_node.get(target_id, {}).get("capability_id", "")).strip() == source_capability
                ]
            selected_targets = preferred_targets or target_ids
            for target_id in selected_targets:
                self._ensure_edge(
                    graph=graph,
                    source_id=source_id,
                    target_id=target_id,
                    kind=EdgeKind.ACTIVATES,
                    weight=weight,
                )

    def _ensure_dynamic_branches(
        self,
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
            self._ensure_branch(
                graph=graph,
                source_action=source_action,
                target_action=target_action,
                node_ids_by_action=node_ids_by_action,
                step_by_node=step_by_node,
                weight=weight,
            )

    def _reinforce_memory_transitions(
        self,
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
            score = self._normalize_positive_float(item.get("score"))
            if score <= 0:
                continue
            normalized_weight = max(0.45, min(0.95, 0.45 + (0.15 * score)))
            self._ensure_branch(
                graph=graph,
                source_action=source_action,
                target_action=target_action,
                node_ids_by_action=node_ids_by_action,
                step_by_node=step_by_node,
                weight=normalized_weight,
            )

    def _materialize_runtime_workflow_orchestrator(
        self,
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
            self._slug(str(getattr(organization, "id", "org"))),
            self._slug(str(getattr(task, "id", "task"))),
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
        self._ensure_edge(
            graph=graph,
            source_id=orchestrator.id,
            target_id=path[0],
            kind=EdgeKind.ACTIVATES,
            weight=0.93,
        )
        self._ensure_edge(
            graph=graph,
            source_id=path[-1],
            target_id=orchestrator.id,
            kind=EdgeKind.DERIVED_FROM,
            weight=0.65,
        )

    @staticmethod
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
        self,
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
        capability_node = graph.get_node("cap_%s" % self._slug(capability_id))
        if not isinstance(capability_node, CapabilityNode):
            return

        base_node = capability_node
        if action == "execute_tooling":
            status = self._tool_execution_status(exec_result.output)
            if not bool(exec_result.success) or bool(exec_result.fallback_used):
                degraded = self._degrade_capability_after_tool_execution(
                    capability_node,
                    status or "failed",
                )
                graph.add_node(degraded)
                self._ensure_edge(
                    graph=graph,
                    source_id=degraded.id,
                    target_id=node_id,
                    kind=EdgeKind.FORGED_BY,
                    weight=0.6,
                )
                return
            if not self._tool_execution_is_real(exec_result.output):
                degraded = self._degrade_capability_after_tool_execution(
                    capability_node,
                    status or "not_implemented",
                )
                graph.add_node(degraded)
                self._ensure_edge(
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
            target_maturity = self._target_maturity_for_tool_execution(base_node, success_count)
        else:
            target_maturity = "tested" if action == "design_tooling" else "trusted"

        promoted = self._promote_capability_node(base_node, target_maturity=target_maturity)
        graph.add_node(promoted)
        self._ensure_edge(
            graph=graph,
            source_id=promoted.id,
            target_id=node_id,
            kind=EdgeKind.FORGED_BY,
            weight=0.85 if action == "stabilize_tooling" else (0.82 if action == "execute_tooling" else 0.75),
        )

    @staticmethod
    def _tool_execution_is_real(output: Any) -> bool:
        if not isinstance(output, dict):
            return False
        status = str(output.get("status", "")).strip().lower()
        if not status:
            return False
        if status in {"not_implemented", "fallback", "failed", "error"}:
            return False
        return True

    @staticmethod
    def _tool_execution_status(output: Any) -> str:
        if not isinstance(output, dict):
            return ""
        return str(output.get("status", "")).strip().lower()

    def _degrade_capability_after_tool_execution(
        self,
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
        weighted = updated.with_weight(self._capability_weight_for_maturity(updated.maturity))
        assert isinstance(weighted, CapabilityNode)
        return weighted

    def _target_maturity_for_tool_execution(
        self,
        node: CapabilityNode,
        success_count: int,
    ) -> str:
        if node.maturity == "deprecated":
            return "deprecated"
        tested_threshold = self._env_positive_int("ARNALDO_TOOL_EXEC_SUCCESSES_FOR_TESTED", default=2)
        trusted_threshold = self._env_positive_int("ARNALDO_TOOL_EXEC_SUCCESSES_FOR_TRUSTED", default=4)
        if success_count >= max(trusted_threshold, tested_threshold):
            return "trusted"
        if success_count >= tested_threshold:
            return "tested"
        return node.maturity

    def _promote_capability_node(
        self,
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

        adjusted = updated.with_weight(self._capability_weight_for_maturity(updated.maturity))
        assert isinstance(adjusted, CapabilityNode)
        return adjusted

    @staticmethod
    def _result_summary(result_payload: Dict[str, Any]) -> str:
        for key in ("status", "result", "goal", "goal_type"):
            value = result_payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:120]
        return "resultado registrado"

    @staticmethod
    def _synapse_node_id(agent_id: str, action: str, output_name: str | None = None) -> str:
        parts = ["syn", GraphRuntime._slug(agent_id), GraphRuntime._slug(action)]
        if output_name:
            parts.append(GraphRuntime._slug(output_name))
        return "_".join(parts)

    @staticmethod
    def _slug(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower().replace(".", "_"))
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        return normalized or "x"

    def _load_seed_graph(self) -> CognitiveGraph:
        seed = self.seed_graph_path
        if seed is None or not seed.exists():
            return CognitiveGraph()
        try:
            return CognitiveGraph.load(seed)
        except Exception:
            return CognitiveGraph()

    @staticmethod
    def _build_request(task: Any, capability_resolution: Dict[str, Any]) -> str:
        if GraphRuntime._is_lightweight_conversational_task(task) or GraphRuntime._is_conversational_cli_turn(
            task=task,
            capability_resolution=capability_resolution,
        ):
            context_raw = getattr(task, "context", {})
            context = context_raw if isinstance(context_raw, dict) else {}
            user_message = GraphRuntime._extract_primary_user_request(task)
            if not user_message:
                goal = task.goal if isinstance(task.goal, dict) else {}
                user_message = str(goal.get("statement", "")).strip()
            session_user_name = str(context.get("session_user_name", "")).strip()
            lines = [
                "Mode: conversational_reply",
                "UserMessage: %s" % user_message,
                (
                    "Instructions: responda em portugues (pt-BR), de forma natural e direta; "
                    "nao descreva pipeline, goal, deliverables, capabilities, logs ou etapas internas."
                ),
            ]
            if session_user_name:
                lines.append("SessionMemory.user_name: %s" % session_user_name)
                lines.append(
                    "Se o usuario perguntar sobre identidade/nome, use SessionMemory.user_name com prioridade."
                )
            return "\n".join(lines)

        capability_needs = [
            str(item.get("id", "")).strip()
            for item in task.capability_needs
            if str(item.get("id", "")).strip()
        ]
        missing = [
            str(item.get("id", "")).strip()
            for item in (capability_resolution.get("missing", []) or [])
            if str(item.get("id", "")).strip()
        ]
        degraded = [
            str(item.get("id", "")).strip()
            for item in (capability_resolution.get("degraded", []) or [])
            if str(item.get("id", "")).strip()
        ]
        uncertainties = [
            str(item.get("question", "")).strip()
            for item in task.uncertainty
            if str(item.get("question", "")).strip()
        ]
        deliverables = [
            str(item.get("id", "")).strip()
            for item in task.deliverables
            if str(item.get("id", "")).strip()
        ]

        return "\n".join(
            [
                "Goal: %s" % task.goal.get("statement", ""),
                "GoalType: %s" % task.goal.get("type", ""),
                "Deliverables: %s" % json.dumps(deliverables, ensure_ascii=True),
                "CapabilityNeeds: %s" % json.dumps(capability_needs, ensure_ascii=True),
                "MissingCapabilities: %s" % json.dumps(missing, ensure_ascii=True),
                "DegradedCapabilities: %s" % json.dumps(degraded, ensure_ascii=True),
                "Uncertainties: %s" % json.dumps(uncertainties, ensure_ascii=True),
            ]
        )

    @staticmethod
    def _select_execution_mode(topology: str) -> str:
        if topology == "parallel_with_synthesis":
            return "activates_parallel_levels"
        return "activates_reachable"

    @staticmethod
    def _normalize_execution_payload(result: Any) -> dict[str, Any]:
        if result.output is not None:
            normalized = to_dict(result.output)
        else:
            normalized = {}
        normalized["_meta"] = {
            "success": result.success,
            "fallback_used": result.fallback_used,
            "tier": result.tier,
            "refusal": result.refusal,
            "error": result.error,
        }
        return normalized

    def _trace(self, store: RunStore, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        event = RuntimeEvent(
            id=new_id("event"),
            run_id=run_id,
            created_at=utc_now(),
            event_type=event_type,
            payload=payload,
        )
        store.append_jsonl("trace.jsonl", to_dict(event))

    def _record_prompt_payload(
        self,
        *,
        store: RunStore,
        run_id: str,
        payload: Dict[str, Any],
    ) -> None:
        record = {
            "run_id": run_id,
            **payload,
        }
        store.append_jsonl("prompts.jsonl", record)
        messages = payload.get("messages")
        message_count = len(messages) if isinstance(messages, list) else 0
        raw_chat_kwargs = payload.get("chat_kwargs")
        chat_kwargs: Dict[str, Any] = raw_chat_kwargs if isinstance(raw_chat_kwargs, dict) else {}
        self._trace(
            store,
            run_id,
            "prompt_prepared",
            {
                "node_id": str(payload.get("node_id", "")).strip(),
                "agent_id": str(payload.get("agent_id", "")).strip(),
                "action": str(payload.get("action", "")).strip(),
                "capability_id": str(payload.get("capability_id", "")).strip(),
                "tier": str(payload.get("tier", "")).strip(),
                "response_model": str(payload.get("response_model", "")).strip(),
                "message_count": message_count,
                "max_tokens": int(chat_kwargs.get("max_tokens", 0) or 0),
                "timeout": float(chat_kwargs.get("timeout", 0.0) or 0.0),
                "reasoning_effort": str(chat_kwargs.get("reasoning_effort", "")).strip(),
            },
        )

    def _evidence(
        self,
        store: RunStore,
        run_id: str,
        task_id: str,
        record_type: str,
        summary: str,
        payload: Dict[str, Any],
    ) -> None:
        record = EvidenceRecord(
            id=new_id("evidence"),
            run_id=run_id,
            task_id=task_id,
            created_at=utc_now(),
            record_type=record_type,
            summary=summary,
            payload=payload,
        )
        store.append_jsonl("evidence.jsonl", to_dict(record))

    def _resolve_sandbox_dir(self, raw_path: Any) -> Path | None:
        if not raw_path:
            return None
        path = Path(str(raw_path))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_step_artifact(
        self,
        artifacts_path: Path | None,
        *,
        index: int,
        action: str,
        payload: Dict[str, Any],
    ) -> Path | None:
        if artifacts_path is None:
            return None
        safe_action = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in action)
        path = artifacts_path / ("step-%02d-%s.json" % (index, safe_action))
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return path
