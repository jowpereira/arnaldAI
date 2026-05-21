"""Executores de cadeia/BFS/paralelo sobre o grafo de ativação."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import ExecutionEngine

from .context import StepContext, SynapseExecutionResult
from . import plasticity as _plasticity
from .strategies import (
    plan_activates_path,
    plan_activates_levels,
    plan_activates_reachable,
)


def execute_activates_chain(
    engine: ExecutionEngine,
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
    """Executa cadeia linear derivada de arestas ACTIVATES."""
    path = plan_activates_path(
        engine,
        root_synapse_id,
        max_steps=max_steps,
        allowed_node_ids=allowed_node_ids,
    )
    ctx, results = engine.execute_path(
        path,
        request=request,
        context=context,
        tier_override=tier_override,
        max_retries=max_retries,
        temperature=temperature,
    )
    _plasticity._record_path_transition_outcomes(engine, path, results)
    return path, ctx, results


def execute_activates_reachable(
    engine: ExecutionEngine,
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
    """Executa todos os synapses alcançáveis via ACTIVATES (ordem BFS)."""
    path = plan_activates_reachable(
        engine,
        root_synapse_id,
        max_steps=max_steps,
        allowed_node_ids=allowed_node_ids,
    )
    ctx, results = engine.execute_path(
        path,
        request=request,
        context=context,
        tier_override=tier_override,
        max_retries=max_retries,
        temperature=temperature,
    )
    _plasticity._record_reachable_transition_outcomes(engine, path, results)
    return path, ctx, results


def execute_activates_parallel(
    engine: ExecutionEngine,
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
    """Executa níveis de ACTIVATES com concorrência por camada."""
    levels = plan_activates_levels(
        engine,
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
            result = engine.execute_synapse(
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
                        engine.execute_synapse,
                        node_id,
                        request=current_request,
                        context=ctx,
                        tier_override=tier_override,
                        max_retries=max_retries,
                        temperature=temperature,
                    )
                    for node_id in level
                }
                level_results = [future_by_node[nid].result() for nid in level]

        _plasticity._record_level_transition_outcomes(engine, previous_level, level_results)
        successful = [r.node_id for r in level_results if r.success and not r.fallback_used]
        _plasticity._record_collaboration_edges(engine, successful, success=True)
        results.extend(level_results)
        success_outputs = [r.output for r in level_results if r.success and r.output is not None]
        if success_outputs:
            current_request = f"{request}\n\nOutputs do nível atual: " + json.dumps(
                [str(out)[:300] for out in success_outputs], ensure_ascii=True
            )
        previous_level = [r.node_id for r in level_results]

    return flat_order, ctx, results
