"""Tracing, evidência, retenção, bootstrap e sandbox para o GraphRuntime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from arnaldo.contracts import (
    EvidenceRecord,
    RuntimeEvent,
    new_id,
    to_dict,
    utc_now,
)
from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
    MemoryNode,
    NodeKind,
    NodeStatus,
    StepContext,
)
from arnaldo.storage import RunStore

from .infra import _env_positive_int, _slug


def _trace(store: RunStore, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    event = RuntimeEvent(
        id=new_id("event"),
        run_id=run_id,
        created_at=utc_now(),
        event_type=event_type,
        payload=payload,
    )
    store.append_jsonl("trace.jsonl", to_dict(event))


def _record_prompt_payload(
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
    _trace(
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


def _resolve_sandbox_dir(raw_path: Any) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_step_artifact(
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


def _apply_graph_retention(
    *,
    graph: CognitiveGraph,
    run_id: str,
    keep_synapse_ids: set[str],
) -> Dict[str, Any]:
    decay_counters = graph.sweep_decay()
    max_memory_nodes = _env_positive_int("ARNALDO_GRAPH_MAX_MEMORY_NODES", default=256)
    max_archived_nodes = _env_positive_int("ARNALDO_GRAPH_MAX_ARCHIVED_NODES", default=128)

    removed_memory = 0
    run_memory_prefix = "mem_%s_" % _slug(run_id)
    memory_nodes = [node for node in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False)]
    memory_nodes.sort(key=lambda node: node.bitemp.recorded_at)
    memory_overflow = max(0, len(memory_nodes) - max_memory_nodes)
    if memory_overflow > 0:
        removable_memory = [
            node for node in memory_nodes if not node.id.startswith(run_memory_prefix)
        ]
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
        node for node in graph.iter_nodes(active_only=False) if node.status == NodeStatus.ARCHIVED
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

    # Busca em TODOS os synapses do grafo (não só path) para capturar
    # contexto de runs anteriores que usaram agents diferentes.
    all_synapse_ids = set(path)
    for node in graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=False):
        all_synapse_ids.add(node.id)

    latest_by_synapse: Dict[str, tuple[Any, Dict[str, Any], Dict[str, str]]] = {}
    for synapse_id in all_synapse_ids:
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

    context_limit = _env_positive_int("ARNALDO_GRAPH_BOOTSTRAP_CONTEXT_LIMIT", default=6)
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
