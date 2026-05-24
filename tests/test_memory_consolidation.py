"""Testes para consolidação episodic → semantic."""

from __future__ import annotations

from arnaldo.graph import CognitiveGraph
from arnaldo.graph.edges import EdgeKind
from arnaldo.graph.node_types import MemoryNode
from arnaldo.memory.consolidation import ConsolidationResult, consolidate_episodic_memories


def _make_episodic(graph: CognitiveGraph, idx: int, action: str = "plan_project") -> str:
    """Helper: cria nó episódico com payload similar."""
    node = MemoryNode.episodic(
        label=f"episodic::{action}",
        id=f"ep-{idx}",
        run_id=f"run-{idx}",
        payload={"action": action, "capability_id": "intent.compile"},
    )
    graph.add_node(node)
    return node.id


class TestConsolidation:
    def test_consolidate_creates_semantic_from_cluster(self) -> None:
        graph = CognitiveGraph()
        for i in range(3):
            _make_episodic(graph, i)
        result = consolidate_episodic_memories(graph, min_cluster_size=3)
        assert len(result.created_semantic_ids) == 1
        assert len(result.source_episodic_ids) == 3
        sem = graph.get_node(result.created_semantic_ids[0])
        assert sem is not None
        assert sem.payload["memory_type"] == "semantic"
        assert sem.payload["pattern"] == "plan_project"

    def test_consolidate_skips_small_clusters(self) -> None:
        graph = CognitiveGraph()
        _make_episodic(graph, 0)
        _make_episodic(graph, 1)
        result = consolidate_episodic_memories(graph, min_cluster_size=3)
        assert result == ConsolidationResult((), (), 0)

    def test_consolidate_empty_graph(self) -> None:
        graph = CognitiveGraph()
        result = consolidate_episodic_memories(graph)
        assert result == ConsolidationResult((), (), 0)

    def test_consolidate_creates_derived_from_edges(self) -> None:
        graph = CognitiveGraph()
        ep_ids = [_make_episodic(graph, i) for i in range(4)]
        result = consolidate_episodic_memories(graph, min_cluster_size=3)
        assert result.edges_created == 4
        sem_id = result.created_semantic_ids[0]
        for ep_id in ep_ids:
            edges = list(graph.iter_edges_from(ep_id, kinds=[EdgeKind.DERIVED_FROM]))
            assert any(e.target_id == sem_id for e in edges)

    def test_consolidate_respects_max_consolidations(self) -> None:
        graph = CognitiveGraph()
        # Cluster A: 3 nós similares
        for i in range(3):
            _make_episodic(graph, i, action="plan_project")
        # Cluster B: 3 nós similares com ação diferente
        for i in range(3, 6):
            _make_episodic(graph, i, action="deploy_service")
        result = consolidate_episodic_memories(graph, min_cluster_size=3, max_consolidations=1)
        assert len(result.created_semantic_ids) == 1
