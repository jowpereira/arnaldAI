"""Tests for negative memory — auto-created on run failure."""

from __future__ import annotations

from arnaldo.graph import CognitiveGraph
from arnaldo.graph.provenance import SourceRecord
from arnaldo.kernel.postprocess import create_negative_memory
from arnaldo.memory.graph_bridge import ingest_record_to_graph


_BOOT = SourceRecord.from_bootstrap("test")


class TestCreateNegativeMemory:
    def test_basic_creation(self) -> None:
        record = create_negative_memory("run-1", "query falha", "timeout", "sess-1")
        assert record.kind == "negative"
        assert "falha" in record.payload["summary"]
        assert record.payload["run_id"] == "run-1"
        assert record.payload["session_id"] == "sess-1"

    def test_id_prefix(self) -> None:
        record = create_negative_memory("run-1", "q", "err")
        assert record.id.startswith("neg_")

    def test_deterministic_id(self) -> None:
        r1 = create_negative_memory("run-1", "same query", "err1")
        r2 = create_negative_memory("run-1", "same query", "err2")
        assert r1.id == r2.id

    def test_different_run_different_id(self) -> None:
        r1 = create_negative_memory("run-1", "q", "err")
        r2 = create_negative_memory("run-2", "q", "err")
        assert r1.id != r2.id

    def test_payload_truncation(self) -> None:
        long_request = "x" * 500
        long_error = "e" * 600
        record = create_negative_memory("r", long_request, long_error)
        assert len(record.payload["pattern"]) <= 200
        assert len(record.payload["error_context"]) <= 300
        assert len(record.payload["summary"]) <= 90

    def test_empty_session_id_default(self) -> None:
        record = create_negative_memory("r", "q", "err")
        assert record.payload["session_id"] == ""


class TestNegativeIngestedToGraph:
    def test_node_created_with_negative_domain(self) -> None:
        graph = CognitiveGraph()
        record = create_negative_memory("run-1", "q", "err")
        ingest_record_to_graph(
            graph,
            {},
            record,
            association_window=6,
            materialize_support_threshold=2,
            materialize_score_threshold=0.45,
        )
        node = graph.get_node(record.id)
        assert node is not None
        assert node.domain == "negative"
        assert node.payload.get("memory_type") == "negative"
