"""graph_runtime_postprocess — pós-processamento de resultados de execução.

Extrai o loop de processamento de step_results e a finalização do run().
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .evolution import _evolve_capability_nodes
from .infra import _normalize_execution_payload
from .nodes import _record_step_memory
from .tracing import (
    _apply_graph_retention,
    _evidence,
    _trace,
    _write_step_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path

    from arnaldo.graph import SynapseExecutionResult
    from arnaldo.storage import RunStore


def _process_execution_results(
    *,
    execution_results: list[SynapseExecutionResult],
    step_by_node: dict[str, dict[str, Any]],
    graph: Any,
    store: RunStore,
    run_id: str,
    task: Any,
    artifacts_path: Path | None,
) -> list[dict[str, Any]]:
    """Itera sobre resultados de execução e produz step_results."""
    step_results: list[dict[str, Any]] = []
    previous_memory_node_id: str | None = None

    for index, exec_result in enumerate(execution_results, start=1):
        item = step_by_node.get(exec_result.node_id)
        if item is None:
            _trace(
                store,
                run_id,
                "orphan_synapse_skipped",
                {"node_id": exec_result.node_id, "index": index},
            )
            continue

        result_payload = _normalize_execution_payload(exec_result)
        step_result: dict[str, Any] = {
            "step_id": item["id"],
            "agent_id": item["agent_id"],
            "action": item["action"],
            "output": item["output"],
            "result": result_payload,
            "uncertainties": [entry["question"] for entry in task.uncertainty],
        }
        if item.get("capability_id"):
            step_result["capability_id"] = item["capability_id"]

        step_artifact = _write_step_artifact(
            artifacts_path,
            index=index,
            action=item["action"],
            payload=step_result,
        )
        if step_artifact:
            step_result["sandbox_artifact"] = str(step_artifact)
        step_results.append(step_result)

        current_memory_node_id = _record_step_memory(
            graph=graph,
            run_id=run_id,
            node_id=exec_result.node_id,
            step_item=item,
            result_payload=result_payload,
            previous_memory_id=previous_memory_node_id,
        )
        if current_memory_node_id:
            previous_memory_node_id = current_memory_node_id

        _evolve_capability_nodes(
            graph=graph,
            node_id=exec_result.node_id,
            step_item=item,
            exec_result=exec_result,
        )

        _trace(store, run_id, "step_completed", step_result)
        _record_step_evidence(
            store,
            run_id,
            task.id,
            item,
            exec_result,
            result_payload,
        )

    return step_results


def _record_step_evidence(
    store: RunStore,
    run_id: str,
    task_id: str,
    item: dict[str, Any],
    exec_result: SynapseExecutionResult,
    result_payload: dict[str, Any],
) -> None:
    """Registra evidência de um step no ledger."""
    if exec_result.refusal is not None:
        _evidence(
            store,
            run_id,
            task_id,
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
        _evidence(
            store,
            run_id,
            task_id,
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
        _evidence(
            store,
            run_id,
            task_id,
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
        _evidence(
            store,
            run_id,
            task_id,
            "step_completed",
            "Etapa %s executada via synapse tipado." % item["action"],
            {
                "node_id": exec_result.node_id,
                "step_id": item["id"],
                "action": item["action"],
                "result": result_payload,
            },
        )


def _finalize_run(
    *,
    graph: Any,
    store: RunStore,
    run_id: str,
    task: Any,
    organization: Any,
    policy: Any,
    step_results: list[dict[str, Any]],
    step_context: Any,
    allowed_node_ids: set[str],
    artifacts_path: Path | None,
    temp_path: Path | None,
) -> tuple[Any, str]:
    """Finaliza o run: artifact, retention, persistência do grafo."""
    from ..local import render_artifact
    from ..base import RuntimeResult

    artifact = render_artifact(task, organization, policy, step_results)
    artifact_path = store.write_text("artifact.md", artifact)
    if artifacts_path:
        (artifacts_path / "artifact.md").write_text(artifact, encoding="utf-8")

    if step_context.refusals:
        _trace(
            store,
            run_id,
            "graph_runtime_refusals",
            {"count": len(step_context.refusals), "items": step_context.refusals},
        )
    if step_context.errors:
        _trace(
            store,
            run_id,
            "graph_runtime_errors",
            {"count": len(step_context.errors), "items": step_context.errors},
        )

    if temp_path:
        (temp_path / "runtime-finished.txt").write_text(
            "completed=true\n",
            encoding="utf-8",
        )

    retention = _apply_graph_retention(
        graph=graph,
        run_id=run_id,
        keep_synapse_ids=allowed_node_ids,
    )
    _trace(store, run_id, "graph_retention_applied", retention)

    graph_path = store.path("execution-graph.msgpack")
    graph.persist(graph_path)
    _trace(
        store,
        run_id,
        "graph_persisted",
        {
            "path": str(graph_path),
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
        },
    )

    _trace(
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
