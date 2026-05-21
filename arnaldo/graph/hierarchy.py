"""Operações de hierarquia de sub-grafos — attach, detach, resolve, federated match."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

import numpy as np

from .events import GraphEvent
from .matching import MatchResult
from .refs import GraphRef, GraphRefKind
from .registry import GraphRegistry, _new_graph_id
from .temporal import utc_now

if TYPE_CHECKING:
    from .store import CognitiveGraph


def attach_subgraph(
    graph: CognitiveGraph,
    node_id: str,
    subgraph: CognitiveGraph,
    *,
    kind: GraphRefKind = GraphRefKind.OWNED,
    bridge_nodes: list[str] | None = None,
    uri: Path | None = None,
    ref_strength: float = 0.5,
) -> GraphRef:
    """Anexa ``subgraph`` como sub-grafo do nó ``node_id``.

    Raises:
        KeyError: nó-pai inexistente.
        GraphCycleError: ciclo detectado.
        RuntimeError: sem ``GraphRegistry`` configurado.
    """
    graph._assert_mutable()
    node = graph._nodes.get(node_id)
    if node is None:
        raise KeyError(f"node {node_id} não existe em {graph.graph_id}")

    registry = graph._registry
    if registry is None:
        registry = GraphRegistry()
        registry.register(graph, graph_id=graph._graph_id)
        graph._registry = registry

    if registry.get(graph._graph_id) is None:
        registry.register(graph, graph_id=graph._graph_id)

    if kind == GraphRefKind.FEDERATED and uri is None:
        raise ValueError("GraphRefKind.FEDERATED exige uri.")

    effective_uri = Path(uri) if uri is not None else None
    target_subgraph = subgraph
    target_graph_id = subgraph._graph_id

    if kind == GraphRefKind.SNAPSHOT:
        if effective_uri is None:
            base_path = registry._base_path
            if base_path is None:
                raise ValueError("GraphRefKind.SNAPSHOT exige uri ou GraphRegistry(base_path=...).")
            snapshot_dir = Path(base_path) / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot_name = f"{subgraph.graph_id}_{utc_now().strftime('%Y%m%dT%H%M%S%f')}.msgpack"
            effective_uri = snapshot_dir / snapshot_name
        subgraph.persist(effective_uri)
        target_subgraph = type(graph).load(effective_uri, registry=registry)
        target_subgraph._set_read_only(True)
        target_graph_id = _new_graph_id()

    sub_gid = registry.register(target_subgraph, graph_id=target_graph_id, uri=effective_uri)

    if kind == GraphRefKind.OWNED:
        registry.mark_owned(
            parent_graph_id=graph._graph_id,
            parent_node_id=node_id,
            child_graph_id=sub_gid,
        )
    registry.incr_refcount(sub_gid)

    ref = GraphRef(
        graph_id=sub_gid,
        kind=kind,
        uri=str(effective_uri) if effective_uri else None,
        bridge_nodes=tuple(bridge_nodes or []),
        ref_strength=ref_strength,
    )
    node.attach_ref(ref)

    graph._record(
        GraphEvent(
            "subgraph_attached",
            node_id,
            utc_now(),
            {"sub_graph_id": sub_gid, "kind": kind.value},
        )
    )
    return ref


def detach_subgraph(graph: CognitiveGraph, node_id: str, sub_graph_id: str) -> bool:
    """Remove referência de ``sub_graph_id`` no nó ``node_id``."""
    graph._assert_mutable()
    node = graph._nodes.get(node_id)
    if node is None:
        return False
    ref = node.detach_ref(sub_graph_id)
    if ref is None:
        return False
    if graph._registry is not None:
        remaining = graph._registry.decr_refcount(sub_graph_id)
        if ref.kind == GraphRefKind.OWNED and remaining == 0:
            graph._registry.unregister(sub_graph_id)
    graph._record(
        GraphEvent(
            "subgraph_detached",
            node_id,
            utc_now(),
            {"sub_graph_id": sub_graph_id, "kind": ref.kind.value},
        )
    )
    return True


def resolve_subgraph(graph: CognitiveGraph, ref: GraphRef) -> CognitiveGraph | None:
    """Resolve ``GraphRef`` para ``CognitiveGraph`` (lazy via registry)."""
    if graph._registry is None:
        return None
    return graph._registry.resolve(ref)


def iter_subgraphs(
    graph: CognitiveGraph,
    node_id: str,
) -> Iterator[tuple[GraphRef, CognitiveGraph | None]]:
    """Itera (ref, sub_grafo_resolvido) para todos os sub-grafos do nó."""
    node = graph._nodes.get(node_id)
    if node is None:
        return
    for ref in node.subgraph_refs:
        yield ref, resolve_subgraph(graph, ref)


def record_outcome_recursive(
    graph: CognitiveGraph,
    node_id: str,
    *,
    success: bool,
    scoped_activations: dict[str, set[str]] | None = None,
    depth: int = 0,
    max_depth: int = 3,
) -> None:
    """Propaga plasticidade Hebbian através da hierarquia de sub-grafos."""
    graph._assert_mutable()
    graph.record_outcome(node_id, success=success)

    if depth >= max_depth:
        return

    node = graph._nodes.get(node_id)
    if node is None or not node.has_subgraphs:
        return

    for ref in node.subgraph_refs:
        subgraph = resolve_subgraph(graph, ref)
        if subgraph is None:
            continue
        if not ref.kind.allows_mutation:
            continue
        if not scoped_activations:
            continue

        activated_in_sub = scoped_activations.get(ref.graph_id, set())
        for sub_node_id in activated_in_sub:
            record_outcome_recursive(
                subgraph,
                sub_node_id,
                success=success,
                scoped_activations=scoped_activations,
                depth=depth + 1,
                max_depth=max_depth,
            )

        ref_updated = ref.with_strength(
            graph.plasticity.rule.update(
                ref.ref_strength,
                1.0 if success else 0.0,
            )
        )
        for i, existing in enumerate(node.subgraph_refs):
            if existing.graph_id == ref.graph_id:
                node.subgraph_refs[i] = ref_updated
                break


def federated_match(
    graph: CognitiveGraph,
    node_id: str,
    *,
    query: str | None = None,
    query_embedding: np.ndarray | None = None,
    intent: str | None = None,
) -> dict[str, list[MatchResult]]:
    """Executa ``match`` em sub-grafos do nó, agregando por graph_id."""
    results: dict[str, list[MatchResult]] = {}
    node = graph._nodes.get(node_id)
    if node is None:
        return results
    for ref in node.subgraph_refs:
        subgraph = resolve_subgraph(graph, ref)
        if subgraph is None:
            continue
        sub_results = subgraph.match(
            query=query,
            query_embedding=query_embedding,
            intent=intent,
        )
        if ref.bridge_nodes:
            allowed = set(ref.bridge_nodes)
            sub_results = [r for r in sub_results if r.node.id in allowed]
        results[ref.graph_id] = sub_results
    return results
