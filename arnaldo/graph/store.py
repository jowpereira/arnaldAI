"""``CognitiveGraph`` — store principal do substrate cognitivo."""

from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator  # Iterable used in match()

import msgpack
import networkx as nx
import numpy as np
from .edges import EdgeKind, GraphEdge
from .events import GraphEvent
from .matching import HybridMatcher, MatchResult
from .nodes import CapabilityNode, GraphNode, MemoryNode, NodeKind, NodeStatus, SynapseNode
from .plasticity import PlasticityEngine
from .refs import GraphRef, GraphRefKind
from .registry import GraphCycleError, GraphRegistry, _new_graph_id
from .serialization import (
    serialize_node,
    deserialize_node,
    serialize_edge,
    deserialize_edge,
    top_n_tags,
)
from .temporal import utc_now
from datetime import datetime
from . import hierarchy as _hierarchy, query as _query


class CognitiveGraph:
    """Substrate cognitivo unificado — nós e arestas tipados, com plasticidade."""

    def __init__(
        self,
        *,
        graph_id: str | None = None,
        plasticity: PlasticityEngine | None = None,
        matcher: HybridMatcher | None = None,
        registry: GraphRegistry | None = None,
    ) -> None:
        self._graph_id: str = graph_id or _new_graph_id()
        self._g: nx.MultiDiGraph = nx.MultiDiGraph()
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._by_kind: dict[NodeKind, set[str]] = defaultdict(set)
        self._by_domain: dict[str, set[str]] = defaultdict(set)
        self._by_tag: dict[str, set[str]] = defaultdict(set)
        self.plasticity: PlasticityEngine = plasticity or PlasticityEngine()
        self.matcher: HybridMatcher = matcher or HybridMatcher()
        self._registry: GraphRegistry | None = registry
        self._read_only: bool = False
        self._events: list[GraphEvent] = []

    @property
    def graph_id(self) -> str:
        return self._graph_id

    def _bind_graph_id(self, gid: str) -> None:
        self._graph_id = gid

    def _bind_registry(self, registry: GraphRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> GraphRegistry | None:
        return self._registry

    @property
    def is_read_only(self) -> bool:
        return self._read_only

    def _set_read_only(self, value: bool = True) -> None:
        self._read_only = bool(value)

    def _assert_mutable(self) -> None:
        if self._read_only:
            raise RuntimeError(f"CognitiveGraph '{self._graph_id}' está em modo read-only.")

    # ── Mutação ──────────────────────────────────────────────────────────

    def add_node(self, node: GraphNode) -> GraphNode:
        """Adiciona ou substitui um nó, atualizando índices e nx."""
        self._assert_mutable()
        if not node.id:
            raise ValueError("Node sem id não pode ser adicionado")
        if node.id in self._nodes:
            self._remove_from_indices(self._nodes[node.id])
        self._nodes[node.id] = node
        self._g.add_node(node.id, kind=node.kind.value)
        self._add_to_indices(node)
        self._record(GraphEvent("node_added", node.id, utc_now(), {"kind": node.kind.value}))
        return node

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        """Adiciona aresta tipada. Source/target devem existir."""
        self._assert_mutable()
        if edge.source_id not in self._nodes:
            raise KeyError(f"source_id {edge.source_id} inexistente")
        if edge.target_id not in self._nodes:
            raise KeyError(f"target_id {edge.target_id} inexistente")
        if edge.id in self._edges:
            self._g.remove_edge(
                self._edges[edge.id].source_id,
                self._edges[edge.id].target_id,
                key=edge.id,
            )
        self._edges[edge.id] = edge
        self._g.add_edge(edge.source_id, edge.target_id, key=edge.id, kind=edge.kind.value)
        if not edge.kind.is_directed and edge.source_id != edge.target_id:
            self._g.add_edge(edge.target_id, edge.source_id, key=edge.id, kind=edge.kind.value)
        self._record(GraphEvent("edge_added", edge.id, utc_now(), {"kind": edge.kind.value}))
        return edge

    def remove_node(self, node_id: str) -> None:
        """Remove nó e todas as arestas incidentes."""
        self._assert_mutable()
        if node_id not in self._nodes:
            return
        incident = [
            eid
            for eid, e in self._edges.items()
            if e.source_id == node_id or e.target_id == node_id
        ]
        for eid in incident:
            del self._edges[eid]
        node = self._nodes.pop(node_id)
        self._remove_from_indices(node)
        self._g.remove_node(node_id)
        self._record(GraphEvent("node_removed", node_id, utc_now()))

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def get_edge(self, edge_id: str) -> GraphEdge | None:
        return self._edges.get(edge_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def iter_nodes(self, **kw: Any) -> Iterator[GraphNode]:
        return _query.iter_nodes(self, **kw)

    def iter_edges_from(self, node_id: str, **kw: Any) -> Iterator[GraphEdge]:
        return _query.iter_edges_from(self, node_id, **kw)

    def iter_edges_to(self, node_id: str, **kw: Any) -> Iterator[GraphEdge]:
        return _query.iter_edges_to(self, node_id, **kw)

    def iter_edges(self, **kw: Any) -> Iterator[GraphEdge]:
        return _query.iter_edges(self, **kw)

    def neighbors(self, node_id: str, **kw: Any) -> Iterator[GraphNode]:
        return _query.neighbors(self, node_id, **kw)

    # ── Operações sinápticas ────────────────────────────────────────────

    def activate(self, node_id: str, *, at: datetime | None = None) -> None:
        self._assert_mutable()
        node = self._nodes.get(node_id)
        if node is None:
            return
        node.activate(at)
        self._record(GraphEvent("activation", node_id, at or utc_now()))

    def record_outcome(self, node_id: str, *, success: bool) -> None:
        self._assert_mutable()
        node = self._nodes.get(node_id)
        if node is None:
            return
        updated = self.plasticity.update_node(node, success=success)
        self._nodes[node_id] = updated
        self._record(GraphEvent("hebbian", node_id, utc_now(), {"success": success}))

    def record_edge_outcome(self, edge_id: str, *, success: bool) -> None:
        self._assert_mutable()
        edge = self._edges.get(edge_id)
        if edge is None:
            return
        updated = self.plasticity.update_edge(edge, success=success)
        self._edges[edge_id] = updated

    def attach_subgraph(self, node_id: str, subgraph: CognitiveGraph, **kw: Any) -> GraphRef:
        return _hierarchy.attach_subgraph(self, node_id, subgraph, **kw)

    def detach_subgraph(self, node_id: str, sub_graph_id: str) -> bool:
        return _hierarchy.detach_subgraph(self, node_id, sub_graph_id)

    def resolve_subgraph(self, ref: GraphRef) -> CognitiveGraph | None:
        return _hierarchy.resolve_subgraph(self, ref)

    def iter_subgraphs(self, node_id: str) -> Iterator[tuple[GraphRef, CognitiveGraph | None]]:
        return _hierarchy.iter_subgraphs(self, node_id)

    def record_outcome_recursive(self, node_id: str, **kw: Any) -> None:
        _hierarchy.record_outcome_recursive(self, node_id, **kw)

    def federated_match(self, node_id: str, **kw: Any) -> dict[str, list[MatchResult]]:
        return _hierarchy.federated_match(self, node_id, **kw)

    def sweep_decay(self, *, at: datetime | None = None) -> dict[str, int]:
        self._assert_mutable()
        now = at or utc_now()
        counters = {"to_stale": 0, "to_archived": 0, "to_consolidated": 0}
        for node_id, node in list(self._nodes.items()):
            suggested = self.plasticity.classify_status(node, at=now)
            new_status = {
                "candidate": NodeStatus.CANDIDATE,
                "active": NodeStatus.ACTIVE,
                "consolidated": NodeStatus.CONSOLIDATED,
                "stale": NodeStatus.STALE,
                "archived": NodeStatus.ARCHIVED,
            }[suggested]
            if new_status != node.status:
                self._nodes[node_id] = node.with_status(new_status)
                if new_status == NodeStatus.STALE:
                    counters["to_stale"] += 1
                elif new_status == NodeStatus.ARCHIVED:
                    counters["to_archived"] += 1
                elif new_status == NodeStatus.CONSOLIDATED:
                    counters["to_consolidated"] += 1
        self._record(GraphEvent("decay_swept", "<all>", now, dict(counters)))
        return counters

    def match(
        self,
        *,
        query: str | None = None,
        query_embedding: np.ndarray | None = None,
        intent: str | None = None,
        node_kinds: Iterable[NodeKind] | None = None,
    ) -> list[MatchResult]:
        kind_values = [k.value for k in node_kinds] if node_kinds else None
        return self.matcher.retrieve(
            self,
            query=query,
            query_embedding=query_embedding,
            intent=intent,
            node_kinds=kind_values,
        )

    def persist(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "cognitive-graph/v2",
            "graph_id": self._graph_id,
            "nodes": [serialize_node(n) for n in self._nodes.values()],
            "edges": [serialize_edge(e) for e in self._edges.values()],
        }
        with path.open("wb") as f:
            msgpack.pack(payload, f, use_bin_type=True)
        return path

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        plasticity: PlasticityEngine | None = None,
        matcher: HybridMatcher | None = None,
        registry: GraphRegistry | None = None,
    ) -> CognitiveGraph:
        with Path(path).open("rb") as f:
            payload = msgpack.unpack(f, raw=False)
        version = payload.get("version")
        if version not in {"cognitive-graph/v1", "cognitive-graph/v2"}:
            raise ValueError(f"Versão de schema desconhecida: {version}")
        cog = cls(
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

    def stats(self) -> dict[str, Any]:
        kind_counts = {k.value: len(v) for k, v in self._by_kind.items()}
        edge_kind_counts: dict[str, int] = defaultdict(int)
        for e in self._edges.values():
            edge_kind_counts[e.kind.value] += 1
        return {
            "nodes_total": self.node_count,
            "edges_total": self.edge_count,
            "nodes_by_kind": kind_counts,
            "edges_by_kind": dict(edge_kind_counts),
            "domains": sorted(self._by_domain.keys()),
            "tags_top_10": top_n_tags(self._by_tag, 10),
        }

    def _add_to_indices(self, node: GraphNode) -> None:
        self._by_kind[node.kind].add(node.id)
        self._by_domain[node.domain].add(node.id)
        for tag in node.tags:
            self._by_tag[tag].add(node.id)

    def _remove_from_indices(self, node: GraphNode) -> None:
        self._by_kind[node.kind].discard(node.id)
        self._by_domain[node.domain].discard(node.id)
        for tag in node.tags:
            self._by_tag[tag].discard(node.id)

    def _record(self, event: GraphEvent) -> None:
        self._events.append(event)
        if len(self._events) > 1000:
            self._events = self._events[-500:]
