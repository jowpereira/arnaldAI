"""Testes de plasticidade recursiva — collect_scoped_activations + apply_recursive_plasticity."""

from __future__ import annotations

from unittest.mock import patch

from arnaldo.graph import CognitiveGraph
from arnaldo.graph.node_types import SynapseNode
from arnaldo.graph.provenance import SourceRecord
from arnaldo.kernel.plasticity import (
    apply_post_run_plasticity,
    apply_recursive_plasticity,
    collect_scoped_activations,
)

_BOOT = SourceRecord.from_bootstrap("test")


def _graph_with_synapse(sid: str = "syn_1") -> CognitiveGraph:
    g = CognitiveGraph()
    node = SynapseNode.specialist(
        label="test",
        role="tester",
        objective="testar",
        id=sid,
        source=_BOOT,
    )
    g.add_node(node)
    return g


class TestCollectScopedActivations:
    def test_empty_steps(self) -> None:
        assert collect_scoped_activations([]) == {}

    def test_no_subgraph_id(self) -> None:
        steps = [{"node_id": "n1", "success": True}]
        assert collect_scoped_activations(steps) == {}

    def test_groups_by_subgraph(self) -> None:
        steps = [
            {"node_id": "n1", "subgraph_id": "sg_a", "success": True},
            {"node_id": "n2", "subgraph_id": "sg_a", "success": True},
            {"node_id": "n3", "subgraph_id": "sg_b", "success": False},
        ]
        result = collect_scoped_activations(steps)
        assert result == {"sg_a": {"n1", "n2"}, "sg_b": {"n3"}}


class TestApplyRecursivePlasticity:
    def test_noop_without_activations(self) -> None:
        graph = _graph_with_synapse()
        steps = [{"node_id": "syn_1", "success": True}]
        report = apply_recursive_plasticity(graph, steps, run_success=True)
        assert report["recursive_updates"] == 0

    def test_calls_record_outcome_recursive(self) -> None:
        graph = _graph_with_synapse("syn_parent")
        steps = [
            {"node_id": "syn_parent", "subgraph_id": "sg_x", "success": True},
        ]
        with patch("arnaldo.kernel.plasticity.record_outcome_recursive") as mock_rec:
            report = apply_recursive_plasticity(graph, steps, run_success=True)
        assert report["recursive_updates"] >= 1
        mock_rec.assert_called_once()


class TestPostRunIncludesRecursiveReport:
    def test_post_run_includes_recursive_updates(self) -> None:
        graph = _graph_with_synapse("syn_pr")
        steps = [{"node_id": "syn_pr", "success": True}]
        report = apply_post_run_plasticity(graph, step_results=steps, run_success=True)
        assert "recursive_updates" in report
        assert isinstance(report["recursive_updates"], int)
