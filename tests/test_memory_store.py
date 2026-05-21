from __future__ import annotations

from pathlib import Path
import tempfile

from arnaldo.graph import EdgeKind, NodeKind, SynapseNode
from arnaldo.memory import MemoryRecord, MemoryStore, MemorySynapseCandidate


def _read_jsonl(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_memory_store_persists_graph_and_candidates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "memory"
        store = MemoryStore(
            base,
            association_window=4,
            materialize_support_threshold=2,
            materialize_score_threshold=0.2,
        )
        record_a = MemoryRecord(
            id="mem_a",
            kind="procedural",
            payload={
                "session_id": "sess_1",
                "action": "design_tooling",
                "summary": "desenhar plano de conector http",
            },
        )
        record_b = MemoryRecord(
            id="mem_b",
            kind="procedural",
            payload={
                "session_id": "sess_1",
                "action": "design_tooling",
                "summary": "desenhar plano de conector http",
            },
        )

        store.append(record_a)
        store.append(record_b)
        # Reforça a mesma associação (A -> B) para disparar materialização.
        store.append(record_b)

        graph = store.load_graph()
        assert graph.node_count >= 2
        synapses = list(graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=False))
        assert len(synapses) >= 1
        assert any(node.id.startswith("synmem_") for node in synapses)

        candidate_rows = store.memory_synapses(limit=10)
        assert any(item["materialized_synapse_id"] for item in candidate_rows)

        procedural_log = _read_jsonl(base / "procedural.jsonl")
        assert len(procedural_log) == 3
        assert (base / "memory-graph.msgpack").exists()
        assert (base / "synapse-candidates.json").exists()


def test_memory_store_record_feedback_updates_materialized_synapse() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "memory"
        store = MemoryStore(
            base,
            association_window=3,
            materialize_support_threshold=2,
            materialize_score_threshold=0.2,
        )
        store.append(
            MemoryRecord(
                id="mem_origin",
                kind="episodic",
                payload={"run_id": "run_1", "session_id": "sess_2", "summary": "inicio"},
            )
        )
        store.append(
            MemoryRecord(
                id="mem_target",
                kind="episodic",
                payload={"run_id": "run_1", "session_id": "sess_2", "summary": "passo seguinte"},
            )
        )

        store.record_feedback(
            source_memory_id="mem_origin",
            target_memory_id="mem_target",
            reward=1.0,
        )

        graph = store.load_graph()
        candidates = store.memory_synapses(limit=10)
        materialized = [item for item in candidates if item["materialized_synapse_id"]]
        assert materialized
        synapse_id = materialized[0]["materialized_synapse_id"]
        synapse = graph.get_node(synapse_id)
        assert isinstance(synapse, SynapseNode)
        assert synapse.payload.get("support", 0) >= 2

        mentions_edges = list(graph.iter_edges_from(synapse_id, kinds=[EdgeKind.MENTIONS], active_only=False))
        assert any(edge.target_id == "mem_target" for edge in mentions_edges)


def test_memory_store_builds_workflow_hints_from_memory_graph() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "memory"
        store = MemoryStore(base, association_window=4)
        store.append(
            MemoryRecord(
                id="step_1",
                kind="procedural",
                payload={
                    "run_id": "run_hints",
                    "session_id": "sess_hints",
                    "action": "frame_intent",
                    "summary": "enquadrar problema",
                },
            )
        )
        store.append(
            MemoryRecord(
                id="step_2",
                kind="procedural",
                payload={
                    "run_id": "run_hints",
                    "session_id": "sess_hints",
                    "action": "decompose_work",
                    "summary": "decompor plano de execucao",
                },
            )
        )
        store.append(
            MemoryRecord(
                id="step_3",
                kind="procedural",
                payload={
                    "run_id": "run_hints",
                    "session_id": "sess_hints",
                    "action": "draft_artifact",
                    "summary": "gerar artefato",
                },
            )
        )
        hints = store.build_workflow_hints(goal="preciso decompor e gerar plano", limit=8)
        assert "preferred_actions" in hints
        assert "transitions" in hints
        preferred = hints["preferred_actions"]
        assert isinstance(preferred, list)
        assert "decompose_work" in preferred
        transitions = hints["transitions"]
        assert any(
            item["source_action"] == "frame_intent"
            and item["target_action"] == "decompose_work"
            for item in transitions
        )


def test_memory_candidates_accumulate_across_distinct_memory_ids() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "memory"
        store = MemoryStore(
            base,
            association_window=4,
            materialize_support_threshold=2,
            materialize_score_threshold=0.2,
        )
        store.append(
            MemoryRecord(
                id="run1_step1",
                kind="procedural",
                payload={
                    "run_id": "run1",
                    "session_id": "sess",
                    "agent_id": "operator",
                    "action": "frame_intent",
                    "summary": "enquadrar objetivo",
                },
            )
        )
        store.append(
            MemoryRecord(
                id="run1_step2",
                kind="procedural",
                payload={
                    "run_id": "run1",
                    "session_id": "sess",
                    "agent_id": "operator",
                    "action": "decompose_work",
                    "summary": "decompor plano",
                },
            )
        )
        store.append(
            MemoryRecord(
                id="run2_step1",
                kind="procedural",
                payload={
                    "run_id": "run2",
                    "session_id": "sess",
                    "agent_id": "operator",
                    "action": "frame_intent",
                    "summary": "enquadrar novamente",
                },
            )
        )
        store.append(
            MemoryRecord(
                id="run2_step2",
                kind="procedural",
                payload={
                    "run_id": "run2",
                    "session_id": "sess",
                    "agent_id": "operator",
                    "action": "decompose_work",
                    "summary": "decompor novamente",
                },
            )
        )

        rows = store.memory_synapses(limit=20)
        assert any(item["support"] >= 2 for item in rows)
        assert any(item.get("materialized_synapse_id") for item in rows)


def test_memory_synapse_candidate_from_dict_handles_null_materialized_synapse() -> None:
    candidate = MemorySynapseCandidate.from_dict(
        {
            "source_memory_id": "mem_a",
            "target_memory_id": "mem_b",
            "source_signature": "procedural|frame_intent|-|operator",
            "target_signature": "procedural|decompose_work|-|operator",
            "support": 1,
            "greedy_score": 0.7,
            "materialized_synapse_id": None,
        }
    )
    assert candidate.materialized_synapse_id is None
    assert candidate.is_materialized is False
