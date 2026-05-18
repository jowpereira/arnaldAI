"""Testes de grafos referenciando grafos (hierarquia composicional).

Cobre:

* ``GraphRef`` — tipagem, validação, plasticidade da referência.
* ``GraphRefKind`` — apenas OWNED/SHARED implementados na Fase 2.
* ``GraphRegistry`` — registro, resolução lazy, refcount, ownership,
  detecção de ciclo, garbage collection.
* ``CognitiveGraph.attach_subgraph`` — composição estrutural.
* ``CognitiveGraph.record_outcome_recursive`` — plasticidade transitiva.
* ``CognitiveGraph.federated_match`` — query através de bridges.
* Persistência preserva refs.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from arnaldo.graph import (
    CapabilityNode,
    CognitiveGraph,
    EdgeKind,
    GraphCycleError,
    GraphEdge,
    GraphRef,
    GraphRefKind,
    GraphRegistry,
    MemoryNode,
    SourceKind,
    SourceRecord,
    SynapseNode,
)


# ────────────────────────────────────────────────────────────────────────────
# GraphRefKind / GraphRef
# ────────────────────────────────────────────────────────────────────────────


class TestGraphRefKind:
    def test_owned_and_shared_implemented(self) -> None:
        assert GraphRefKind.OWNED.is_implemented
        assert GraphRefKind.SHARED.is_implemented

    def test_federated_and_snapshot_not_yet(self) -> None:
        assert not GraphRefKind.FEDERATED.is_implemented
        assert not GraphRefKind.SNAPSHOT.is_implemented

    def test_snapshot_is_immutable(self) -> None:
        assert not GraphRefKind.SNAPSHOT.allows_mutation
        assert GraphRefKind.OWNED.allows_mutation
        assert GraphRefKind.SHARED.allows_mutation


class TestGraphRef:
    def test_basic_construction(self) -> None:
        ref = GraphRef(
            graph_id="cog_abc",
            kind=GraphRefKind.OWNED,
            bridge_nodes=("n1", "n2"),
        )
        assert ref.graph_id == "cog_abc"
        assert ref.kind == GraphRefKind.OWNED
        assert "n1" in ref.bridge_nodes

    def test_invalid_strength_raises(self) -> None:
        with pytest.raises(ValueError):
            GraphRef(
                graph_id="cog_x",
                kind=GraphRefKind.OWNED,
                ref_strength=1.5,
            )

    def test_federated_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            GraphRef(graph_id="x", kind=GraphRefKind.FEDERATED)

    def test_snapshot_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            GraphRef(graph_id="x", kind=GraphRefKind.SNAPSHOT)

    def test_with_strength_is_immutable_update(self) -> None:
        ref = GraphRef(graph_id="x", kind=GraphRefKind.OWNED, ref_strength=0.5)
        ref2 = ref.with_strength(0.9)
        assert ref.ref_strength == 0.5
        assert ref2.ref_strength == 0.9


# ────────────────────────────────────────────────────────────────────────────
# GraphRegistry
# ────────────────────────────────────────────────────────────────────────────


class TestGraphRegistry:
    def test_register_assigns_id(self) -> None:
        reg = GraphRegistry()
        cog = CognitiveGraph()
        original_id = cog.graph_id
        gid = reg.register(cog)
        assert gid == original_id  # mantém id pré-existente

    def test_register_with_explicit_id(self) -> None:
        reg = GraphRegistry()
        cog = CognitiveGraph()
        reg.register(cog, graph_id="custom_id")
        assert cog.graph_id == "custom_id"
        assert reg.get("custom_id") is cog

    def test_resolve_in_memory(self) -> None:
        reg = GraphRegistry()
        cog = CognitiveGraph()
        gid = reg.register(cog)
        ref = GraphRef(graph_id=gid, kind=GraphRefKind.OWNED)
        resolved = reg.resolve(ref)
        assert resolved is cog

    def test_resolve_lazy_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub.msgpack"
            sub = CognitiveGraph()
            sub.add_node(MemoryNode.episodic("test", run_id="r1"))
            sub.persist(path)

            reg = GraphRegistry()
            ref = GraphRef(
                graph_id=sub.graph_id,
                kind=GraphRefKind.SHARED,
                uri=str(path),
            )
            resolved = reg.resolve(ref)
            assert resolved is not None
            assert resolved.node_count == 1

    def test_resolve_missing_returns_none(self) -> None:
        reg = GraphRegistry()
        ref = GraphRef(graph_id="nonexistent", kind=GraphRefKind.OWNED)
        assert reg.resolve(ref) is None

    def test_mark_owned_records_relationship(self) -> None:
        reg = GraphRegistry()
        parent = CognitiveGraph(graph_id="P")
        child = CognitiveGraph(graph_id="C")
        reg.register(parent)
        reg.register(child)
        reg.mark_owned(
            parent_graph_id="P", parent_node_id="n1", child_graph_id="C"
        )
        # Tentar marcar segundo dono deve falhar (OWNED é exclusivo)
        with pytest.raises(ValueError, match="já possui dono"):
            reg.mark_owned(
                parent_graph_id="P", parent_node_id="n2", child_graph_id="C"
            )

    def test_refcount_lifecycle(self) -> None:
        reg = GraphRegistry()
        cog = CognitiveGraph()
        reg.register(cog)
        assert reg.incr_refcount(cog.graph_id) == 1
        assert reg.incr_refcount(cog.graph_id) == 2
        assert reg.decr_refcount(cog.graph_id) == 1
        assert reg.decr_refcount(cog.graph_id) == 0
        # Decrementar abaixo de zero é seguro (floor=0)
        assert reg.decr_refcount(cog.graph_id) == 0

    def test_cycle_detection_self_loop(self) -> None:
        reg = GraphRegistry()
        cog = CognitiveGraph(graph_id="X")
        reg.register(cog)
        # Tentar anexar X em X mesmo
        assert reg._would_create_cycle("X", "X") is True

    def test_cycle_detection_indirect(self) -> None:
        """A → B → C → tentar anexar A sob C deve falhar."""
        reg = GraphRegistry()
        a = CognitiveGraph(graph_id="A")
        b = CognitiveGraph(graph_id="B")
        c = CognitiveGraph(graph_id="C")
        reg.register(a)
        reg.register(b)
        reg.register(c)

        # A → B
        a_node = SynapseNode.specialist("a_n", role="r", objective="o")
        a.add_node(a_node)
        a.attach_subgraph(a_node.id, b, kind=GraphRefKind.OWNED)

        # B → C
        b_node = SynapseNode.specialist("b_n", role="r", objective="o")
        b.add_node(b_node)
        b.attach_subgraph(b_node.id, c, kind=GraphRefKind.OWNED)

        # Tentar C → A deve falhar
        c_node = SynapseNode.specialist("c_n", role="r", objective="o")
        c.add_node(c_node)
        with pytest.raises(GraphCycleError):
            c.attach_subgraph(c_node.id, a, kind=GraphRefKind.OWNED)


# ────────────────────────────────────────────────────────────────────────────
# CognitiveGraph.attach_subgraph
# ────────────────────────────────────────────────────────────────────────────


class TestAttachSubgraph:
    def test_owned_attaches_correctly(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)

        sub = CognitiveGraph()
        sub.add_node(MemoryNode.episodic("inner", run_id="r1"))

        ref = root.attach_subgraph(syn.id, sub, kind=GraphRefKind.OWNED)
        assert ref.kind == GraphRefKind.OWNED
        assert root.get_node(syn.id).has_subgraphs

    def test_shared_allows_multiple_refs(self) -> None:
        root = CognitiveGraph()
        a = SynapseNode.specialist("A", role="r", objective="o")
        b = SynapseNode.specialist("B", role="r", objective="o")
        root.add_node(a)
        root.add_node(b)

        kb = CognitiveGraph()
        kb.add_node(MemoryNode.episodic("shared knowledge", run_id="rN"))

        ref_a = root.attach_subgraph(a.id, kb, kind=GraphRefKind.SHARED)
        ref_b = root.attach_subgraph(b.id, kb, kind=GraphRefKind.SHARED)

        assert ref_a.graph_id == ref_b.graph_id

    def test_attach_to_nonexistent_raises(self) -> None:
        root = CognitiveGraph()
        sub = CognitiveGraph()
        with pytest.raises(KeyError):
            root.attach_subgraph("fake_id", sub, kind=GraphRefKind.OWNED)

    def test_bridge_nodes_recorded(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)

        sub = CognitiveGraph()
        m = MemoryNode.episodic("public_interface", run_id="r1")
        sub.add_node(m)

        ref = root.attach_subgraph(
            syn.id, sub, kind=GraphRefKind.OWNED, bridge_nodes=[m.id]
        )
        assert m.id in ref.bridge_nodes

    def test_resolve_subgraph_returns_attached(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)
        sub = CognitiveGraph()
        sub.add_node(MemoryNode.episodic("x", run_id="r1"))
        ref = root.attach_subgraph(syn.id, sub, kind=GraphRefKind.OWNED)
        resolved = root.resolve_subgraph(ref)
        assert resolved is sub

    def test_iter_subgraphs(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)

        sub1 = CognitiveGraph()
        sub2 = CognitiveGraph()
        root.attach_subgraph(syn.id, sub1, kind=GraphRefKind.OWNED)
        root.attach_subgraph(syn.id, sub2, kind=GraphRefKind.SHARED)

        refs = list(root.iter_subgraphs(syn.id))
        assert len(refs) == 2
        kinds = {r.kind for r, _ in refs}
        assert kinds == {GraphRefKind.OWNED, GraphRefKind.SHARED}


# ────────────────────────────────────────────────────────────────────────────
# CognitiveGraph.detach_subgraph
# ────────────────────────────────────────────────────────────────────────────


class TestDetachSubgraph:
    def test_detach_removes_ref(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)
        sub = CognitiveGraph()
        ref = root.attach_subgraph(syn.id, sub, kind=GraphRefKind.OWNED)

        removed = root.detach_subgraph(syn.id, ref.graph_id)
        assert removed is True
        assert not root.get_node(syn.id).has_subgraphs

    def test_detach_owned_unregisters_subgraph(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)
        sub = CognitiveGraph()
        ref = root.attach_subgraph(syn.id, sub, kind=GraphRefKind.OWNED)
        sub_id = ref.graph_id

        root.detach_subgraph(syn.id, sub_id)
        # Sub-grafo OWNED foi desregistrado
        assert root.registry.get(sub_id) is None

    def test_detach_shared_keeps_subgraph_alive(self) -> None:
        root = CognitiveGraph()
        a = SynapseNode.specialist("A", role="r", objective="o")
        b = SynapseNode.specialist("B", role="r", objective="o")
        root.add_node(a)
        root.add_node(b)

        kb = CognitiveGraph()
        root.attach_subgraph(a.id, kb, kind=GraphRefKind.SHARED)
        ref_b = root.attach_subgraph(b.id, kb, kind=GraphRefKind.SHARED)

        # Remove apenas a referência de B
        root.detach_subgraph(b.id, ref_b.graph_id)
        # kb continua existindo (A ainda referencia)
        assert root.registry.get(kb.graph_id) is kb

    def test_detach_nonexistent_returns_false(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)
        assert root.detach_subgraph(syn.id, "fake") is False


# ────────────────────────────────────────────────────────────────────────────
# Plasticidade transitiva
# ────────────────────────────────────────────────────────────────────────────


class TestRecursivePlasticity:
    def test_records_outcome_locally(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)
        original_weight = syn.weight

        root.record_outcome_recursive(syn.id, success=True)
        updated = root.get_node(syn.id)
        assert updated.weight > original_weight

    def test_propagates_to_subgraph_with_scoped_activations(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)

        sub = CognitiveGraph()
        inner = SynapseNode.specialist("INNER", role="r", objective="o")
        sub.add_node(inner)

        ref = root.attach_subgraph(syn.id, sub, kind=GraphRefKind.OWNED)
        original_inner_weight = inner.weight

        # Sem trace, não propaga
        root.record_outcome_recursive(syn.id, success=True)
        assert sub.get_node(inner.id).weight == original_inner_weight

        # Com trace, propaga
        root.record_outcome_recursive(
            syn.id,
            success=True,
            scoped_activations={ref.graph_id: {inner.id}},
        )
        assert sub.get_node(inner.id).weight > original_inner_weight

    def test_max_depth_limits_recursion(self) -> None:
        # Cria hierarquia 4 níveis profunda — depth_max=2 não desce até último
        root = CognitiveGraph()
        roots_node = SynapseNode.specialist("L0", role="r", objective="o")
        root.add_node(roots_node)

        levels = [CognitiveGraph() for _ in range(3)]
        nodes = [
            SynapseNode.specialist(f"L{i+1}", role="r", objective="o")
            for i in range(3)
        ]
        for lvl, nd in zip(levels, nodes):
            lvl.add_node(nd)

        refs = []
        refs.append(
            root.attach_subgraph(roots_node.id, levels[0], kind=GraphRefKind.OWNED)
        )
        refs.append(
            levels[0].attach_subgraph(nodes[0].id, levels[1], kind=GraphRefKind.OWNED)
        )
        refs.append(
            levels[1].attach_subgraph(nodes[1].id, levels[2], kind=GraphRefKind.OWNED)
        )

        scoped = {
            refs[0].graph_id: {nodes[0].id},
            refs[1].graph_id: {nodes[1].id},
            refs[2].graph_id: {nodes[2].id},
        }

        # depth=0 → propaga até depth 1 (com max_depth=2)
        root.record_outcome_recursive(
            roots_node.id,
            success=True,
            scoped_activations=scoped,
            max_depth=2,
        )
        # L1, L2 receberam update; L3 não
        assert levels[0].get_node(nodes[0].id).weight > 0.5
        assert levels[1].get_node(nodes[1].id).weight > 0.5
        # L3 (depth 3) deve estar fora do max_depth=2
        assert levels[2].get_node(nodes[2].id).weight == 0.5

    def test_ref_strength_updates_on_success(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)
        sub = CognitiveGraph()
        inner = MemoryNode.episodic("x", run_id="r1")
        sub.add_node(inner)

        ref = root.attach_subgraph(syn.id, sub, kind=GraphRefKind.OWNED)
        original_strength = ref.ref_strength

        root.record_outcome_recursive(
            syn.id,
            success=True,
            scoped_activations={ref.graph_id: {inner.id}},
        )
        updated_ref = root.get_node(syn.id).find_ref(ref.graph_id)
        assert updated_ref is not None
        assert updated_ref.ref_strength > original_strength


# ────────────────────────────────────────────────────────────────────────────
# Federated match
# ────────────────────────────────────────────────────────────────────────────


class TestFederatedMatch:
    def test_returns_per_subgraph_results(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)

        sub = CognitiveGraph()
        sub.add_node(MemoryNode.episodic("memory in sub", run_id="r1"))
        ref = root.attach_subgraph(syn.id, sub, kind=GraphRefKind.OWNED)

        results = root.federated_match(syn.id)
        assert ref.graph_id in results
        # Sub-grafo tem 1 memory
        assert len(results[ref.graph_id]) >= 1

    def test_filters_by_bridge_nodes(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)

        sub = CognitiveGraph()
        public = MemoryNode.episodic("public", run_id="r1")
        private = MemoryNode.episodic("private", run_id="r1")
        sub.add_node(public)
        sub.add_node(private)

        ref = root.attach_subgraph(
            syn.id, sub, kind=GraphRefKind.OWNED, bridge_nodes=[public.id]
        )

        results = root.federated_match(syn.id)
        # Apenas nós bridge devem aparecer
        for r in results[ref.graph_id]:
            assert r.node.id == public.id


# ────────────────────────────────────────────────────────────────────────────
# Persistência preservando refs
# ────────────────────────────────────────────────────────────────────────────


class TestPersistenceWithRefs:
    def test_roundtrip_preserves_refs(self) -> None:
        root = CognitiveGraph()
        syn = SynapseNode.specialist("S", role="r", objective="o")
        root.add_node(syn)

        sub = CognitiveGraph()
        sub.add_node(MemoryNode.episodic("inner", run_id="r1"))

        with tempfile.TemporaryDirectory() as tmp:
            sub_path = Path(tmp) / "sub.msgpack"
            sub.persist(sub_path)
            ref = root.attach_subgraph(
                syn.id, sub, kind=GraphRefKind.SHARED, uri=sub_path
            )
            original_ref_id = ref.graph_id

            root_path = Path(tmp) / "root.msgpack"
            root.persist(root_path)

            loaded = CognitiveGraph.load(root_path)
            loaded_syn = loaded.get_node(syn.id)
            assert loaded_syn is not None
            assert len(loaded_syn.subgraph_refs) == 1
            assert loaded_syn.subgraph_refs[0].graph_id == original_ref_id
            assert loaded_syn.subgraph_refs[0].uri == str(sub_path)

    def test_load_resolves_subgraph_from_uri(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Setup: cria sub e persiste
            sub = CognitiveGraph()
            sub.add_node(MemoryNode.episodic("sub_mem", run_id="r1"))
            sub_path = Path(tmp) / "sub.msgpack"
            sub.persist(sub_path)

            # Cria root, anexa via URI
            root = CognitiveGraph()
            syn = SynapseNode.specialist("S", role="r", objective="o")
            root.add_node(syn)
            ref = root.attach_subgraph(
                syn.id, sub, kind=GraphRefKind.SHARED, uri=sub_path
            )
            root_path = Path(tmp) / "root.msgpack"
            root.persist(root_path)

            # Em "nova sessão", carrega root com registry novo
            reg = GraphRegistry()
            loaded_root = CognitiveGraph.load(root_path, registry=reg)
            loaded_syn = loaded_root.get_node(syn.id)
            loaded_ref = loaded_syn.subgraph_refs[0]

            # Resolução lazy do disco
            resolved = loaded_root.resolve_subgraph(loaded_ref)
            assert resolved is not None
            assert resolved.node_count == 1


# ────────────────────────────────────────────────────────────────────────────
# EdgeKind.INCLUDES (intra-grafo composição)
# ────────────────────────────────────────────────────────────────────────────


class TestIncludesEdge:
    def test_includes_is_compositional(self) -> None:
        assert EdgeKind.INCLUDES.is_compositional
        assert EdgeKind.INCLUDES.is_transitive

    def test_includes_in_graph(self) -> None:
        cog = CognitiveGraph()
        cluster_root = SynapseNode.specialist(
            "cluster", role="agg", objective="aggregate"
        )
        member = MemoryNode.episodic("member", run_id="r1")
        cog.add_node(cluster_root)
        cog.add_node(member)
        edge = GraphEdge.connect(cluster_root.id, member.id, EdgeKind.INCLUDES)
        cog.add_edge(edge)
        assert cog.edge_count == 1
