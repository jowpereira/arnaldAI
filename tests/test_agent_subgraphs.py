"""Testes de isolamento de memória por agente (agent_subgraphs)."""

from __future__ import annotations

import pytest

from arnaldo.graph import CognitiveGraph
from arnaldo.graph.node_types import MemoryNode, SynapseNode
from arnaldo.graph.provenance import SourceRecord
from arnaldo.graph.agent_subgraphs import (
    ensure_agent_subgraph,
    query_agent_context,
    route_memory_to_agent,
)

_BOOT = SourceRecord.from_bootstrap("test")


def _make_synapse(graph: CognitiveGraph, sid: str = "syn_test") -> SynapseNode:
    node = SynapseNode.specialist(
        label="test synapse",
        role="tester",
        objective="testar isolamento",
        id=sid,
        source=_BOOT,
    )
    graph.add_node(node)
    return node


def _make_memory(label: str = "fact X") -> MemoryNode:
    return MemoryNode.semantic(label=label, source=_BOOT)


class TestEnsureAgentSubgraph:
    def test_ensure_creates_subgraph(self) -> None:
        graph = CognitiveGraph()
        syn = _make_synapse(graph)
        sub = ensure_agent_subgraph(graph, syn.id)
        assert sub is not None
        assert isinstance(sub, CognitiveGraph)

    def test_ensure_returns_existing(self) -> None:
        graph = CognitiveGraph()
        syn = _make_synapse(graph)
        sub1 = ensure_agent_subgraph(graph, syn.id)
        sub2 = ensure_agent_subgraph(graph, syn.id)
        assert sub1.graph_id == sub2.graph_id

    def test_ensure_rejects_non_synapse(self) -> None:
        graph = CognitiveGraph()
        mem = _make_memory("não é synapse")
        graph.add_node(mem)
        with pytest.raises(TypeError, match="não é SYNAPSE"):
            ensure_agent_subgraph(graph, mem.id)

    def test_ensure_rejects_missing_node(self) -> None:
        graph = CognitiveGraph()
        with pytest.raises(KeyError, match="não encontrada"):
            ensure_agent_subgraph(graph, "inexistente")


class TestRouteMemory:
    def test_route_memory_adds_to_subgraph(self) -> None:
        graph = CognitiveGraph()
        syn = _make_synapse(graph)
        mem = _make_memory("dado isolado")
        ok = route_memory_to_agent(graph, syn.id, mem)
        assert ok
        sub = ensure_agent_subgraph(graph, syn.id)
        assert sub.has_node(mem.id)

    def test_route_memory_fails_gracefully(self) -> None:
        graph = CognitiveGraph()
        mem = _make_memory("sem dono")
        ok = route_memory_to_agent(graph, "inexistente", mem)
        assert not ok


class TestQueryAgentContext:
    def test_query_agent_context_empty(self) -> None:
        graph = CognitiveGraph()
        syn = _make_synapse(graph)
        ensure_agent_subgraph(graph, syn.id)
        results = query_agent_context(graph, syn.id, "qualquer coisa")
        assert results == []

    def test_query_agent_context_finds_node(self) -> None:
        graph = CognitiveGraph()
        syn = _make_synapse(graph)
        mem = _make_memory("Python async patterns")
        route_memory_to_agent(graph, syn.id, mem)
        results = query_agent_context(graph, syn.id, "Python async")
        assert len(results) >= 1
        assert any(r.node.id == mem.id for r in results)
