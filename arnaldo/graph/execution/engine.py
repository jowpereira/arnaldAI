"""Execution engine para SynapseNodes com contratos tipados."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable

from ..nodes import SynapseNode
from ..store import CognitiveGraph
from .context import StepContext, SynapseExecutionResult
from arnaldo.llm.contracts import ContractModelRegistry
from . import defaults as _defaults
from . import strategies as _strategies
from . import tooling as _tooling


class ExecutionEngine:
    """Executa `SynapseNode` com `chat_typed` e feedback Hebb."""

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
        if _tooling._is_tool_execution_node(node):
            return _tooling._execute_tooling_synapse(
                self,
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
            return _defaults._degraded_result(
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
            return _defaults._degraded_result(
                node=node,
                tier=tier,
                context=ctx,
                reason="llm_client_unavailable",
                request=request,
            )

        messages = _defaults._build_messages(node=node, request=request, context=ctx)
        action = str(node.payload.get("action", "")).strip()
        chat_kwargs = _defaults._build_chat_kwargs(node, action, tier, max_retries, temperature)

        if self._on_prompt_prepared is not None:
            self._fire_prompt_event(node, action, tier, contract_model, messages, chat_kwargs)

        try:
            response = self.llm_client.chat_typed(
                tier=tier,
                messages=messages,
                response_model=contract_model,
                **chat_kwargs,
            )
        except Exception as exc:
            return self._handle_llm_error(node, tier, ctx, exc)

        if response.refusal is not None:
            return self._handle_refusal(node, tier, ctx, response.refusal)

        if response.parsed is None:
            return self._handle_no_parsed(node, tier, ctx)

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
                current_request = f"{request}\n\nOutput de {node_id}: {str(result.output)[:500]}"
        return ctx, results

    def execute_activates_chain(self, root_synapse_id, **kwargs):
        return _strategies.execute_activates_chain(self, root_synapse_id, **kwargs)

    def execute_activates_reachable(self, root_synapse_id, **kwargs):
        return _strategies.execute_activates_reachable(self, root_synapse_id, **kwargs)

    def execute_activates_parallel(self, root_synapse_id, **kwargs):
        return _strategies.execute_activates_parallel(self, root_synapse_id, **kwargs)

    def plan_activates_path(self, root_synapse_id, **kwargs):
        return _strategies.plan_activates_path(self, root_synapse_id, **kwargs)

    def plan_activates_reachable(self, root_synapse_id, **kwargs):
        return _strategies.plan_activates_reachable(self, root_synapse_id, **kwargs)

    def plan_activates_levels(self, root_synapse_id, **kwargs):
        return _strategies.plan_activates_levels(self, root_synapse_id, **kwargs)

    # ── Internals ────────────────────────────────────────────────────

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

    def _fire_prompt_event(
        self,
        node: SynapseNode,
        action: str,
        tier: str,
        contract_model: type[Any],
        messages: list,
        chat_kwargs: dict,
    ) -> None:
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
            pass

    def _handle_llm_error(
        self,
        node: SynapseNode,
        tier: str,
        ctx: StepContext,
        exc: Exception,
    ) -> SynapseExecutionResult:
        detail = _defaults._format_exception_detail(exc)
        return self._handle_failure(
            node,
            tier,
            ctx,
            error=str(exc),
            error_detail=detail,
            strict_msg=f"chamada LLM falhou no synapse '{node.id}': {detail}",
            raise_from=exc,
        )

    def _handle_refusal(
        self,
        node: SynapseNode,
        tier: str,
        ctx: StepContext,
        refusal: str,
    ) -> SynapseExecutionResult:
        return self._handle_failure(
            node,
            tier,
            ctx,
            refusal=refusal,
            strict_msg=f"refusal no synapse '{node.id}': {refusal}",
        )

    def _handle_no_parsed(
        self,
        node: SynapseNode,
        tier: str,
        ctx: StepContext,
    ) -> SynapseExecutionResult:
        return self._handle_failure(
            node,
            tier,
            ctx,
            error="chat_typed retornou sem parsed",
            strict_msg=f"chat_typed sem parsed no synapse '{node.id}'.",
        )

    def _handle_failure(
        self,
        node: SynapseNode,
        tier: str,
        ctx: StepContext,
        *,
        error: str | None = None,
        error_detail: str | None = None,
        refusal: str | None = None,
        strict_msg: str = "",
        raise_from: Exception | None = None,
    ) -> SynapseExecutionResult:
        with self._graph_lock:
            self.graph.record_outcome(node.id, success=False)
        if refusal:
            ctx.record_refusal(node.id, refusal)
        elif error_detail:
            ctx.record_error(node.id, error_detail)
        elif error:
            ctx.record_error(node.id, error)
        if self.strict_real:
            exc = RuntimeError(f"strict_real habilitado: {strict_msg}")
            if raise_from:
                raise exc from raise_from
            raise exc
        return SynapseExecutionResult(
            node_id=node.id,
            tier=tier,
            success=False,
            error=error,
            refusal=refusal,
        )
