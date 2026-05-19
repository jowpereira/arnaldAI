"""Execution engine para SynapseNodes com contratos tipados."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Callable

from .edges import EdgeKind, GraphEdge
from .nodes import NodeStatus, SynapseNode
from .store import CognitiveGraph
from arnaldo.llm.contracts import ContractModelRegistry


@dataclass(slots=True)
class StepContext:
    """Blackboard entre execuções de synapse com histórico versionado."""

    outputs: dict[str, Any] = field(default_factory=dict)
    tool_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_history: list[dict[str, Any]] = field(default_factory=list)
    version: int = 0
    history_limit: int = 512
    refusals: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def write(
        self,
        node_id: str,
        value: Any,
        *,
        action: str = "",
        agent_id: str = "",
        capability_id: str = "",
        channel: str = "llm",
    ) -> None:
        normalized_action = str(action).strip()
        normalized_agent = str(agent_id).strip()
        normalized_capability = str(capability_id).strip()
        normalized_channel = str(channel).strip() or "llm"
        with self._lock:
            self.outputs[node_id] = value
            if normalized_capability:
                payload = value if isinstance(value, dict) else {"result": value}
                self.tool_outputs[normalized_capability] = {
                    "node_id": node_id,
                    "action": normalized_action,
                    "agent_id": normalized_agent,
                    "channel": normalized_channel,
                    "output": payload,
                }
            self.version += 1
            event = {
                "version": self.version,
                "node_id": node_id,
                "action": normalized_action,
                "agent_id": normalized_agent,
                "capability_id": normalized_capability,
                "channel": normalized_channel,
                "status": self._extract_status(value),
                "excerpt": str(value)[:300],
            }
            self.output_history.append(event)
            overflow = len(self.output_history) - self.history_limit
            if overflow > 0:
                del self.output_history[:overflow]

    def read(self, node_id: str) -> Any | None:
        with self._lock:
            return self.outputs.get(node_id)

    def record_refusal(self, node_id: str, reason: str) -> None:
        with self._lock:
            self.refusals.append({"node_id": node_id, "reason": reason})

    def record_error(self, node_id: str, error: str) -> None:
        with self._lock:
            self.errors.append({"node_id": node_id, "error": error})

    def record_tool_output(self, node_id: str, capability_id: str, value: Any) -> None:
        if not capability_id:
            return
        self.write(
            node_id,
            value,
            capability_id=capability_id,
            channel="tool",
        )

    def snapshot_recent_outputs(self, *, limit: int = 3) -> dict[str, str]:
        with self._lock:
            if limit <= 0:
                return {}
            return {
                str(item["node_id"]): str(item["excerpt"])
                for item in self.output_history[-limit:]
            }

    def snapshot_recent_tool_outputs(self, *, limit: int = 3) -> dict[str, dict[str, str]]:
        with self._lock:
            if limit <= 0:
                return {}
            return {
                capability_id: {
                    "node_id": str(item.get("node_id", "")),
                    "action": str(item.get("action", ""))[:120],
                    "channel": str(item.get("channel", ""))[:40],
                    "status": str((item.get("output") or {}).get("status", ""))[:120],
                    "excerpt": str(item.get("output", {}))[:300],
                }
                for capability_id, item in list(self.tool_outputs.items())[-limit:]
            }

    def snapshot_related_outputs(
        self,
        *,
        action: str = "",
        capability_id: str = "",
        limit: int = 3,
    ) -> list[dict[str, str]]:
        normalized_action = str(action).strip()
        normalized_capability = str(capability_id).strip()
        if limit <= 0:
            return []

        with self._lock:
            history = list(self.output_history)

        if not history:
            return []

        ranked: list[tuple[int, int, dict[str, Any]]] = []
        for item in history:
            item_action = str(item.get("action", "")).strip()
            item_capability = str(item.get("capability_id", "")).strip()
            item_channel = str(item.get("channel", "")).strip()
            score = 0
            if normalized_capability and item_capability and item_capability == normalized_capability:
                score += 4
            if normalized_action and item_action and item_action == normalized_action:
                score += 3
            if item_channel == "tool":
                score += 1
            if score <= 0 and (normalized_action or normalized_capability):
                continue
            ranked.append((score, int(item.get("version", 0)), item))

        if not ranked:
            return []

        ranked.sort(key=lambda bucket: (bucket[0], bucket[1]), reverse=True)
        selected = [bucket[2] for bucket in ranked[:limit]]
        selected.sort(key=lambda item: int(item.get("version", 0)))
        return [
            {
                "version": str(item.get("version", "")),
                "node_id": str(item.get("node_id", "")),
                "action": str(item.get("action", "")),
                "capability_id": str(item.get("capability_id", "")),
                "channel": str(item.get("channel", "")),
                "status": str(item.get("status", "")),
                "excerpt": str(item.get("excerpt", "")),
            }
            for item in selected
        ]

    @staticmethod
    def _extract_status(value: Any) -> str:
        if isinstance(value, dict):
            status = str(value.get("status", "")).strip()
            if status:
                return status
        return "ok"


@dataclass(slots=True)
class SynapseExecutionResult:
    """Resultado padronizado de uma execução de synapse."""

    node_id: str
    tier: str
    success: bool
    output: Any | None = None
    refusal: str | None = None
    error: str | None = None
    fallback_used: bool = False


class ExecutionEngine:
    """Executa `SynapseNode` com `chat_typed`, fallback e feedback Hebb."""

    def __init__(
        self,
        *,
        graph: CognitiveGraph,
        llm_client: Any | None = None,
        contract_registry: ContractModelRegistry | None = None,
        model_registry: dict[str, type[Any]] | None = None,
        default_tier: str = "expert",
        strict_real: bool = True,
        on_prompt_prepared: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.graph = graph
        self.llm_client = llm_client
        self.contract_registry = contract_registry or ContractModelRegistry()
        if model_registry:
            self.contract_registry.register_many(model_registry)
        self.default_tier = default_tier
        self.strict_real = bool(strict_real)
        self._graph_lock = Lock()
        self._on_prompt_prepared = on_prompt_prepared

    def register_contract_model(
        self,
        model: type[Any],
        *,
        name: str | None = None,
    ) -> None:
        self.contract_registry.register(model, name=name)

    def execute_synapse(
        self,
        synapse_id: str,
        *,
        request: str,
        context: StepContext | None = None,
        tier_override: str | None = None,
        max_retries: int = 2,
        temperature: float = 0.2,
    ) -> SynapseExecutionResult:
        node = self.graph.get_node(synapse_id)
        if node is None:
            raise KeyError(f"SynapseNode '{synapse_id}' não encontrado")
        if not isinstance(node, SynapseNode):
            raise TypeError(f"node '{synapse_id}' não é SynapseNode")

        ctx = context or StepContext()
        with self._graph_lock:
            self.graph.activate(node.id)

        tier = str(tier_override or node.payload.get("tier_preference") or self.default_tier)
        if self._is_tool_execution_node(node):
            return self._execute_tooling_synapse(
                node=node,
                tier=tier,
                request=request,
                context=ctx,
            )

        contract_model = self._resolve_contract_model(node)

        if contract_model is None:
            if self.strict_real:
                with self._graph_lock:
                    self.graph.record_outcome(node.id, success=False)
                error = "missing_output_contract_model"
                ctx.record_error(node.id, error)
                raise RuntimeError(
                    f"strict_real habilitado: synapse '{node.id}' sem output_contract_model."
                )
            return self._fallback_result(
                node=node,
                tier=tier,
                context=ctx,
                reason="missing_output_contract_model",
                request=request,
            )

        if not self._llm_supports_typed():
            if self.strict_real:
                with self._graph_lock:
                    self.graph.record_outcome(node.id, success=False)
                error = "llm_client_unavailable"
                ctx.record_error(node.id, error)
                raise RuntimeError(
                    f"strict_real habilitado: llm_client indisponível para synapse '{node.id}'."
                )
            return self._fallback_result(
                node=node,
                tier=tier,
                context=ctx,
                reason="llm_client_unavailable",
                request=request,
            )

        messages = self._build_messages(node=node, request=request, context=ctx)
        action = str(node.payload.get("action", "")).strip()
        step_max_retries = self._resolve_payload_positive_int(node.payload.get("max_retries"), fallback=max_retries)
        step_temperature = self._resolve_payload_float(node.payload.get("temperature"), fallback=temperature)
        chat_kwargs: dict[str, Any] = {
            "max_retries": step_max_retries,
            "temperature": step_temperature,
        }
        step_max_tokens = self._resolve_payload_positive_int(node.payload.get("max_tokens"))
        if step_max_tokens is None:
            step_max_tokens = self._default_max_tokens_for_action(action=action, tier=tier)
        if step_max_tokens is not None:
            chat_kwargs["max_tokens"] = step_max_tokens
        step_timeout = self._resolve_payload_positive_float(node.payload.get("timeout"))
        if step_timeout is None:
            step_timeout = self._default_timeout_for_tier(tier)
        if step_timeout is not None:
            chat_kwargs["timeout"] = step_timeout
        reasoning_effort = self._resolve_payload_str(node.payload.get("reasoning_effort"))
        if not reasoning_effort:
            reasoning_effort = self._default_reasoning_effort_for_action(action=action, tier=tier)
        if reasoning_effort:
            chat_kwargs["reasoning_effort"] = reasoning_effort
        reasoning_summary = self._resolve_payload_str(node.payload.get("reasoning_summary"))
        if reasoning_summary:
            chat_kwargs["reasoning_summary"] = reasoning_summary

        if self._on_prompt_prepared is not None:
            prompt_event = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "node_id": node.id,
                "agent_id": str(node.payload.get("agent_id", "")).strip(),
                "action": action,
                "capability_id": str(node.payload.get("capability_id", "")).strip(),
                "tier": tier,
                "response_model": getattr(contract_model, "__name__", str(contract_model)),
                "messages": messages,
                "chat_kwargs": dict(chat_kwargs),
            }
            try:
                self._on_prompt_prepared(prompt_event)
            except Exception:
                # Observabilidade de prompt não pode interromper execução.
                pass

        try:
            response = self.llm_client.chat_typed(
                tier=tier,
                messages=messages,
                response_model=contract_model,
                **chat_kwargs,
            )
        except Exception as exc:  # pragma: no cover - protegido por teste
            if self.strict_real:
                with self._graph_lock:
                    self.graph.record_outcome(node.id, success=False)
                detail = self._format_exception_detail(exc)
                ctx.record_error(node.id, detail)
                raise RuntimeError(
                    f"strict_real habilitado: chamada LLM falhou no synapse '{node.id}': {detail}"
                ) from exc
            with self._graph_lock:
                self.graph.record_outcome(node.id, success=False)
            ctx.record_error(node.id, str(exc))
            return SynapseExecutionResult(
                node_id=node.id,
                tier=tier,
                success=False,
                error=str(exc),
            )

        if response.refusal is not None:
            if self.strict_real:
                with self._graph_lock:
                    self.graph.record_outcome(node.id, success=False)
                ctx.record_refusal(node.id, response.refusal)
                raise RuntimeError(
                    f"strict_real habilitado: refusal no synapse '{node.id}': {response.refusal}"
                )
            with self._graph_lock:
                self.graph.record_outcome(node.id, success=False)
            ctx.record_refusal(node.id, response.refusal)
            return SynapseExecutionResult(
                node_id=node.id,
                tier=tier,
                success=False,
                refusal=response.refusal,
            )

        if response.parsed is None:
            if self.strict_real:
                with self._graph_lock:
                    self.graph.record_outcome(node.id, success=False)
                error = "chat_typed retornou sem parsed"
                ctx.record_error(node.id, error)
                raise RuntimeError(
                    f"strict_real habilitado: chat_typed sem parsed no synapse '{node.id}'."
                )
            with self._graph_lock:
                self.graph.record_outcome(node.id, success=False)
            error = "chat_typed retornou sem parsed"
            ctx.record_error(node.id, error)
            return SynapseExecutionResult(
                node_id=node.id,
                tier=tier,
                success=False,
                error=error,
            )

        with self._graph_lock:
            self.graph.record_outcome(node.id, success=True)
        ctx.write(
            node.id,
            response.parsed,
            action=str(node.payload.get("action", "")),
            agent_id=str(node.payload.get("agent_id", "")),
            capability_id=str(node.payload.get("capability_id", "")),
            channel="llm",
        )
        return SynapseExecutionResult(
            node_id=node.id,
            tier=tier,
            success=True,
            output=response.parsed,
        )

    def execute_path(
        self,
        node_ids: list[str],
        *,
        request: str,
        context: StepContext | None = None,
        tier_override: str | None = None,
        max_retries: int = 2,
        temperature: float = 0.2,
    ) -> tuple[StepContext, list[SynapseExecutionResult]]:
        """Executa uma sequência explícita de synapses (ordem fornecida)."""
        ctx = context or StepContext()
        results: list[SynapseExecutionResult] = []
        current_request = request

        for node_id in node_ids:
            result = self.execute_synapse(
                node_id,
                request=current_request,
                context=ctx,
                tier_override=tier_override,
                max_retries=max_retries,
                temperature=temperature,
            )
            results.append(result)
            if result.success and result.output is not None:
                current_request = (
                    f"{request}\n\nOutput de {node_id}: "
                    f"{str(result.output)[:500]}"
                )

        return ctx, results

    def execute_activates_chain(
        self,
        root_synapse_id: str,
        *,
        request: str,
        max_steps: int = 16,
        allowed_node_ids: set[str] | None = None,
        context: StepContext | None = None,
        tier_override: str | None = None,
        max_retries: int = 2,
        temperature: float = 0.2,
    ) -> tuple[list[str], StepContext, list[SynapseExecutionResult]]:
        """Executa cadeia linear derivada de arestas `ACTIVATES`.

        Estratégia atual:
        - Seleciona o vizinho `ACTIVATES` com maior peso a cada passo
        - Evita ciclos por conjunto de visitados
        - Para quando não há próximo synapse elegível
        """
        path = self.plan_activates_path(
            root_synapse_id,
            max_steps=max_steps,
            allowed_node_ids=allowed_node_ids,
        )
        ctx, results = self.execute_path(
            path,
            request=request,
            context=context,
            tier_override=tier_override,
            max_retries=max_retries,
            temperature=temperature,
        )
        self._record_path_transition_outcomes(path, results)
        return path, ctx, results

    def execute_activates_reachable(
        self,
        root_synapse_id: str,
        *,
        request: str,
        max_steps: int = 64,
        allowed_node_ids: set[str] | None = None,
        context: StepContext | None = None,
        tier_override: str | None = None,
        max_retries: int = 2,
        temperature: float = 0.2,
    ) -> tuple[list[str], StepContext, list[SynapseExecutionResult]]:
        """Executa todos os synapses alcançáveis via `ACTIVATES` (ordem BFS)."""
        path = self.plan_activates_reachable(
            root_synapse_id,
            max_steps=max_steps,
            allowed_node_ids=allowed_node_ids,
        )
        ctx, results = self.execute_path(
            path,
            request=request,
            context=context,
            tier_override=tier_override,
            max_retries=max_retries,
            temperature=temperature,
        )
        self._record_reachable_transition_outcomes(path, results)
        return path, ctx, results

    def plan_activates_path(
        self,
        root_synapse_id: str,
        *,
        max_steps: int = 16,
        allowed_node_ids: set[str] | None = None,
    ) -> list[str]:
        if max_steps < 1:
            raise ValueError("max_steps deve ser >= 1")
        if self.graph.get_node(root_synapse_id) is None:
            raise KeyError(f"SynapseNode '{root_synapse_id}' não encontrado")
        if self._resolve_runnable_synapse(root_synapse_id, allowed_node_ids=allowed_node_ids) is None:
            return []

        path: list[str] = [root_synapse_id]
        visited: set[str] = {root_synapse_id}
        current = root_synapse_id

        while len(path) < max_steps:
            candidates = []
            for edge in self.graph.iter_edges_from(current, kinds=[EdgeKind.ACTIVATES]):
                if edge.target_id in visited:
                    continue
                target = self._resolve_runnable_synapse(
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
        self,
        root_synapse_id: str,
        *,
        max_steps: int = 64,
        allowed_node_ids: set[str] | None = None,
    ) -> list[str]:
        """Planeja ordem de execução BFS de todos os nós alcançáveis por `ACTIVATES`."""
        if max_steps < 1:
            raise ValueError("max_steps deve ser >= 1")
        if self.graph.get_node(root_synapse_id) is None:
            raise KeyError(f"SynapseNode '{root_synapse_id}' não encontrado")
        if self._resolve_runnable_synapse(root_synapse_id, allowed_node_ids=allowed_node_ids) is None:
            return []

        order: list[str] = []
        queue: list[str] = [root_synapse_id]
        seen: set[str] = set()

        while queue and len(order) < max_steps:
            current = queue.pop(0)
            if current in seen:
                continue
            node = self._resolve_runnable_synapse(
                current,
                allowed_node_ids=allowed_node_ids,
            )
            if node is None:
                continue
            seen.add(current)
            order.append(current)

            children: list[tuple[float, str]] = []
            for edge in self.graph.iter_edges_from(current, kinds=[EdgeKind.ACTIVATES]):
                target = self._resolve_runnable_synapse(
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
        self,
        root_synapse_id: str,
        *,
        max_steps: int = 64,
        allowed_node_ids: set[str] | None = None,
    ) -> list[list[str]]:
        """Planeja níveis BFS de `ACTIVATES` para execução com paralelismo por camada."""
        if max_steps < 1:
            raise ValueError("max_steps deve ser >= 1")
        if self.graph.get_node(root_synapse_id) is None:
            raise KeyError(f"SynapseNode '{root_synapse_id}' não encontrado")
        if self._resolve_runnable_synapse(root_synapse_id, allowed_node_ids=allowed_node_ids) is None:
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
                node = self._resolve_runnable_synapse(
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
                for edge in self.graph.iter_edges_from(parent_id, kinds=[EdgeKind.ACTIVATES]):
                    target = self._resolve_runnable_synapse(
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

    def execute_activates_parallel(
        self,
        root_synapse_id: str,
        *,
        request: str,
        max_steps: int = 64,
        max_parallel: int = 4,
        allowed_node_ids: set[str] | None = None,
        context: StepContext | None = None,
        tier_override: str | None = None,
        max_retries: int = 2,
        temperature: float = 0.2,
    ) -> tuple[list[str], StepContext, list[SynapseExecutionResult]]:
        """Executa níveis de `ACTIVATES` com concorrência por camada."""
        levels = self.plan_activates_levels(
            root_synapse_id,
            max_steps=max_steps,
            allowed_node_ids=allowed_node_ids,
        )
        flat_order = [node_id for level in levels for node_id in level]
        ctx = context or StepContext()
        results: list[SynapseExecutionResult] = []
        current_request = request
        previous_level: list[str] = []

        for level in levels:
            if not level:
                continue

            if len(level) == 1:
                result = self.execute_synapse(
                    level[0],
                    request=current_request,
                    context=ctx,
                    tier_override=tier_override,
                    max_retries=max_retries,
                    temperature=temperature,
                )
                level_results = [result]
            else:
                workers = max(1, min(max_parallel, len(level)))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    future_by_node = {
                        node_id: executor.submit(
                            self.execute_synapse,
                            node_id,
                            request=current_request,
                            context=ctx,
                            tier_override=tier_override,
                            max_retries=max_retries,
                            temperature=temperature,
                        )
                        for node_id in level
                    }
                    level_results = [future_by_node[node_id].result() for node_id in level]

            self._record_level_transition_outcomes(previous_level, level_results)
            successful_nodes = [
                result.node_id
                for result in level_results
                if result.success and not result.fallback_used
            ]
            self._record_collaboration_edges(successful_nodes, success=True)

            results.extend(level_results)
            success_outputs = [r.output for r in level_results if r.success and r.output is not None]
            if success_outputs:
                current_request = (
                    f"{request}\n\nOutputs do nível atual: "
                    + json.dumps([str(out)[:300] for out in success_outputs], ensure_ascii=True)
                )
            previous_level = [result.node_id for result in level_results]

        return flat_order, ctx, results

    def _record_path_transition_outcomes(
        self,
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
            success = self._edge_success_from_result(target_result)
            if success is None:
                continue
            self._record_edge_outcome_between(
                source_id=source_id,
                target_id=target_id,
                kind=EdgeKind.ACTIVATES,
                success=success,
                create_if_missing=False,
            )

    def _record_reachable_transition_outcomes(
        self,
        path: list[str],
        results: list[SynapseExecutionResult],
    ) -> None:
        if len(path) < 2 or not results:
            return

        order_by_node = {node_id: index for index, node_id in enumerate(path)}
        result_by_node = {result.node_id: result for result in results}

        with self._graph_lock:
            for target_id in path:
                target_result = result_by_node.get(target_id)
                success = self._edge_success_from_result(target_result)
                if success is None:
                    continue
                target_index = order_by_node.get(target_id)
                if target_index is None:
                    continue
                for edge in self.graph.iter_edges_to(
                    target_id,
                    kinds=[EdgeKind.ACTIVATES],
                    active_only=False,
                ):
                    source_index = order_by_node.get(edge.source_id)
                    if source_index is None:
                        continue
                    if source_index >= target_index:
                        continue
                    self.graph.record_edge_outcome(edge.id, success=success)

    def _record_level_transition_outcomes(
        self,
        previous_level: list[str],
        level_results: list[SynapseExecutionResult],
    ) -> None:
        if not previous_level or not level_results:
            return

        with self._graph_lock:
            for result in level_results:
                success = self._edge_success_from_result(result)
                if success is None:
                    continue
                for source_id in previous_level:
                    for edge in self.graph.iter_edges_from(
                        source_id,
                        kinds=[EdgeKind.ACTIVATES],
                        active_only=False,
                    ):
                        if edge.target_id != result.node_id:
                            continue
                        self.graph.record_edge_outcome(edge.id, success=success)

    @staticmethod
    def _edge_success_from_result(result: SynapseExecutionResult | None) -> bool | None:
        if result is None:
            return None
        if result.fallback_used:
            return None
        return bool(result.success)

    def _record_edge_outcome_between(
        self,
        *,
        source_id: str,
        target_id: str,
        kind: EdgeKind,
        success: bool,
        create_if_missing: bool,
    ) -> None:
        with self._graph_lock:
            matched = False
            for edge in self.graph.iter_edges_from(
                source_id,
                kinds=[kind],
                active_only=False,
            ):
                if edge.target_id != target_id:
                    continue
                self.graph.record_edge_outcome(edge.id, success=success)
                matched = True
            if matched or not create_if_missing:
                return

            new_edge = GraphEdge.connect(
                source_id,
                target_id,
                kind,
            )
            self.graph.add_edge(new_edge)
            self.graph.record_edge_outcome(new_edge.id, success=success)

    def _record_collaboration_edges(self, node_ids: list[str], *, success: bool) -> None:
        unique_ids = sorted({node_id for node_id in node_ids if node_id})
        if len(unique_ids) < 2:
            return
        for idx, left_id in enumerate(unique_ids):
            for right_id in unique_ids[idx + 1:]:
                self._record_edge_outcome_between(
                    source_id=left_id,
                    target_id=right_id,
                    kind=EdgeKind.COLLABORATED_WITH,
                    success=success,
                    create_if_missing=True,
                )
                self._record_edge_outcome_between(
                    source_id=right_id,
                    target_id=left_id,
                    kind=EdgeKind.COLLABORATED_WITH,
                    success=success,
                    create_if_missing=True,
                )

    @staticmethod
    def _is_tool_execution_node(node: SynapseNode) -> bool:
        return str(node.payload.get("action", "")).strip() == "execute_tooling"

    def _execute_tooling_synapse(
        self,
        *,
        node: SynapseNode,
        tier: str,
        request: str,
        context: StepContext,
    ) -> SynapseExecutionResult:
        capability_id = str(node.payload.get("capability_id", "")).strip()
        module_path_raw = str(node.payload.get("module_path", "")).strip()
        if not module_path_raw:
            if self.strict_real:
                with self._graph_lock:
                    self.graph.record_outcome(node.id, success=False)
                error = "execute_tooling sem module_path"
                context.record_error(node.id, error)
                raise RuntimeError(
                    f"strict_real habilitado: execute_tooling sem module_path no synapse '{node.id}'."
                )
            with self._graph_lock:
                self.graph.record_outcome(node.id, success=False)
            error = "execute_tooling sem module_path"
            context.record_error(node.id, error)
            return SynapseExecutionResult(
                node_id=node.id,
                tier=tier,
                success=False,
                error=error,
            )

        module_path = Path(module_path_raw)
        if not module_path.exists():
            if self.strict_real:
                with self._graph_lock:
                    self.graph.record_outcome(node.id, success=False)
                error = "module_path_not_found: %s" % module_path
                context.record_error(node.id, error)
                raise RuntimeError(
                    f"strict_real habilitado: module_path não encontrado no synapse '{node.id}': {module_path}"
                )
            with self._graph_lock:
                self.graph.record_outcome(node.id, success=False)
            error = "module_path_not_found: %s" % module_path
            context.record_error(node.id, error)
            return SynapseExecutionResult(
                node_id=node.id,
                tier=tier,
                success=False,
                error=error,
            )

        try:
            module_name = "arnaldo_tool_%s_%s" % (node.id, abs(hash(str(module_path))))
            spec = importlib.util.spec_from_file_location(module_name, str(module_path))
            if spec is None or spec.loader is None:
                raise RuntimeError("nao foi possivel criar spec para %s" % module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            runner = getattr(module, "run", None)
            if not callable(runner):
                raise RuntimeError("modulo %s nao define funcao run(payload)" % module_path)

            raw_output = runner(
                {
                    "request": request,
                    "capability_id": capability_id,
                    "node_id": node.id,
                    "context": self._context_snapshot(context, capability_id=capability_id),
                }
            )
            if isinstance(raw_output, dict):
                output = dict(raw_output)
            else:
                output = {"result": raw_output}
            output.setdefault("status", "completed")
            if capability_id:
                output.setdefault("capability_id", capability_id)

            with self._graph_lock:
                self.graph.record_outcome(node.id, success=True)
            context.write(
                node.id,
                output,
                action=str(node.payload.get("action", "")),
                agent_id=str(node.payload.get("agent_id", "")),
                capability_id=capability_id,
                channel="tool",
            )
            return SynapseExecutionResult(
                node_id=node.id,
                tier=tier,
                success=True,
                output=output,
            )
        except Exception as exc:
            if self.strict_real:
                with self._graph_lock:
                    self.graph.record_outcome(node.id, success=False)
                error = "tool_execution_failed: %s" % exc
                context.record_error(node.id, error)
                raise RuntimeError(
                    f"strict_real habilitado: falha em execute_tooling no synapse '{node.id}': {exc}"
                ) from exc
            with self._graph_lock:
                self.graph.record_outcome(node.id, success=False)
            error = "tool_execution_failed: %s" % exc
            context.record_error(node.id, error)
            return SynapseExecutionResult(
                node_id=node.id,
                tier=tier,
                success=False,
                error=error,
            )

    @staticmethod
    def _context_snapshot(
        context: StepContext,
        *,
        limit: int = 3,
        capability_id: str = "",
    ) -> dict[str, Any]:
        return {
            "context_version": context.version,
            "recent_outputs": context.snapshot_recent_outputs(limit=limit),
            "recent_tool_outputs": context.snapshot_recent_tool_outputs(limit=limit),
            "related_outputs": context.snapshot_related_outputs(
                capability_id=capability_id,
                limit=limit,
            ),
        }

    def _resolve_runnable_synapse(
        self,
        node_id: str,
        *,
        allowed_node_ids: set[str] | None = None,
    ) -> SynapseNode | None:
        if allowed_node_ids is not None and node_id not in allowed_node_ids:
            return None
        node = self.graph.get_node(node_id)
        if not isinstance(node, SynapseNode):
            return None
        if node.status in {NodeStatus.STALE, NodeStatus.ARCHIVED}:
            return None
        return node

    def _resolve_contract_model(self, node: SynapseNode) -> type[Any] | None:
        value = node.payload.get("output_contract_model")
        if value is None:
            return None
        if isinstance(value, type):
            return value
        if isinstance(value, str):
            return self.contract_registry.resolve(value)
        return None

    def _llm_supports_typed(self) -> bool:
        if self.llm_client is None:
            return False
        if not hasattr(self.llm_client, "chat_typed"):
            return False
        configured = getattr(self.llm_client, "is_configured", True)
        return bool(configured)

    @staticmethod
    def _format_exception_detail(exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        status = getattr(exc, "status", None)
        body = str(getattr(exc, "body", "") or "").strip()
        if isinstance(status, int):
            message = f"{message} (status={status})"
        if not body:
            return message
        compact_body = " ".join(body.split())
        if len(compact_body) > 600:
            compact_body = compact_body[:600] + "..."
        return f"{message} | body={compact_body}"

    @staticmethod
    def _resolve_payload_positive_int(value: Any, *, fallback: int | None = None) -> int | None:
        if value is None:
            return fallback
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return fallback
        if parsed <= 0:
            return fallback
        return parsed

    @staticmethod
    def _resolve_payload_positive_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return parsed

    @staticmethod
    def _resolve_payload_float(value: Any, *, fallback: float) -> float:
        if value is None:
            return fallback
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _resolve_payload_str(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _default_timeout_for_tier(tier: str) -> float:
        normalized = str(tier).strip().lower()
        if normalized == "fast":
            return 45.0
        if normalized == "god":
            return 300.0
        if normalized == "codex":
            return 240.0
        return 240.0

    @staticmethod
    def _default_max_tokens_for_action(*, action: str, tier: str) -> int:
        normalized_action = str(action).strip()
        by_action: dict[str, int] = {
            "frame_intent": 900,
            "clarify_uncertainties": 1200,
            "decompose_work": 1200,
            "explore_path_a": 1200,
            "explore_path_b": 1200,
            "design_tooling": 1200,
            "stabilize_tooling": 1200,
            "compose_tooling": 1400,
            "draft_artifact": 1600,
            "synthesize_artifact": 1600,
            "critic_review": 1400,
            "risk_review": 1400,
            "decision_synthesis": 1400,
        }
        if normalized_action in by_action:
            return by_action[normalized_action]

        normalized_tier = str(tier).strip().lower()
        if normalized_tier == "fast":
            return 800
        if normalized_tier == "god":
            return 2000
        if normalized_tier == "codex":
            return 1800
        return 1400

    @staticmethod
    def _default_reasoning_effort_for_action(*, action: str, tier: str) -> str:
        normalized_tier = str(tier).strip().lower()
        if normalized_tier not in {"expert", "god", "codex"}:
            return ""
        normalized_action = str(action).strip()
        if normalized_action in {
            "frame_intent",
            "clarify_uncertainties",
            "decompose_work",
            "explore_path_a",
            "explore_path_b",
            "design_tooling",
            "stabilize_tooling",
        }:
            return "low"
        if normalized_action in {"critic_review", "risk_review", "decision_synthesis"}:
            return "medium"
        return "medium"

    @staticmethod
    def _build_messages(
        *,
        node: SynapseNode,
        request: str,
        context: StepContext,
    ) -> list[dict[str, str]]:
        system_parts = [
            "Você é um synapse especializado do Arnaldo.",
            f"Role: {node.payload.get('role', 'generic')}.",
            f"Action: {node.payload.get('action', '')}.",
            f"Objective: {node.payload.get('objective', '')}.",
            f"Epistemic style: {node.payload.get('epistemic_style', 'evidence_first')}.",
            "Responda de forma estritamente estruturada conforme o contrato de saída.",
        ]
        output_contract = node.payload.get("output_contract")
        if output_contract:
            system_parts.append(
                "Contrato declarativo de saída: "
                + json.dumps(output_contract, ensure_ascii=True, separators=(",", ":"))
            )

        user_content = request
        previous = context.snapshot_recent_outputs(limit=3)
        if previous:
            # Mantém o contexto curto para evitar prompt bloat.
            user_content += (
                "\n\nContexto prévio (últimos outputs): "
                + json.dumps(previous, ensure_ascii=True, separators=(",", ":"))
            )
        tool_outputs = context.snapshot_recent_tool_outputs(limit=3)
        if tool_outputs:
            user_content += (
                "\n\nSaidas de ferramentas recentes: "
                + json.dumps(tool_outputs, ensure_ascii=True, separators=(",", ":"))
            )
        related = context.snapshot_related_outputs(
            action=str(node.payload.get("action", "")),
            capability_id=str(node.payload.get("capability_id", "")),
            limit=4,
        )
        if related:
            user_content += (
                "\n\nContexto relacionado (acao/capability): "
                + json.dumps(related, ensure_ascii=True, separators=(",", ":"))
            )

        return [
            {"role": "system", "content": " ".join(system_parts)},
            {"role": "user", "content": user_content},
        ]

    def _fallback_result(
        self,
        *,
        node: SynapseNode,
        tier: str,
        context: StepContext,
        reason: str,
        request: str,
    ) -> SynapseExecutionResult:
        payload = {
            "status": "fallback",
            "reason": reason,
            "role": node.payload.get("role", "generic"),
            "objective": node.payload.get("objective", ""),
            "request_excerpt": request[:180],
        }
        context.write(
            node.id,
            payload,
            action=str(node.payload.get("action", "")),
            agent_id=str(node.payload.get("agent_id", "")),
            capability_id=str(node.payload.get("capability_id", "")),
            channel="fallback",
        )
        return SynapseExecutionResult(
            node_id=node.id,
            tier=tier,
            success=True,
            output=payload,
            fallback_used=True,
        )
