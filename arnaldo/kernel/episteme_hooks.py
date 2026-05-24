"""Hooks epistêmicos do kernel — criação de memórias prospectivas."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from arnaldo.episteme.signals import GapType
from arnaldo.graph.brain import BrainDecision
from arnaldo.graph.store import CognitiveGraph
from arnaldo.graph.nodes import NodeKind
from arnaldo.memory.models import MemoryRecord

logger = logging.getLogger("arnaldo.kernel.episteme_hooks")


def create_prospective_memory(decision: BrainDecision, request: str) -> MemoryRecord | None:
    """GAP 1: Cria memória prospectiva quando brain detecta gap."""
    if not decision.knowledge_gap:
        return None

    digest = hashlib.sha256(request.encode()).hexdigest()[:12]
    record = MemoryRecord(
        id=f"prospect_{digest}",
        kind="prospective",
        payload={
            "query": request[:500],
            "gap_type": decision.gap_type.value,
            "confidence": decision.confidence,
            "status": "pending",
            "summary": f"gap detectado: {request[:120]}",
        },
    )
    logger.info(
        "Memória prospectiva criada: gap_type=%s query='%s'",
        decision.gap_type.value,
        request[:60],
    )
    return record


def collect_pending_prospective(
    graph: CognitiveGraph,
) -> list[dict[str, Any]]:
    """GAP 4: Coleta memórias prospectivas pendentes do grafo."""
    pending: list[dict[str, Any]] = []
    for node in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=True):
        payload = node.payload if isinstance(node.payload, dict) else {}
        if payload.get("memory_type") == "prospective" and payload.get("status") == "pending":
            pending.append(
                {
                    "node_id": node.id,
                    "query": payload.get("query", ""),
                    "gap_type": payload.get("gap_type", "unknown"),
                }
            )
    return pending


def resolve_prospective_memories(
    graph: CognitiveGraph,
    query: str,
    gap_type: GapType,
) -> int:
    """Marca prospective memories pendentes como resolved. Retorna count."""
    resolved = 0
    for node in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=True):
        payload = node.payload if isinstance(node.payload, dict) else {}
        if payload.get("memory_type") != "prospective":
            continue
        if payload.get("status") != "pending":
            continue
        node_gap = payload.get("gap_type", "")
        if node_gap == gap_type.value or query[:60] in str(payload.get("query", "")):
            node.payload["status"] = "resolved"
            graph.add_node(node)
            resolved += 1
    if resolved:
        logger.info("Resolved %d prospective memories for gap_type=%s", resolved, gap_type.value)
    return resolved
