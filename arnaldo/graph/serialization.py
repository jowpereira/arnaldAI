"""Serialização msgpack de nós, arestas, bitemp e proveniência."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .edges import EdgeKind, GraphEdge
from .nodes import (
    CapabilityNode,
    GraphNode,
    MemoryNode,
    NodeKind,
    NodeStats,
    NodeStatus,
    SynapseNode,
)
from .provenance import SourceKind, SourceRecord
from .refs import GraphRef, GraphRefKind
from .temporal import BiTemporal, ValidityWindow


# ── Nós ──────────────────────────────────────────────────────────────────


def serialize_node(n: GraphNode) -> dict[str, Any]:
    """Converte ``GraphNode`` em dict serializável por msgpack."""
    return {
        "id": n.id,
        "kind": n.kind.value,
        "label": n.label,
        "payload": n.payload,
        "embedding": n.embedding.tobytes() if n.embedding is not None else None,
        "embedding_shape": list(n.embedding.shape) if n.embedding is not None else None,
        "embedding_dtype": str(n.embedding.dtype) if n.embedding is not None else None,
        "weight": n.weight,
        "status": n.status.value,
        "bitemp": _serialize_bitemp(n.bitemp),
        "source": _serialize_source(n.source),
        "stats": {
            "activations": n.stats.activations,
            "successes": n.stats.successes,
            "failures": n.stats.failures,
            "last_activated_at": n.stats.last_activated_at.isoformat()
            if n.stats.last_activated_at
            else None,
            "last_refreshed_at": n.stats.last_refreshed_at.isoformat()
            if n.stats.last_refreshed_at
            else None,
        },
        "tags": sorted(n.tags),
        "domain": n.domain,
        "subgraph_refs": [_serialize_ref(r) for r in n.subgraph_refs],
    }


def deserialize_node(data: dict[str, Any]) -> GraphNode:
    """Reconstrói ``GraphNode`` a partir de dict msgpack."""
    kind = NodeKind(data["kind"])
    cls_map = {
        NodeKind.MEMORY: MemoryNode,
        NodeKind.SYNAPSE: SynapseNode,
        NodeKind.CAPABILITY: CapabilityNode,
    }
    cls = cls_map[kind]
    embedding = None
    if data.get("embedding"):
        arr = np.frombuffer(data["embedding"], dtype=data["embedding_dtype"])
        embedding = arr.reshape(data["embedding_shape"]).astype(np.float32)
    stats = NodeStats(
        activations=data["stats"]["activations"],
        successes=data["stats"]["successes"],
        failures=data["stats"]["failures"],
        last_activated_at=datetime.fromisoformat(data["stats"]["last_activated_at"])
        if data["stats"]["last_activated_at"]
        else None,
        last_refreshed_at=datetime.fromisoformat(data["stats"]["last_refreshed_at"])
        if data["stats"]["last_refreshed_at"]
        else None,
    )
    return cls(
        id=data["id"],
        kind=kind,
        label=data["label"],
        payload=dict(data["payload"]),
        embedding=embedding,
        weight=float(data["weight"]),
        status=NodeStatus(data["status"]),
        bitemp=_deserialize_bitemp(data["bitemp"]),
        source=_deserialize_source(data["source"]),
        stats=stats,
        tags=set(data["tags"]),
        domain=data["domain"],
        subgraph_refs=[_deserialize_ref(r) for r in data.get("subgraph_refs", [])],
    )


# ── Refs ─────────────────────────────────────────────────────────────────


def _serialize_ref(r: GraphRef) -> dict[str, Any]:
    return {
        "graph_id": r.graph_id,
        "kind": r.kind.value,
        "uri": r.uri,
        "bridge_nodes": list(r.bridge_nodes),
        "attached_at": r.attached_at.isoformat(),
        "ref_strength": r.ref_strength,
    }


def _deserialize_ref(data: dict[str, Any]) -> GraphRef:
    return GraphRef(
        graph_id=data["graph_id"],
        kind=GraphRefKind(data["kind"]),
        uri=data.get("uri"),
        bridge_nodes=tuple(data.get("bridge_nodes", [])),
        attached_at=datetime.fromisoformat(data["attached_at"]),
        ref_strength=float(data.get("ref_strength", 0.5)),
    )


# ── Arestas ──────────────────────────────────────────────────────────────


def serialize_edge(e: GraphEdge) -> dict[str, Any]:
    """Converte ``GraphEdge`` em dict serializável por msgpack."""
    return {
        "id": e.id,
        "source_id": e.source_id,
        "target_id": e.target_id,
        "kind": e.kind.value,
        "weight": e.weight,
        "bitemp": _serialize_bitemp(e.bitemp),
        "source": _serialize_source(e.source),
        "payload": e.payload,
        "activations": e.activations,
        "successes": e.successes,
        "failures": e.failures,
        "last_activated_at": e.last_activated_at.isoformat() if e.last_activated_at else None,
    }


def deserialize_edge(data: dict[str, Any]) -> GraphEdge:
    """Reconstrói ``GraphEdge`` a partir de dict msgpack."""
    return GraphEdge(
        id=data["id"],
        source_id=data["source_id"],
        target_id=data["target_id"],
        kind=EdgeKind(data["kind"]),
        weight=float(data["weight"]),
        bitemp=_deserialize_bitemp(data["bitemp"]),
        source=_deserialize_source(data["source"]),
        payload=dict(data["payload"]),
        activations=data.get("activations", 0),
        successes=data.get("successes", 0),
        failures=data.get("failures", 0),
        last_activated_at=datetime.fromisoformat(data["last_activated_at"])
        if data.get("last_activated_at")
        else None,
    )


# ── BiTemporal ───────────────────────────────────────────────────────────


def _serialize_bitemp(b: BiTemporal) -> dict[str, Any]:
    return {
        "valid_from": b.window.valid_from.isoformat(),
        "valid_to": b.window.valid_to.isoformat() if b.window.valid_to else None,
        "recorded_at": b.recorded_at.isoformat(),
        "invalidated_at": b.invalidated_at.isoformat() if b.invalidated_at else None,
    }


def _deserialize_bitemp(data: dict[str, Any]) -> BiTemporal:
    window = ValidityWindow(
        valid_from=datetime.fromisoformat(data["valid_from"]),
        valid_to=datetime.fromisoformat(data["valid_to"]) if data["valid_to"] else None,
    )
    return BiTemporal(
        window=window,
        recorded_at=datetime.fromisoformat(data["recorded_at"]),
        invalidated_at=datetime.fromisoformat(data["invalidated_at"])
        if data["invalidated_at"]
        else None,
    )


# ── SourceRecord ─────────────────────────────────────────────────────────


def _serialize_source(s: SourceRecord) -> dict[str, Any]:
    return {
        "kind": s.kind.value,
        "identifier": s.identifier,
        "captured_at": s.captured_at.isoformat(),
        "confidence": s.confidence,
        "author": s.author,
        "version": s.version,
        "metadata": s.metadata,
    }


def _deserialize_source(data: dict[str, Any]) -> SourceRecord:
    return SourceRecord(
        kind=SourceKind(data["kind"]),
        identifier=data["identifier"],
        captured_at=datetime.fromisoformat(data["captured_at"]),
        confidence=float(data["confidence"]),
        author=data.get("author"),
        version=data.get("version"),
        metadata=dict(data.get("metadata", {})),
    )


# ── Utilitários ──────────────────────────────────────────────────────────


def top_n_tags(tag_index: dict[str, set[str]], n: int) -> list[tuple[str, int]]:
    """Retorna as ``n`` tags mais frequentes."""
    ranked = sorted(tag_index.items(), key=lambda kv: len(kv[1]), reverse=True)
    return [(tag, len(ids)) for tag, ids in ranked[:n]]


# ── Persist / Load do CognitiveGraph ────────────────────────────────────


def persist_graph(graph: Any, path: Path) -> Path:
    """Serializa CognitiveGraph completo para msgpack."""
    import msgpack

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph._event_ledger_path = path.parent / "graph_events.jsonl"
    payload = {
        "version": "cognitive-graph/v2",
        "graph_id": graph._graph_id,
        "nodes": [serialize_node(n) for n in graph._nodes.values()],
        "edges": [serialize_edge(e) for e in graph._edges.values()],
    }
    with path.open("wb") as f:
        msgpack.pack(payload, f, use_bin_type=True)
    return path


def load_graph(
    path: Path,
    *,
    graph_cls: type | None = None,
    plasticity: Any | None = None,
    matcher: Any | None = None,
    registry: Any | None = None,
) -> Any:
    """Desserializa CognitiveGraph de msgpack."""
    import msgpack

    with Path(path).open("rb") as f:
        payload = msgpack.unpack(f, raw=False)
    version = payload.get("version")
    if version not in {"cognitive-graph/v1", "cognitive-graph/v2"}:
        raise ValueError(f"Versão de schema desconhecida: {version}")
    if graph_cls is None:
        from .store import CognitiveGraph

        graph_cls = CognitiveGraph
    cog = graph_cls(
        graph_id=payload.get("graph_id"),
        plasticity=plasticity,
        matcher=matcher,
        registry=registry,
    )
    for n_data in payload["nodes"]:
        cog.add_node(deserialize_node(n_data))
    for e_data in payload["edges"]:
        cog.add_edge(deserialize_edge(e_data))
    return cog
