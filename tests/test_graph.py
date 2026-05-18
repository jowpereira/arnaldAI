"""Testes do substrate cognitivo (``arnaldo.graph``).

Cobertura:

* Modelo bi-temporal — janelas, overlap, invalidation
* Proveniência — taxonomia, baseline confidence, degradação
* Nós — factory methods, mutações imutáveis, especializações
* Arestas — tipos, simetria semântica, validação de self-loops
* Plasticidade — Hebbian update, decay adaptativo, classificação de status
* Matching — vector search, expansion, intent routing
* CognitiveGraph — add/remove, índices, ativação, persistência round-trip
"""
from __future__ import annotations

from dataclasses import dataclass
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from arnaldo.graph import (
    BiTemporal,
    CapabilityNode,
    CognitiveGraph,
    DecayPolicy,
    EdgeKind,
    GraphEdge,
    HebbianRule,
    HybridMatcher,
    MemoryNode,
    NodeKind,
    NodeStatus,
    PlasticityEngine,
    SourceKind,
    SourceRecord,
    SynapseNode,
    ValidityWindow,
    utc_now,
)
from arnaldo.graph.matching import INTENT_TO_EDGES, classify_intent


# ────────────────────────────────────────────────────────────────────────────
# Temporal
# ────────────────────────────────────────────────────────────────────────────


class TestValidityWindow:
    def test_open_window_valid_forever(self) -> None:
        w = ValidityWindow.from_now()
        future = utc_now() + timedelta(days=365)
        assert w.is_valid_at(future)

    def test_closed_window_rejects_future(self) -> None:
        start = utc_now()
        w = ValidityWindow(valid_from=start, valid_to=start + timedelta(days=1))
        assert w.is_valid_at(start)
        assert not w.is_valid_at(start + timedelta(days=2))

    def test_valid_to_before_from_raises(self) -> None:
        now = utc_now()
        with pytest.raises(ValueError, match="deve ser >"):
            ValidityWindow(valid_from=now, valid_to=now - timedelta(seconds=1))

    def test_overlaps_detection(self) -> None:
        now = utc_now()
        a = ValidityWindow(now, now + timedelta(days=10))
        b = ValidityWindow(now + timedelta(days=5), now + timedelta(days=15))
        c = ValidityWindow(now + timedelta(days=20), now + timedelta(days=30))
        assert a.overlaps(b)
        assert not a.overlaps(c)

    def test_closed_at_returns_new_window(self) -> None:
        now = utc_now()
        w = ValidityWindow.from_now()
        closed = w.closed_at(now + timedelta(days=1))
        assert closed.valid_to == now + timedelta(days=1)
        assert w.valid_to is None  # original imutável


class TestBiTemporal:
    def test_active_by_default(self) -> None:
        bt = BiTemporal.now()
        assert bt.is_active

    def test_invalidate_idempotent(self) -> None:
        bt = BiTemporal.now()
        bt2 = bt.invalidate()
        bt3 = bt2.invalidate()
        assert not bt2.is_active
        assert bt2.invalidated_at == bt3.invalidated_at

    def test_age_seconds_increases(self) -> None:
        past = utc_now() - timedelta(seconds=60)
        bt = BiTemporal(window=ValidityWindow.open_at(past))
        assert bt.age_seconds() >= 60.0


# ────────────────────────────────────────────────────────────────────────────
# Proveniência
# ────────────────────────────────────────────────────────────────────────────


class TestSourceRecord:
    def test_baseline_confidence_by_kind(self) -> None:
        s = SourceRecord(kind=SourceKind.BOOTSTRAP, identifier="x")
        assert s.confidence == 0.99
        s2 = SourceRecord(kind=SourceKind.INFERENCE, identifier="y")
        assert s2.confidence == 0.65

    def test_explicit_confidence_overrides_default(self) -> None:
        s = SourceRecord(
            kind=SourceKind.EXTERNAL_AUTHORITY,
            identifier="paper",
            confidence=0.92,
        )
        assert s.confidence == 0.92

    def test_invalid_confidence_raises(self) -> None:
        with pytest.raises(ValueError):
            SourceRecord(
                kind=SourceKind.BOOTSTRAP, identifier="x", confidence=1.5
            )

    def test_empty_identifier_raises(self) -> None:
        with pytest.raises(ValueError):
            SourceRecord(kind=SourceKind.BOOTSTRAP, identifier="")

    def test_degrade_reduces_confidence(self) -> None:
        s = SourceRecord(kind=SourceKind.BOOTSTRAP, identifier="x")
        s2 = s.degrade(0.5)
        assert s2.confidence == pytest.approx(s.confidence * 0.5)
        assert s.confidence == 0.99  # original imutável

    def test_helpers(self) -> None:
        u = SourceRecord.from_user("sess_42")
        assert u.kind == SourceKind.DIRECT_OBSERVATION
        assert "sess_42" in u.identifier

        r = SourceRecord.from_run("run_abc", agent="critic")
        assert r.kind == SourceKind.SYSTEM_ARTIFACT
        assert "run_abc" in r.identifier


# ────────────────────────────────────────────────────────────────────────────
# Nós
# ────────────────────────────────────────────────────────────────────────────


class TestMemoryNode:
    def test_episodic_factory(self) -> None:
        m = MemoryNode.episodic("Usuário pediu plano B2B", run_id="run_123")
        assert m.kind == NodeKind.MEMORY
        assert m.payload["memory_type"] == "episodic"
        assert m.payload["run_id"] == "run_123"
        assert m.domain == "episodic"

    def test_semantic_factory(self) -> None:
        s = SourceRecord(kind=SourceKind.EXTERNAL_AUTHORITY, identifier="arxiv:1")
        m = MemoryNode.semantic("MAGMA tem 4 grafos ortogonais", source=s)
        assert m.payload["memory_type"] == "semantic"
        assert m.domain == "semantic_stable"

    def test_id_uniqueness(self) -> None:
        m1 = MemoryNode.episodic("x", run_id="r1")
        m2 = MemoryNode.episodic("x", run_id="r1")
        assert m1.id != m2.id

    def test_invalid_weight_raises(self) -> None:
        with pytest.raises(ValueError):
            MemoryNode(id="m1", kind=NodeKind.MEMORY, label="x", weight=2.0)


class TestSynapseNode:
    def test_specialist_factory(self) -> None:
        s = SynapseNode.specialist(
            "Framer", role="framer", objective="enquadrar intenção"
        )
        assert s.role == "framer"
        assert s.kind == NodeKind.SYNAPSE
        assert "send.external_message" in s.payload["forbidden_capabilities"]

    def test_with_weight_is_immutable(self) -> None:
        s = SynapseNode.specialist("Critic", role="critic", objective="x")
        s2 = s.with_weight(0.9)
        assert s.weight == 0.5
        assert s2.weight == 0.9

    def test_specialist_persists_output_contract_model_schema(self) -> None:
        @dataclass
        class Contract:
            result: str
            evidence: list[str]

        s = SynapseNode.specialist(
            "Framer",
            role="framer",
            objective="enquadrar",
            output_contract_model=Contract,
        )
        assert s.payload["output_contract_model"] == "Contract"
        assert s.payload["output_schema"]["type"] == "object"
        assert "result" in s.payload["output_schema"]["required"]
        assert "evidence" in s.payload["output_schema"]["required"]


class TestCapabilityNode:
    def test_tool_factory_with_maturity(self) -> None:
        c = CapabilityNode.tool(
            "search.public_web",
            description="Web search",
            maturity="trusted",
        )
        assert c.maturity == "trusted"
        assert c.weight == 0.85  # trusted default

    def test_invalid_maturity_raises(self) -> None:
        with pytest.raises(ValueError, match="maturity inválido"):
            CapabilityNode.tool("x.y", description="d", maturity="invented")

    def test_promote_advances_maturity(self) -> None:
        c = CapabilityNode.tool("x.y", description="d", maturity="draft")
        c2 = c.promote()
        assert c2.maturity == "tested"
        c3 = c2.promote()
        assert c3.maturity == "trusted"
        # idempotente em trusted
        assert c3.promote().maturity == "trusted"

    def test_promote_deprecated_raises(self) -> None:
        c = CapabilityNode.tool("x.y", description="d", maturity="deprecated")
        with pytest.raises(ValueError, match="deprecated"):
            c.promote()


# ────────────────────────────────────────────────────────────────────────────
# Arestas
# ────────────────────────────────────────────────────────────────────────────


class TestGraphEdge:
    def test_connect_factory(self) -> None:
        e = GraphEdge.connect("a", "b", EdgeKind.CAUSAL)
        assert e.kind == EdgeKind.CAUSAL
        assert 0 < e.weight <= 1.0

    def test_self_loop_rejected_for_directional(self) -> None:
        with pytest.raises(ValueError, match="Self-loop"):
            GraphEdge.connect("a", "a", EdgeKind.CAUSAL)

    def test_self_loop_allowed_for_semantic(self) -> None:
        e = GraphEdge.connect("a", "a", EdgeKind.SEMANTIC)
        assert e.source_id == e.target_id == "a"

    def test_kind_classification(self) -> None:
        assert EdgeKind.SEMANTIC.is_directed is False
        assert EdgeKind.CAUSAL.is_directed is True
        assert EdgeKind.ACTIVATES.is_synaptic is True
        assert EdgeKind.REQUIRES.is_synaptic is False
        assert EdgeKind.IS_A.is_transitive is True


# ────────────────────────────────────────────────────────────────────────────
# Plasticidade
# ────────────────────────────────────────────────────────────────────────────


class TestHebbianRule:
    def test_success_increases_weight(self) -> None:
        rule = HebbianRule(learning_rate=0.20)
        new = rule.update(0.5, success_rate=1.0)
        assert new > 0.5

    def test_failure_decreases_weight(self) -> None:
        rule = HebbianRule(learning_rate=0.20)
        new = rule.update(0.5, success_rate=0.0)
        assert new < 0.5

    def test_cap_per_step(self) -> None:
        rule = HebbianRule(learning_rate=1.0, cap_per_step=0.10)
        new = rule.update(0.5, success_rate=1.0)
        # Mudança não excede cap
        assert abs(new - 0.5) <= 0.10 + 1e-9

    def test_floor_and_ceiling(self) -> None:
        rule = HebbianRule(floor=0.05, ceiling=0.95)
        # 1000 sucessos → não passa de ceiling
        w = 0.5
        for _ in range(1000):
            w = rule.update(w, success_rate=1.0)
        assert w <= 0.95
        # 1000 falhas → não desce de floor
        w = 0.5
        for _ in range(1000):
            w = rule.update(w, success_rate=0.0)
        assert w >= 0.05


class TestDecayPolicy:
    def test_decay_factor_in_unit_interval(self) -> None:
        p = DecayPolicy()
        for d in ["episodic", "semantic_stable", "tech_news"]:
            f = p.decay_factor(d, timedelta(days=10))
            assert 0.0 <= f <= 1.0

    def test_half_life_semantics(self) -> None:
        p = DecayPolicy()
        # após 1 half-life, fator ~= 0.5
        hl = p.half_life_for("episodic")
        f = p.decay_factor("episodic", hl)
        assert 0.45 < f < 0.55

    def test_unknown_domain_uses_fallback(self) -> None:
        p = DecayPolicy()
        f = p.decay_factor("dominio_inexistente", timedelta(days=1))
        # fallback é 60d → 1d quase nada decai
        assert f > 0.9

    def test_different_domains_decay_differently(self) -> None:
        p = DecayPolicy()
        t = timedelta(days=7)
        f_news = p.decay_factor("tech_news", t)        # half_life=3d
        f_stable = p.decay_factor("semantic_stable", t)  # half_life=180d
        assert f_news < f_stable  # news decai mais rápido


class TestPlasticityEngine:
    def test_effective_weight_combines_factors(self) -> None:
        eng = PlasticityEngine()
        node = MemoryNode.episodic("x", run_id="r1")
        node = node.with_weight(0.8)
        eff = eng.effective_weight(node)
        # 0.8 (base) * ~1.0 (decay ~0) * 0.75 (sys_artifact baseline) ≈ 0.6
        assert 0.5 < eff < 0.9

    def test_classify_status_after_decay(self) -> None:
        # Cria nó "antigo"
        eng = PlasticityEngine()
        ancient = MemoryNode(
            id="m_old",
            kind=NodeKind.MEMORY,
            label="muito antigo",
            weight=0.5,
            bitemp=BiTemporal(
                window=ValidityWindow.open_at(
                    utc_now() - timedelta(days=10_000)
                )
            ),
            domain="tech_news",  # half-life=3d → 10k dias = decay total
        )
        status = eng.classify_status(ancient)
        assert status in {"stale", "archived"}

    def test_update_node_after_success(self) -> None:
        eng = PlasticityEngine()
        node = SynapseNode.specialist("X", role="x", objective="y")
        original_weight = node.weight
        updated = eng.update_node(node, success=True)
        assert updated.weight > original_weight
        assert updated.stats.successes == 1


# ────────────────────────────────────────────────────────────────────────────
# Matching
# ────────────────────────────────────────────────────────────────────────────


class TestIntentClassification:
    @pytest.mark.parametrize(
        "query,expected",
        [
            ("por que isso aconteceu?", "why"),
            ("quando o evento começou", "when"),
            ("quem é o responsável", "who"),
            ("como executar essa task", "how"),
            ("o que é MAGMA", "what"),
            ("resumo da sessão", "summary"),
            ("isso é um teste", "default"),
        ],
    )
    def test_classifier(self, query: str, expected: str) -> None:
        assert classify_intent(query) == expected

    def test_intent_to_edges_mapping(self) -> None:
        assert EdgeKind.CAUSAL in INTENT_TO_EDGES["why"]
        assert EdgeKind.TEMPORAL_BEFORE in INTENT_TO_EDGES["when"]
        assert EdgeKind.SEMANTIC in INTENT_TO_EDGES["default"]


class TestHybridMatcher:
    def _build_graph_with_embeddings(self) -> CognitiveGraph:
        cog = CognitiveGraph()
        # 3 memórias com embeddings sintéticos (3D)
        a = MemoryNode.episodic("evento alpha", run_id="r1")
        a.embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = MemoryNode.episodic("evento beta", run_id="r1")
        b.embedding = np.array([0.95, 0.05, 0.0], dtype=np.float32)
        c = MemoryNode.episodic("evento gamma", run_id="r2")
        c.embedding = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        cog.add_node(a)
        cog.add_node(b)
        cog.add_node(c)
        cog.add_edge(GraphEdge.connect(a.id, b.id, EdgeKind.TEMPORAL_BEFORE))
        return cog

    def test_match_returns_results(self) -> None:
        cog = self._build_graph_with_embeddings()
        query_emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        results = cog.match(query_embedding=query_emb)
        assert len(results) > 0
        # O mais próximo (alpha) deve aparecer primeiro
        assert "alpha" in results[0].node.label

    def test_match_without_embedding_uses_plasticity(self) -> None:
        cog = self._build_graph_with_embeddings()
        results = cog.match()  # sem embedding → fallback puramente sináptico
        assert len(results) > 0

    def test_match_filters_by_kind(self) -> None:
        cog = self._build_graph_with_embeddings()
        # Adiciona synapse
        cog.add_node(
            SynapseNode.specialist("S", role="s", objective="o")
        )
        results = cog.match(node_kinds=[NodeKind.MEMORY])
        for r in results:
            assert r.node.kind == NodeKind.MEMORY


# ────────────────────────────────────────────────────────────────────────────
# CognitiveGraph integrado
# ────────────────────────────────────────────────────────────────────────────


class TestCognitiveGraphIntegration:
    def test_add_node_then_query(self) -> None:
        cog = CognitiveGraph()
        m = MemoryNode.episodic("test", run_id="r1")
        cog.add_node(m)
        assert cog.node_count == 1
        assert cog.get_node(m.id) is not None

    def test_add_edge_validates_endpoints(self) -> None:
        cog = CognitiveGraph()
        e = GraphEdge.connect("non_existent_a", "non_existent_b", EdgeKind.CAUSAL)
        with pytest.raises(KeyError):
            cog.add_edge(e)

    def test_iter_nodes_by_kind(self) -> None:
        cog = CognitiveGraph()
        cog.add_node(MemoryNode.episodic("m", run_id="r1"))
        cog.add_node(SynapseNode.specialist("s", role="s", objective="o"))
        memories = list(cog.iter_nodes(kind=NodeKind.MEMORY))
        synapses = list(cog.iter_nodes(kind=NodeKind.SYNAPSE))
        assert len(memories) == 1
        assert len(synapses) == 1

    def test_neighbors_via_typed_edges(self) -> None:
        cog = CognitiveGraph()
        m1 = MemoryNode.episodic("a", run_id="r1")
        m2 = MemoryNode.episodic("b", run_id="r1")
        cog.add_node(m1)
        cog.add_node(m2)
        cog.add_edge(GraphEdge.connect(m1.id, m2.id, EdgeKind.TEMPORAL_BEFORE))
        neighbors_temporal = list(
            cog.neighbors(m1.id, kinds=[EdgeKind.TEMPORAL_BEFORE])
        )
        neighbors_causal = list(
            cog.neighbors(m1.id, kinds=[EdgeKind.CAUSAL])
        )
        assert len(neighbors_temporal) == 1
        assert len(neighbors_causal) == 0

    def test_activation_increments_stats(self) -> None:
        cog = CognitiveGraph()
        s = SynapseNode.specialist("x", role="x", objective="y")
        cog.add_node(s)
        cog.activate(s.id)
        cog.activate(s.id)
        node = cog.get_node(s.id)
        assert node is not None
        assert node.stats.activations == 2

    def test_record_outcome_updates_weight(self) -> None:
        cog = CognitiveGraph()
        s = SynapseNode.specialist("x", role="x", objective="y")
        cog.add_node(s)
        cog.activate(s.id)
        cog.record_outcome(s.id, success=True)
        node = cog.get_node(s.id)
        assert node is not None
        assert node.weight > 0.5

    def test_persist_roundtrip(self) -> None:
        cog = CognitiveGraph()
        m = MemoryNode.episodic("evento de teste", run_id="r1")
        m.embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        m.add_tags("test", "persistence")
        cog.add_node(m)
        s = SynapseNode.specialist("S", role="critic", objective="o")
        cog.add_node(s)
        cog.add_edge(GraphEdge.connect(s.id, m.id, EdgeKind.MENTIONS))

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "g.msgpack"
            cog.persist(p)
            cog2 = CognitiveGraph.load(p)

        assert cog2.node_count == cog.node_count
        assert cog2.edge_count == cog.edge_count

        m2 = cog2.get_node(m.id)
        assert m2 is not None
        assert m2.label == m.label
        assert np.allclose(m2.embedding, m.embedding)
        assert m2.tags == m.tags

    def test_remove_node_cleans_edges(self) -> None:
        cog = CognitiveGraph()
        a = MemoryNode.episodic("a", run_id="r1")
        b = MemoryNode.episodic("b", run_id="r1")
        cog.add_node(a)
        cog.add_node(b)
        cog.add_edge(GraphEdge.connect(a.id, b.id, EdgeKind.TEMPORAL_BEFORE))
        assert cog.edge_count == 1
        cog.remove_node(a.id)
        assert cog.edge_count == 0
        assert cog.get_node(a.id) is None

    def test_sweep_decay_changes_status(self) -> None:
        cog = CognitiveGraph()
        # Nó muito antigo + tech_news → vai para archived
        ancient = MemoryNode(
            id="ancient",
            kind=NodeKind.MEMORY,
            label="old news",
            weight=0.3,
            domain="tech_news",
            bitemp=BiTemporal(
                window=ValidityWindow.open_at(
                    utc_now() - timedelta(days=10_000)
                )
            ),
        )
        cog.add_node(ancient)
        counters = cog.sweep_decay()
        node = cog.get_node("ancient")
        assert node is not None
        assert node.status in {NodeStatus.STALE, NodeStatus.ARCHIVED}
        assert counters["to_stale"] + counters["to_archived"] >= 1
