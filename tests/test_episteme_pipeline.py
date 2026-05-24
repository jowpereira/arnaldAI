"""Integration tests for epistemic pipeline — kernel + foraging."""

from __future__ import annotations

from arnaldo.episteme.signals import GapType
from arnaldo.kernel.episteme_bridge import (
    check_web_search_available,
    maybe_forage,
)
from arnaldo.kernel.episteme_hooks import (
    collect_pending_prospective,
    create_prospective_memory,
    resolve_prospective_memories,
)
from arnaldo.graph import CognitiveGraph
from arnaldo.graph.brain import BrainDecision
from arnaldo.graph.node_types import CapabilityNode, MemoryNode
from arnaldo.graph.provenance import SourceRecord
from arnaldo.capabilities.base import CapabilityResult


from arnaldo.episteme.forager import WebForager


_BOOT = SourceRecord.from_bootstrap("test")


# ── ThinkingEmitter integration ──────────────────────────────────────


class TestMaybeForageWithThinking:
    def setup_method(self) -> None:
        WebForager.reset_counter()

    def test_maybe_forage_with_thinking_emits(self, monkeypatch: object) -> None:
        from arnaldo.kernel.thinking import ThinkingEmitter, ThinkingEvent, ThinkingKind

        graph = CognitiveGraph()
        emitter = ThinkingEmitter()
        received: list[ThinkingEvent] = []
        emitter.register(received.append)

        fake_result = CapabilityResult(
            success=True,
            data={"results": [{"title": "X", "snippet": "Y", "url": "http://x.com"}]},
            source=_BOOT,
        )
        from arnaldo.episteme import forager as _forager_mod

        monkeypatch.setattr(
            _forager_mod.WebSearchCapability,
            "execute",
            lambda self, params: fake_result,
        )

        created = maybe_forage(
            graph,
            GapType.GENUINE,
            "azure deploy",
            0.1,
            has_web_search=True,
            thinking=emitter,
        )
        assert len(created) >= 1
        # Verifica que thinking emitiu pelo menos um SEARCHING
        searching_events = [e for e in received if e.kind == ThinkingKind.SEARCHING]
        assert len(searching_events) >= 1
        assert "azure deploy" in searching_events[0].query


# ── episteme_hooks ───────────────────────────────────────────────────


class TestCreateProspectiveMemory:
    def test_creates_record_when_gap(self) -> None:
        decision = BrainDecision(
            primary_synapse=None,
            tier="fast",
            complexity="conversational",
            skip_full_pipeline=True,
            needs_external_data=True,
            knowledge_gap=True,
            gap_type=GapType.GENUINE,
            confidence=0.1,
        )
        record = create_prospective_memory(decision, "pergunta misteriosa")
        assert record is not None
        assert record.kind == "prospective"
        assert record.payload["gap_type"] == "genuine"
        assert record.payload["status"] == "pending"

    def test_returns_none_when_no_gap(self) -> None:
        decision = BrainDecision(
            primary_synapse="syn-ok",
            tier="fast",
            complexity="conversational",
            skip_full_pipeline=True,
            needs_external_data=False,
            knowledge_gap=False,
        )
        assert create_prospective_memory(decision, "ok") is None


class TestCollectPendingProspective:
    def test_finds_pending_prospective_nodes(self) -> None:
        graph = CognitiveGraph()
        node = MemoryNode.semantic(
            label="prospect::test",
            id="p1",
            payload={"memory_type": "prospective", "status": "pending", "query": "q"},
            source=_BOOT,
            domain="prospective",
        )
        # Sobrescreve memory_type que semantic() força
        node.payload["memory_type"] = "prospective"
        graph.add_node(node)
        pending = collect_pending_prospective(graph)
        assert len(pending) == 1
        assert pending[0]["query"] == "q"

    def test_empty_graph_returns_empty(self) -> None:
        graph = CognitiveGraph()
        assert collect_pending_prospective(graph) == []


# ── episteme_bridge ──────────────────────────────────────────────────


class TestMaybeForage:
    def setup_method(self) -> None:
        WebForager.reset_counter()

    def test_none_gap_returns_empty(self) -> None:
        graph = CognitiveGraph()
        assert maybe_forage(graph, GapType.NONE, "q", 0.5) == []

    def test_genuine_gap_without_web_returns_empty(self) -> None:
        graph = CognitiveGraph()
        result = maybe_forage(graph, GapType.GENUINE, "q", 0.1, has_web_search=False)
        assert result == []

    def test_genuine_gap_with_web_creates_nodes(self, monkeypatch: object) -> None:
        graph = CognitiveGraph()
        fake_result = CapabilityResult(
            success=True,
            data={
                "results": [
                    {"title": "A", "snippet": "SA", "url": "http://a.com"},
                    {"title": "B", "snippet": "SB", "url": "http://b.com"},
                ]
            },
            source=_BOOT,
        )
        from arnaldo.episteme import forager as _forager_mod

        monkeypatch.setattr(
            _forager_mod.WebSearchCapability,
            "execute",
            lambda self, params: fake_result,
        )
        created = maybe_forage(graph, GapType.GENUINE, "test query", 0.1, has_web_search=True)
        assert len(created) == 2
        for nid in created:
            assert graph.has_node(nid)


class TestCheckWebSearchAvailable:
    def test_no_capability_returns_false(self) -> None:
        graph = CognitiveGraph()
        assert check_web_search_available(graph) is False

    def test_with_web_cap_returns_true(self) -> None:
        graph = CognitiveGraph()
        cap = CapabilityNode.new(
            label="Web Search",
            id="cap-web",
            payload={"capability_id": "search.public_web"},
            source=_BOOT,
        )
        graph.add_node(cap)
        assert check_web_search_available(graph) is True


# ── resolve_prospective_memories ─────────────────────────────────────


class TestResolveProspective:
    def test_resolve_after_foraging(self) -> None:
        graph = CognitiveGraph()
        node = MemoryNode.semantic(
            label="prospect::test",
            id="p1",
            payload={
                "memory_type": "prospective",
                "status": "pending",
                "query": "test",
                "gap_type": "genuine",
            },
            source=_BOOT,
            domain="prospective",
        )
        node.payload["memory_type"] = "prospective"
        graph.add_node(node)
        count = resolve_prospective_memories(graph, "test", GapType.GENUINE)
        assert count == 1
        updated = graph.get_node("p1")
        assert updated.payload["status"] == "resolved"

    def test_resolve_no_match_returns_zero(self) -> None:
        graph = CognitiveGraph()
        count = resolve_prospective_memories(graph, "q", GapType.GENUINE)
        assert count == 0

    def test_resolve_skips_already_resolved(self) -> None:
        graph = CognitiveGraph()
        node = MemoryNode.semantic(
            label="prospect::done",
            id="p2",
            payload={
                "memory_type": "prospective",
                "status": "resolved",
                "query": "test",
                "gap_type": "genuine",
            },
            source=_BOOT,
            domain="prospective",
        )
        node.payload["memory_type"] = "prospective"
        graph.add_node(node)
        count = resolve_prospective_memories(graph, "test", GapType.GENUINE)
        assert count == 0
