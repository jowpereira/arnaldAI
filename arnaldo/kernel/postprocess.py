"""Pós-processamento do pipeline — gap detection, plasticidade, memória."""

from __future__ import annotations

from typing import Any, Dict

from arnaldo.storage import RunStore

from . import graph_ops as _graph
from . import render as _render
from . import session as _session
from .plasticity import apply_post_run_plasticity


def post_process_run(
    *,
    store: RunStore,
    run_id: str,
    task: Any,
    organization: Any,
    session: Any,
    runtime_result: Any,
    adaptive_plan: Any,
    files: Dict[str, Any],
    gap_detector: Any,
    memory: Any,
    sessions: Any,
    capabilities: Any,
    tool_forge: Any,
    runtime: Any,
    retrieval: Any,
    complexity: Any,
) -> Any:
    """Pós-processamento: gap, plasticidade, memória, sessão."""
    from arnaldo.runtime import GraphRuntime

    execution_graph = store.path("execution-graph.msgpack")
    if execution_graph.exists():
        files["execution_graph"] = execution_graph
        session = sessions.update_preferences(
            session,
            {"execution_graph_uri": str(execution_graph)},
        )
        if isinstance(runtime, GraphRuntime):
            session = _graph.post_process_graph(
                capabilities,
                sessions,
                tool_forge,
                execution_graph,
                files=files,
                session=session,
                run_id=run_id,
                task=task,
                store=store,
                adaptive_plan=adaptive_plan,
            )

    files["result"] = store.write_text(
        "result.md",
        _render.render_result(run_id, files, organization.topology),
    )

    gap_report = gap_detector.analyze(task, list(runtime_result.step_results))
    if gap_report.status != "ok":
        _session.evidence(
            store,
            run_id,
            task.id,
            "reality_gap_detected",
            ",".join(gap_report.warnings) or "gap_detected",
        )

    # Hebbian pós-run
    if execution_graph.exists():
        from arnaldo.graph import CognitiveGraph

        try:
            exec_graph = CognitiveGraph.load(execution_graph)
            plasticity_report = apply_post_run_plasticity(
                exec_graph,
                step_results=list(runtime_result.step_results),
                run_success=gap_report.status == "ok",
            )
            exec_graph.persist(execution_graph)
            _session.evidence(
                store,
                run_id,
                task.id,
                "hebbian_post_run",
                "Plasticidade pós-run aplicada.",
                plasticity_report,
            )
        except Exception:
            pass

    # Persiste artefatos de diagnóstico
    if retrieval.has_context:
        store.write_json(
            "retrieval-context.json",
            {
                "memories": retrieval.relevant_memories,
                "synapses": retrieval.relevant_synapses,
                "inhibited": retrieval.inhibited_synapses,
            },
        )
    store.write_json("request-classification.json", complexity.to_dict())

    _session.remember(
        memory,
        run_id,
        task.goal,
        files,
        session.id,
        adaptive_plan,
        step_results=list(runtime_result.step_results),
    )
    return session, gap_report
