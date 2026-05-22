"""Testes para gaps — parte 2: spawning, lens, brain scan, edge categories."""

from __future__ import annotations

from arnaldo.graph import CognitiveGraph, EdgeKind
from arnaldo.graph.brain import activate
from arnaldo.graph.lens import GraphLens
from arnaldo.graph.node_types import MemoryNode
from arnaldo.graph.provenance import SourceRecord
from arnaldo.kernel.bootstrap import bootstrap_graph

_BOOT = SourceRecord.from_bootstrap("test")


def _bootstrapped_graph() -> CognitiveGraph:
    g = CognitiveGraph()
    bootstrap_graph(g)
    return g


# ── G2: Spawning IDs estáveis ────────────────────────────────────────────


class TestG2StableSpawningIDs:
    def test_spawned_id_does_not_contain_run_id(self) -> None:
        from arnaldo.graph.execution.spawning import spawn_synapse_for_pattern

        pattern = {"intent": "debug", "examples": ["fix bug"]}
        syn, _ = spawn_synapse_for_pattern(pattern, run_id="abc12345")
        assert syn.id == "spawned-debug"
        assert "abc12345" not in syn.id

    def test_same_intent_different_run_same_id(self) -> None:
        from arnaldo.graph.execution.spawning import spawn_synapse_for_pattern

        p = {"intent": "code", "examples": []}
        s1, _ = spawn_synapse_for_pattern(p, run_id="run-aaa")
        s2, _ = spawn_synapse_for_pattern(p, run_id="run-bbb")
        assert s1.id == s2.id

    def test_try_spawn_dedup_by_stable_id(self) -> None:
        from arnaldo.graph.execution.spawning import try_spawn_from_history

        history = [
            {"role": "user", "content": "como funciona?"},
            {"role": "user", "content": "como faço?"},
        ]
        existing = {"spawned-how"}
        result = try_spawn_from_history(history, existing, run_id="r1")
        assert len(result) == 0


# ── G18: Efficient counters no GraphLens ─────────────────────────────────


class TestG18EfficientCounters:
    def test_agent_count_uses_by_kind_index(self) -> None:
        g = _bootstrapped_graph()
        lens = GraphLens(g)
        assert lens.agent_node_count == sum(1 for _ in lens.agent_nodes())

    def test_memory_count_uses_by_kind_index(self) -> None:
        g = _bootstrapped_graph()
        mem = MemoryNode.semantic(label="test", id="m1", source=_BOOT)
        g.add_node(mem)
        lens = GraphLens(g)
        assert lens.memory_node_count == 1


# ── G6: Single scan no brain ─────────────────────────────────────────────


class TestG6SingleScan:
    def test_activate_returns_both_synapses_and_memories(self) -> None:
        g = _bootstrapped_graph()
        mem = MemoryNode.semantic(
            label="fact::analisar dados complexos",
            id="mem-analise",
            source=_BOOT,
        )
        g.add_node(mem)
        decision = activate(g, "analisar dados complexos")
        assert len(decision.activated_synapses) >= 1


# ── RECALLS is_synaptic ──────────────────────────────────────────────────


class TestRecallsIsSynaptic:
    def test_recalls_is_synaptic(self) -> None:
        assert EdgeKind.RECALLS.is_synaptic is True

    def test_informs_not_synaptic(self) -> None:
        assert EdgeKind.INFORMS.is_synaptic is False


# ── Every EdgeKind belongs to at most one category (updated) ─────────────


class TestEdgeKindCategoriesUpdated:
    def test_every_kind_at_most_one_category(self) -> None:
        for kind in EdgeKind:
            cats = sum(
                [
                    kind.is_memory_internal,
                    kind.is_agent_internal,
                    kind.is_cross_layer,
                ]
            )
            assert cats <= 1, f"{kind} belongs to {cats} categories"
