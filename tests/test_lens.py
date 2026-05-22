"""Testes do GraphLens — views lógicas sobre o grafo cognitivo."""

from __future__ import annotations

from arnaldo.graph import CognitiveGraph, EdgeKind, GraphLens
from arnaldo.graph.edges import GraphEdge
from arnaldo.graph.node_types import MemoryNode, SynapseNode
from arnaldo.graph.nodes import NodeKind
from arnaldo.graph.provenance import SourceRecord
from arnaldo.kernel.bootstrap import bootstrap_graph

_BOOT = SourceRecord.from_bootstrap("test")


def _mixed_graph() -> CognitiveGraph:
    """Grafo com nós de todos os tipos + edges intra e cross-layer."""
    g = CognitiveGraph()
    bootstrap_graph(g)  # 5 synapses + 2 capabilities + edges
    # Adicionar memórias
    g.add_node(
        MemoryNode.semantic(
            label="fact::bitcoin",
            id="mem-btc",
            payload={"content": "bitcoin 50k"},
            source=_BOOT,
        )
    )
    g.add_node(
        MemoryNode.semantic(
            label="fact::python",
            id="mem-py",
            payload={"content": "python 3.12"},
            source=_BOOT,
        )
    )
    # Edge intra-memory
    g.add_edge(
        GraphEdge.connect(
            source_id="mem-btc",
            target_id="mem-py",
            kind=EdgeKind.SEMANTIC,
            weight=0.5,
        )
    )
    # Edge cross-layer: synapse RECALLS memory
    g.add_edge(
        GraphEdge.connect(
            source_id="syn-analisar",
            target_id="mem-btc",
            kind=EdgeKind.RECALLS,
            weight=0.7,
        )
    )
    return g


class TestGraphLensNodeViews:
    def test_agent_nodes_returns_only_synapses_and_capabilities(self) -> None:
        graph = _mixed_graph()
        lens = GraphLens(graph)
        kinds = {n.kind for n in lens.agent_nodes()}
        assert kinds <= {NodeKind.SYNAPSE, NodeKind.CAPABILITY}
        assert lens.agent_node_count >= 7  # 5 syn + 2 cap from bootstrap

    def test_memory_nodes_returns_only_memories(self) -> None:
        graph = _mixed_graph()
        lens = GraphLens(graph)
        kinds = {n.kind for n in lens.memory_nodes()}
        assert kinds == {NodeKind.MEMORY}
        assert lens.memory_node_count == 2  # btc + py

    def test_agent_and_memory_counts_sum_to_total(self) -> None:
        graph = _mixed_graph()
        lens = GraphLens(graph)
        assert lens.agent_node_count + lens.memory_node_count == graph.node_count


class TestGraphLensEdgeViews:
    def test_agent_edges_only_agent_internal(self) -> None:
        graph = _mixed_graph()
        lens = GraphLens(graph)
        for edge in lens.agent_edges():
            assert edge.kind.is_agent_internal

    def test_memory_edges_only_memory_internal(self) -> None:
        graph = _mixed_graph()
        lens = GraphLens(graph)
        for edge in lens.memory_edges():
            assert edge.kind.is_memory_internal

    def test_cross_layer_edges_are_recalls_or_informs(self) -> None:
        graph = _mixed_graph()
        lens = GraphLens(graph)
        cross = list(lens.cross_layer_edges())
        assert len(cross) >= 1  # At least the RECALLS edge we added
        for edge in cross:
            assert edge.kind.is_cross_layer


class TestGraphLensConvenience:
    def test_memories_recalled_by_synapse(self) -> None:
        graph = _mixed_graph()
        lens = GraphLens(graph)
        mems = list(lens.memories_recalled_by("syn-analisar"))
        assert len(mems) == 1
        assert mems[0].id == "mem-btc"

    def test_memories_recalled_by_unknown_synapse(self) -> None:
        graph = _mixed_graph()
        lens = GraphLens(graph)
        mems = list(lens.memories_recalled_by("non-existent"))
        assert len(mems) == 0

    def test_synapses_informed_by_memory(self) -> None:
        graph = _mixed_graph()
        lens = GraphLens(graph)
        syn = SynapseNode.specialist(
            label="syn-extra",
            id="syn-extra",
            role="tester",
            objective="test",
            tier_preference="fast",
        )
        graph.add_node(syn)
        graph.add_edge(
            GraphEdge.connect(
                source_id="mem-btc",
                target_id="syn-extra",
                kind=EdgeKind.INFORMS,
                weight=0.6,
            )
        )
        syns = list(lens.synapses_informed_by("mem-btc"))
        assert len(syns) == 1
        assert syns[0].id == "syn-extra"


class TestEdgeKindProperties:
    def test_semantic_is_memory_internal(self) -> None:
        assert EdgeKind.SEMANTIC.is_memory_internal is True
        assert EdgeKind.SEMANTIC.is_agent_internal is False

    def test_activates_is_agent_internal(self) -> None:
        assert EdgeKind.ACTIVATES.is_agent_internal is True
        assert EdgeKind.ACTIVATES.is_memory_internal is False

    def test_recalls_is_cross_layer(self) -> None:
        assert EdgeKind.RECALLS.is_cross_layer is True
        assert EdgeKind.RECALLS.is_agent_internal is False
        assert EdgeKind.RECALLS.is_memory_internal is False

    def test_informs_is_cross_layer(self) -> None:
        assert EdgeKind.INFORMS.is_cross_layer is True
        assert EdgeKind.INFORMS.is_agent_internal is False
        assert EdgeKind.INFORMS.is_memory_internal is False

    def test_every_kind_belongs_to_at_most_one_category(self) -> None:
        for kind in EdgeKind:
            categories = sum(
                [
                    kind.is_memory_internal,
                    kind.is_agent_internal,
                    kind.is_cross_layer,
                ]
            )
            assert categories <= 1, f"{kind} pertence a {categories} categorias"
