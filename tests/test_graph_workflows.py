from __future__ import annotations

from pathlib import Path
import tempfile

from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
    GraphRefKind,
    GraphRegistry,
    NodeKind,
    SynapseNode,
    compose_workflows,
    make_workflow,
)


def test_make_workflow_materializes_orchestrator_and_subgraph() -> None:
    graph = CognitiveGraph()
    orchestrator, subgraph, ref = make_workflow(
        graph,
        workflow_id="syn_workflow_plan",
        label="workflow::plan",
        steps=[
            {"action": "frame_intent", "agent_id": "framer", "output": "intent_frame"},
            {"action": "decompose_work", "agent_id": "planner", "output": "work_plan"},
            {"action": "draft_artifact", "agent_id": "planner", "output": "artifact"},
        ],
    )

    stored = graph.get_node(orchestrator.id)
    assert isinstance(stored, SynapseNode)
    assert stored.payload.get("action") == "workflow_orchestrator"
    assert stored.has_subgraphs
    assert ref.kind == GraphRefKind.OWNED

    resolved = graph.resolve_subgraph(ref)
    assert resolved is subgraph
    step_nodes = list(resolved.iter_nodes(kind=NodeKind.SYNAPSE, active_only=False))
    assert len(step_nodes) == 3

    activates_edges = []
    for node in step_nodes:
        activates_edges.extend(list(resolved.iter_edges_from(node.id, kinds=[EdgeKind.ACTIVATES], active_only=False)))
    assert len(activates_edges) == 2


def test_compose_workflows_creates_meta_orchestrator_and_shared_refs() -> None:
    graph = CognitiveGraph()
    w1, _, _ = make_workflow(
        graph,
        workflow_id="syn_workflow_a",
        label="workflow::a",
        steps=[
            {"action": "frame_intent", "agent_id": "framer", "output": "intent_a"},
            {"action": "draft_artifact", "agent_id": "planner", "output": "artifact_a"},
        ],
    )
    w2, _, _ = make_workflow(
        graph,
        workflow_id="syn_workflow_b",
        label="workflow::b",
        steps=[
            {"action": "frame_intent", "agent_id": "framer", "output": "intent_b"},
            {"action": "critic_review", "agent_id": "critic", "output": "review_b"},
        ],
    )

    composed = compose_workflows(
        graph,
        composition_id="syn_workflow_meta",
        label="workflow::meta",
        workflow_ids=[w1.id, w2.id],
    )
    stored = graph.get_node(composed.id)
    assert isinstance(stored, SynapseNode)
    assert stored.payload.get("action") == "workflow_composition"
    composed_refs = list(stored.subgraph_refs)
    assert len(composed_refs) >= 2
    assert all(ref.kind == GraphRefKind.SHARED for ref in composed_refs)

    to_a = list(graph.iter_edges_from(composed.id, kinds=[EdgeKind.ACTIVATES], active_only=False))
    assert any(edge.target_id == w1.id for edge in to_a)


def test_make_workflow_snapshot_is_read_only_when_uri_provided() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        registry = GraphRegistry(base_path=base)
        graph = CognitiveGraph(registry=registry)
        orchestrator, _, ref = make_workflow(
            graph,
            workflow_id="syn_workflow_snapshot",
            label="workflow::snapshot",
            kind=GraphRefKind.SNAPSHOT,
            uri=base / "snapshot_workflow.msgpack",
            steps=[
                {"action": "frame_intent", "agent_id": "framer", "output": "intent"},
                {"action": "draft_artifact", "agent_id": "planner", "output": "artifact"},
            ],
        )
        assert orchestrator.id == "syn_workflow_snapshot"
        resolved = graph.resolve_subgraph(ref)
        assert resolved is not None
        assert resolved.is_read_only

