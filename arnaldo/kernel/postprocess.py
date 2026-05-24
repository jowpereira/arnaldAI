"""Pós-processamento do pipeline — gap detection, plasticidade, memória."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict

from arnaldo.memory.models import MemoryRecord
from arnaldo.storage import RunStore

from . import graph_ops as _graph
from . import render as _render
from . import session as _session
from .plasticity import apply_post_run_plasticity

logger = logging.getLogger("arnaldo.kernel")


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
        except Exception as exc:
            logger.warning("plasticidade pós-run falhou: %s", exc)

    # Consolidação episodic → semantic
    try:
        from arnaldo.memory.consolidation import consolidate_episodic_memories

        memory_graph = memory.load_graph() if hasattr(memory, "load_graph") else None
        if memory_graph is not None:
            consol = consolidate_episodic_memories(memory_graph)
            if consol.created_semantic_ids:
                logger.info(
                    "Consolidação: %d semânticos criados de %d episódicos",
                    len(consol.created_semantic_ids),
                    len(consol.source_episodic_ids),
                )
                if hasattr(memory, "_persist_graph_state"):
                    memory._persist_graph_state()
    except Exception as exc:
        logger.warning("consolidação episodic→semantic falhou: %s", exc)

    # Execution synapse tracking
    # TODO: persistir tracker entre runs para patterns cross-run
    try:
        from arnaldo.graph.synapse_candidates import ExecutionSynapseTracker

        tracker = ExecutionSynapseTracker()
        for result in list(runtime_result.step_results):
            node_id = str(result.get("node_id", "")).strip()
            role = str(result.get("role", "")).strip()
            objective = str(result.get("objective", "")).strip() or str(task.goal)[:100]
            if node_id and role:
                tracker.observe(
                    pattern_key=f"{role}::{node_id}",
                    role=role,
                    objective=objective,
                    success=bool(result.get("success", False)),
                )
        # Materializa candidatos prontos
        memory_graph = memory.load_graph() if hasattr(memory, "load_graph") else None
        if memory_graph is not None:
            for candidate in tracker.ready_to_materialize():
                tracker.materialize(candidate, memory_graph)
                logger.info("Synapse materializada: %s", candidate.pattern_key)
            if hasattr(memory, "_persist_graph_state"):
                memory._persist_graph_state()
    except Exception as exc:
        logger.warning("execution synapse tracking falhou: %s", exc)

    # Agent memory isolation — roteia memórias para sub-grafos dos agentes
    try:
        from arnaldo.graph.agent_subgraphs import route_memory_to_agent

        memory_graph = memory.load_graph() if hasattr(memory, "load_graph") else None
        if memory_graph is not None:
            for result in list(runtime_result.step_results):
                synapse_id = str(result.get("synapse_id", "") or result.get("node_id", "")).strip()
                if not synapse_id:
                    continue
                node = memory_graph.get_node(synapse_id)
                if node is None or str(node.kind) != "synapse":
                    continue
                from arnaldo.graph.node_types import MemoryNode

                step_mem = MemoryNode.episodic(
                    label=f"exec::{synapse_id}::{run_id[:8]}",
                    run_id=run_id,
                    payload={
                        "step_result": {k: str(v)[:200] for k, v in result.items()},
                        "memory_type": "episodic",
                    },
                )
                route_memory_to_agent(memory_graph, synapse_id, step_mem)
    except Exception as exc:
        logger.warning("agent memory isolation falhou: %s", exc)

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

    # Memória: com gap, grava apenas registro episódico mínimo (sem procedural)
    if gap_report.status == "ok":
        _session.remember(
            memory,
            run_id,
            task.goal,
            files,
            session.id,
            adaptive_plan,
            step_results=list(runtime_result.step_results),
        )
    else:
        # Registro episódico mínimo — a run existiu mas falhou
        from arnaldo.memory import MemoryRecord as _MR

        memory.append(
            _MR(
                id=run_id,
                kind="episodic",
                payload={
                    "run_id": run_id,
                    "session_id": session.id,
                    "goal": task.goal,
                    "gap_detected": True,
                    "gap_warnings": gap_report.warnings,
                },
            )
        )
        # Memória negativa — anti-pattern registrado
        neg_record = create_negative_memory(
            run_id=run_id,
            request=task.goal,
            error_context=",".join(gap_report.warnings) or "gap_detected",
            session_id=session.id,
        )
        memory.append(neg_record)
        _session.evidence(
            store,
            run_id,
            task.id,
            "memory_degraded_due_to_gap",
            "Memória procedural não gravada: gap detectado.",
            {"gap_warnings": gap_report.warnings},
        )
    return session, gap_report


def create_negative_memory(
    run_id: str,
    request: str,
    error_context: str,
    session_id: str = "",
) -> MemoryRecord:
    """Cria memória negativa a partir de falha de execução."""
    req_str = str(request)
    truncated = req_str[:100]
    digest = hashlib.sha256(f"{run_id}:{truncated}".encode()).hexdigest()[:12]
    summary_text = req_str[:80]
    return MemoryRecord(
        id=f"neg_{digest}",
        kind="negative",
        payload={
            "pattern": req_str[:200],
            "error_context": str(error_context)[:300],
            "run_id": run_id,
            "session_id": session_id,
            "summary": f"falha: {summary_text}",
            "inhibits_synapses": [],
        },
    )
