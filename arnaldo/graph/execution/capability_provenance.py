"""Proveniência cross-layer — edges entre capabilities e memórias produzidas."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TYPE_CHECKING

from ..edges import EdgeKind
from ..edge_ops import ensure_edge
from ..node_types import MemoryNode
from ..provenance import SourceRecord

if TYPE_CHECKING:
    from ..store import CognitiveGraph


def link_capability_to_memory(
    graph: CognitiveGraph,
    *,
    capability_id: str,
    node_id: str,
    data: Any,
    request: str,
) -> None:
    """Ingere dado de capability como MemoryNode factual + edge DERIVED_FROM.

    Proveniência epistêmica: capability → DERIVED_FROM → memória factual.
    O dado externo fica no grafo com rastreabilidade de origem.
    """
    if isinstance(data, (dict, list)):
        content = json.dumps(data, ensure_ascii=False, default=str)[:500]
    else:
        content = str(data)[:500] if data else ""
    if not content.strip():
        return

    # ID determinístico: mesmo (capability, request) → mesmo ID para deduplicação
    digest = hashlib.sha256(f"{capability_id}:{request}".encode()).hexdigest()[:12]
    mem_id = f"mem-cap-{digest}"

    # Evitar duplicata — se já existe, não recria
    if graph.has_node(mem_id):
        return

    source = SourceRecord.from_run(f"capability:{capability_id}")
    mem_node = MemoryNode.semantic(
        label=f"factual::{request[:120]}",
        id=mem_id,
        payload={
            "memory_type": "semantic",
            "content": content,
            "capability_id": capability_id,
            "query": request[:200],
        },
        source=source,
        domain="factual",
    )
    graph.add_node(mem_node)

    # DERIVED_FROM: capability_node → memória produzida (com guard de existência)
    ensure_edge(
        graph,
        source_id=node_id,
        target_id=mem_id,
        kind=EdgeKind.DERIVED_FROM,
        weight=0.85,
    )
