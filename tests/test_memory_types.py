"""Testes dos factory methods enriquecidos de MemoryNode."""

from __future__ import annotations

from arnaldo.graph.node_types import MemoryNode
from arnaldo.graph.nodes import NodeKind
from arnaldo.graph.provenance import SourceRecord


_BOOT = SourceRecord.from_bootstrap("test")


class TestMemoryNodeFactories:
    """Factory methods de MemoryNode para tipos enriquecidos."""

    def test_fact_creates_memory_with_correct_type(self) -> None:
        mem = MemoryNode.fact(
            label="fact::terra é redonda",
            source=_BOOT,
        )
        assert mem.payload["memory_type"] == "fact"
        assert mem.kind == NodeKind.MEMORY

    def test_fact_default_domain_is_factual(self) -> None:
        mem = MemoryNode.fact(label="test", source=_BOOT)
        assert mem.domain == "factual"

    def test_fact_custom_payload_preserved(self) -> None:
        mem = MemoryNode.fact(
            label="fact::gravidade",
            source=_BOOT,
            payload={"extra": "9.8 m/s²"},
        )
        assert mem.payload["memory_type"] == "fact"
        assert mem.payload["extra"] == "9.8 m/s²"

    def test_fact_custom_id(self) -> None:
        mem = MemoryNode.fact(label="test", source=_BOOT, id="mem-custom")
        assert mem.id == "mem-custom"

    def test_lesson_creates_memory_with_pattern(self) -> None:
        mem = MemoryNode.lesson(
            label="lesson::não usar any",
            source=_BOOT,
            pattern="typing violation",
        )
        assert mem.payload["memory_type"] == "lesson"
        assert mem.payload["pattern"] == "typing violation"

    def test_lesson_default_domain_is_procedural(self) -> None:
        mem = MemoryNode.lesson(label="test", source=_BOOT)
        assert mem.domain == "procedural"

    def test_lesson_without_pattern_omits_key(self) -> None:
        mem = MemoryNode.lesson(label="test", source=_BOOT)
        assert "pattern" not in mem.payload

    def test_execution_creates_memory_with_run_id(self) -> None:
        mem = MemoryNode.execution(
            label="exec::run-123",
            source=_BOOT,
            run_id="run-123",
        )
        assert mem.payload["memory_type"] == "execution"
        assert mem.payload["run_id"] == "run-123"

    def test_execution_default_domain_is_operational(self) -> None:
        mem = MemoryNode.execution(label="test", source=_BOOT)
        assert mem.domain == "operational"

    def test_execution_without_run_id_omits_key(self) -> None:
        mem = MemoryNode.execution(label="test", source=_BOOT)
        assert "run_id" not in mem.payload
