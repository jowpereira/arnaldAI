"""Testes dos mecanismos de ligação cross-layer do grafo cognitivo.

Garante que:
1. SEMANTIC edges são criadas entre memórias com conteúdo similar
2. RECALLS edges cross-layer synapse→memory na co-ativação
3. DERIVED_FROM edges capability→memory na produção de dados
"""

from __future__ import annotations

from arnaldo.graph import CognitiveGraph, EdgeKind, NodeKind
from arnaldo.graph.node_types import CapabilityNode, MemoryNode, SynapseNode
from arnaldo.graph.provenance import SourceRecord
from arnaldo.kernel.learning import apply_learning_to_graph
from arnaldo.memory.graph_bridge import (
    ensure_semantic_link,
    ingest_record_to_graph,
)
from arnaldo.memory.models import MemoryRecord


_BOOT = SourceRecord.from_bootstrap("test")


def _make_graph() -> CognitiveGraph:
    return CognitiveGraph()


class TestSemanticEdgesBetweenMemories:
    """Memórias com conteúdo similar devem criar arestas SEMANTIC."""

    def test_semantic_link_created_when_reward_high(self) -> None:
        graph = _make_graph()
        m1 = MemoryNode.semantic(
            label="mem::bitcoin price",
            id="mem-1",
            payload={"content": "bitcoin price is 50k"},
            source=_BOOT,
        )
        m2 = MemoryNode.semantic(
            label="mem::crypto market",
            id="mem-2",
            payload={"content": "crypto market rally"},
            source=_BOOT,
        )
        graph.add_node(m1)
        graph.add_node(m2)

        ensure_semantic_link(graph, source_id="mem-1", target_id="mem-2", reward=0.6)

        edges = list(graph.iter_edges_from("mem-1", kinds=[EdgeKind.SEMANTIC]))
        assert len(edges) == 1
        assert edges[0].target_id == "mem-2"
        assert edges[0].weight > 0.4

    def test_semantic_link_not_created_when_reward_low(self) -> None:
        graph = _make_graph()
        m1 = MemoryNode.semantic(
            label="mem::hello",
            id="mem-a",
            payload={},
            source=_BOOT,
        )
        m2 = MemoryNode.semantic(
            label="mem::weather",
            id="mem-b",
            payload={},
            source=_BOOT,
        )
        graph.add_node(m1)
        graph.add_node(m2)

        ensure_semantic_link(graph, source_id="mem-a", target_id="mem-b", reward=0.1)

        edges = list(graph.iter_edges_from("mem-a", kinds=[EdgeKind.SEMANTIC]))
        assert len(edges) == 0

    def test_ingest_creates_semantic_edges_between_similar_records(self) -> None:
        graph = _make_graph()
        candidates: dict = {}

        r1 = MemoryRecord(
            id="rec-1",
            kind="episodic",
            payload={
                "action": "conversa",
                "content": "preço do bitcoin hoje",
                "session_id": "s1",
                "run_id": "r1",
            },
        )
        r2 = MemoryRecord(
            id="rec-2",
            kind="episodic",
            payload={
                "action": "conversa",
                "content": "cotação do bitcoin agora",
                "session_id": "s1",
                "run_id": "r1",
            },
        )

        ingest_record_to_graph(
            graph,
            candidates,
            r1,
            association_window=6,
            materialize_support_threshold=2,
            materialize_score_threshold=0.45,
        )
        ingest_record_to_graph(
            graph,
            candidates,
            r2,
            association_window=6,
            materialize_support_threshold=2,
            materialize_score_threshold=0.45,
        )

        # Nota: este é teste de integração — depende de related_memories()
        # retornar reward ≥ 0.3 para memórias na mesma sessão/run com
        # tokens compartilhados. Testes unitários acima cobrem o threshold.
        # Note: edge pode ser de rec-1→rec-2 ou rec-2→rec-1 dependendo da ordem
        all_semantic = []
        for nid in ("rec-1", "rec-2"):
            all_semantic.extend(graph.iter_edges_from(nid, kinds=[EdgeKind.SEMANTIC]))
        assert len(all_semantic) > 0, "Deveria criar edge SEMANTIC entre memórias similares"


class TestActivatesCrossLayer:
    """Synapses co-ativadas com memórias devem criar edges ACTIVATES."""

    def test_cross_link_created_on_positive_feedback(self) -> None:
        graph = _make_graph()
        syn = SynapseNode.specialist(
            label="syn-responder",
            id="syn-1",
            role="responder",
            objective="responder",
            tier_preference="fast",
        )
        mem = MemoryNode.semantic(
            label="mem::fact",
            id="mem-1",
            payload={"content": "fato"},
            source=_BOOT,
        )
        graph.add_node(syn)
        graph.add_node(mem)

        apply_learning_to_graph(
            graph,
            activated_node_ids=["syn-1", "mem-1"],
            feedback="positive",
            synapse_ids=["syn-1"],
            memory_ids=["mem-1"],
        )

        # Deve criar RECALLS de syn→mem (cross-layer)
        edges = list(graph.iter_edges_from("syn-1", kinds=[EdgeKind.RECALLS]))
        mem_targets = [e.target_id for e in edges]
        assert "mem-1" in mem_targets

    def test_cross_link_not_created_on_negative_feedback(self) -> None:
        graph = _make_graph()
        syn = SynapseNode.specialist(
            label="syn-analisar",
            id="syn-2",
            role="analyst",
            objective="analisar",
            tier_preference="expert",
        )
        mem = MemoryNode.semantic(
            label="mem::bad",
            id="mem-2",
            payload={},
            source=_BOOT,
        )
        graph.add_node(syn)
        graph.add_node(mem)

        apply_learning_to_graph(
            graph,
            activated_node_ids=["syn-2", "mem-2"],
            feedback="negative",
            synapse_ids=["syn-2"],
            memory_ids=["mem-2"],
        )

        # Feedback negativo (reward=0.1 < 0.5) → sem cross-link
        edges = list(graph.iter_edges_from("syn-2", kinds=[EdgeKind.RECALLS]))
        mem_targets = [e.target_id for e in edges]
        assert "mem-2" not in mem_targets

    def test_backward_compat_without_separate_ids(self) -> None:
        graph = _make_graph()
        mem = MemoryNode.semantic(
            label="mem::x",
            id="mem-3",
            payload={},
            source=_BOOT,
        )
        graph.add_node(mem)

        # Chamada sem synapse_ids/memory_ids — backward compatible
        updated = apply_learning_to_graph(
            graph,
            activated_node_ids=["mem-3"],
            feedback="positive",
        )
        assert updated == 1


class TestDerivedFromCapability:
    """Capabilities que produzem dados devem criar MemoryNode + DERIVED_FROM."""

    def test_link_creates_memory_and_edge(self) -> None:
        from arnaldo.graph.execution.capability_provenance import link_capability_to_memory

        graph = _make_graph()
        cap = CapabilityNode.new(
            label="cap-search-web",
            id="cap-1",
            payload={"capability_id": "search.public_web"},
            source=_BOOT,
        )
        graph.add_node(cap)

        link_capability_to_memory(
            graph,
            capability_id="search.public_web",
            node_id="cap-1",
            data={"title": "Bitcoin at 50k", "snippet": "Current price..."},
            request="preço do bitcoin",
        )

        # Deve ter criado MemoryNode factual
        mem_nodes = list(graph.iter_nodes(kind=NodeKind.MEMORY))
        assert len(mem_nodes) == 1
        assert "bitcoin" in mem_nodes[0].label.lower()

        # Deve ter edge DERIVED_FROM de cap→mem
        edges = list(graph.iter_edges_from("cap-1", kinds=[EdgeKind.DERIVED_FROM]))
        assert len(edges) == 1
        assert edges[0].target_id == mem_nodes[0].id
        assert edges[0].weight == 0.85

    def test_no_duplicate_memory_on_same_request(self) -> None:
        from arnaldo.graph.execution.capability_provenance import link_capability_to_memory

        graph = _make_graph()
        cap = CapabilityNode.new(
            label="cap-http",
            id="cap-2",
            payload={"capability_id": "connector.http"},
            source=_BOOT,
        )
        graph.add_node(cap)

        link_capability_to_memory(
            graph,
            capability_id="connector.http",
            node_id="cap-2",
            data="result1",
            request="test query",
        )
        link_capability_to_memory(
            graph,
            capability_id="connector.http",
            node_id="cap-2",
            data="result2",
            request="test query",
        )

        mem_nodes = list(graph.iter_nodes(kind=NodeKind.MEMORY))
        assert len(mem_nodes) == 1, "Não deve duplicar memória para mesmo request"

    def test_empty_data_produces_nothing(self) -> None:
        from arnaldo.graph.execution.capability_provenance import link_capability_to_memory

        graph = _make_graph()
        cap = CapabilityNode.new(
            label="cap-3",
            id="cap-3",
            payload={},
            source=_BOOT,
        )
        graph.add_node(cap)

        link_capability_to_memory(
            graph,
            capability_id="search.web",
            node_id="cap-3",
            data="",
            request="empty",
        )

        assert list(graph.iter_nodes(kind=NodeKind.MEMORY)) == []
