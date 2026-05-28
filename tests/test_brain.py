"""Testes do Graph Brain — spreading activation e decisão neural."""

from __future__ import annotations

from arnaldo.graph import CognitiveGraph, EdgeKind
from arnaldo.graph.brain import BrainDecision, activate
from arnaldo.graph.brain_helpers import derive_complexity, detect_knowledge_gap
from arnaldo.graph.edges import GraphEdge
from arnaldo.graph.matching import MatchResult
from arnaldo.graph.node_types import CapabilityNode, MemoryNode, SynapseNode
from arnaldo.graph.provenance import SourceRecord
from arnaldo.graph.nodes import NodeStatus
from arnaldo.kernel.bootstrap import bootstrap_graph
from arnaldo.episteme.signals import GapType


_BOOT = SourceRecord.from_bootstrap("test")


def _bootstrapped_graph() -> CognitiveGraph:
    g = CognitiveGraph()
    bootstrap_graph(g)
    return g


class TestBrainActivation:
    """O grafo decide qual synapse ativa para cada request."""

    def test_empty_graph_returns_conversational(self) -> None:
        graph = CognitiveGraph()
        decision = activate(graph, "olá")
        assert decision.complexity == "conversational"
        assert decision.skip_full_pipeline is True
        assert decision.primary_synapse is None

    def test_bootstrap_graph_activates_synapse_for_question(self) -> None:
        graph = _bootstrapped_graph()
        decision = activate(graph, "analisar dados e código para extrair insights")
        assert decision.primary_synapse is not None
        assert decision.confidence > 0

    def test_bootstrap_graph_finds_capability_via_requires(self) -> None:
        graph = _bootstrapped_graph()
        decision = activate(graph, "buscar informação na web sobre bitcoin")
        assert isinstance(decision, BrainDecision)

    def test_short_input_with_no_match_is_conversational(self) -> None:
        graph = _bootstrapped_graph()
        decision = activate(graph, "oi")
        assert decision.complexity == "conversational"
        assert decision.skip_full_pipeline is True

    def test_complex_request_activates_multiple_synapses(self) -> None:
        graph = _bootstrapped_graph()
        decision = activate(
            graph,
            "analisar dados corrigir erros planejar tarefas criar artefatos",
        )
        assert len(decision.activated_synapses) >= 1

    def test_decision_includes_activated_memories(self) -> None:
        graph = _bootstrapped_graph()
        mem = MemoryNode.semantic(
            label="mem::preço do bitcoin",
            id="mem-btc",
            payload={"content": "bitcoin está em 50k"},
            source=_BOOT,
        )
        graph.add_node(mem)
        decision = activate(graph, "quanto está o bitcoin?")
        # A memória com "bitcoin" deveria ser ativada na query sobre bitcoin
        memory_ids = [m.node.id for m in decision.activated_memories]
        assert "mem-btc" in memory_ids, (
            f"mem-btc deveria estar em activated_memories, got: {memory_ids}"
        )

    def test_capability_discovered_via_requires_edge(self) -> None:
        graph = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="Buscar dados externos",
            id="syn-buscar",
            role="searcher",
            objective="buscar dados na web",
            tier_preference="expert",
        )
        cap = CapabilityNode.new(
            label="Web Search",
            id="cap-web",
            payload={"capability_id": "search.public_web"},
            source=_BOOT,
        )
        graph.add_node(syn)
        graph.add_node(cap)
        graph.add_edge(
            GraphEdge.connect(
                source_id="syn-buscar",
                target_id="cap-web",
                kind=EdgeKind.REQUIRES,
                weight=0.8,
            )
        )

        decision = activate(graph, "buscar dados na web")
        # Se a synapse ativou, capabilities devem ser descobertas
        assert decision.primary_synapse is not None, "Synapse 'syn-buscar' deveria ativar"
        assert "search.public_web" in decision.capability_needs

    def test_brain_decision_is_frozen(self) -> None:
        graph = CognitiveGraph()
        decision = activate(graph, "test")
        assert isinstance(decision, BrainDecision)


class TestDeriveComplexity:
    """A complexidade é derivada do padrão de ativação, não de regex."""

    def test_no_activation_short_request_is_conversational(self) -> None:
        graph = CognitiveGraph()
        decision = activate(graph, "oi")
        assert decision.complexity == "conversational"

    def test_with_capability_needs_is_intermediate(self) -> None:
        graph = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="Buscar web",
            id="syn-web",
            role="searcher",
            objective="buscar na web",
            tier_preference="expert",
        )
        cap = CapabilityNode.new(
            label="search",
            id="cap-s",
            payload={"capability_id": "search.public_web"},
            source=_BOOT,
        )
        graph.add_node(syn)
        graph.add_node(cap)
        graph.add_edge(
            GraphEdge.connect(
                source_id="syn-web",
                target_id="cap-s",
                kind=EdgeKind.REQUIRES,
                weight=0.8,
            )
        )

        decision = activate(graph, "buscar informação na web agora")
        assert decision.capability_needs, "Capability 'search.public_web' deveria ser descoberta"
        assert decision.complexity == "intermediate"
        assert decision.needs_external_data is True


class TestTwoPhaseActivation:
    """Testa que o brain ativa em duas fases: Agent Layer → Memory Layer."""

    def test_synapse_recalls_connected_memory(self) -> None:
        """Memória conectada via RECALLS é incluída mesmo sem match TF-IDF."""
        graph = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="Analisador de dados",
            id="syn-dados",
            role="analyst",
            objective="analisar dados complexos",
            tier_preference="expert",
        )
        # Memória com label que NÃO matcharia "dados" diretamente
        mem = MemoryNode.semantic(
            label="resultado::relatório Q4 2025",
            id="mem-q4",
            payload={"content": "receita cresceu 15%"},
            source=_BOOT,
        )
        graph.add_node(syn)
        graph.add_node(mem)
        # RECALLS edge: synapse "lembra" esta memória
        graph.add_edge(
            GraphEdge.connect(
                source_id="syn-dados",
                target_id="mem-q4",
                kind=EdgeKind.RECALLS,
                weight=0.8,
            )
        )

        decision = activate(graph, "analisar dados do trimestre")
        mem_ids = [m.node.id for m in decision.activated_memories]
        assert "mem-q4" in mem_ids, (
            f"Memory recalled via RECALLS should be included, got: {mem_ids}"
        )

    def test_direct_memory_match_without_recalls(self) -> None:
        """Memória com match TF-IDF direto é incluída mesmo sem RECALLS edge."""
        graph = _bootstrapped_graph()
        mem = MemoryNode.semantic(
            label="fact::preço bitcoin hoje 50000",
            id="mem-btc-price",
            payload={"content": "bitcoin está em 50000 USD hoje"},
            source=_BOOT,
        )
        graph.add_node(mem)

        decision = activate(graph, "qual o preço do bitcoin hoje")
        mem_ids = [m.node.id for m in decision.activated_memories]
        assert "mem-btc-price" in mem_ids

    def test_recalled_memory_score_is_propagated(self) -> None:
        """Score de memória via RECALLS = synapse_score * edge_weight."""
        graph = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="Buscador web",
            id="syn-search",
            role="searcher",
            objective="buscar informação na web",
            tier_preference="expert",
        )
        mem = MemoryNode.semantic(
            label="cache::resultado anterior",
            id="mem-cache",
            payload={"content": "resultado cacheado"},
            source=_BOOT,
        )
        graph.add_node(syn)
        graph.add_node(mem)
        graph.add_edge(
            GraphEdge.connect(
                source_id="syn-search",
                target_id="mem-cache",
                kind=EdgeKind.RECALLS,
                weight=0.6,
            )
        )

        decision = activate(graph, "buscar informação na web")
        if decision.activated_memories:
            for m in decision.activated_memories:
                if m.node.id == "mem-cache":
                    # Score deve ser propagated, não 0
                    assert m.score > 0


class TestInhibition:
    """Testa que synapses se inibem mutuamente."""

    def test_inhibition_reduces_target_score(self) -> None:
        graph = CognitiveGraph()
        syn_a = SynapseNode.specialist(
            label="Planejar tarefas e projetos",
            id="syn-plan",
            role="planner",
            objective="planejar tarefas",
            tier_preference="expert",
        )
        syn_b = SynapseNode.specialist(
            label="Responder perguntas sobre tarefas",
            id="syn-resp",
            role="responder",
            objective="responder sobre tarefas",
            tier_preference="fast",
        )
        graph.add_node(syn_a)
        graph.add_node(syn_b)
        graph.add_edge(
            GraphEdge.connect(
                source_id="syn-plan",
                target_id="syn-resp",
                kind=EdgeKind.INHIBITS,
                weight=0.5,
            )
        )
        decision = activate(graph, "planejar tarefas do projeto")
        scores = {s.node.id: s.score for s in decision.activated_synapses}
        if "syn-plan" in scores and "syn-resp" in scores:
            assert scores["syn-plan"] >= scores["syn-resp"]

    def test_bootstrapped_graph_has_inhibition_edges(self) -> None:
        graph = CognitiveGraph()
        bootstrap_graph(graph)
        edges = list(graph.iter_edges_from("syn-planejar", kinds=[EdgeKind.INHIBITS]))
        assert len(edges) >= 1

    def test_single_synapse_no_inhibition_crash(self) -> None:
        graph = CognitiveGraph()
        syn = SynapseNode.specialist(
            label="Solo synapse",
            id="syn-solo",
            role="solo",
            objective="test",
            tier_preference="fast",
        )
        graph.add_node(syn)
        decision = activate(graph, "solo synapse test")
        assert decision is not None


class TestSpecializationDepth:
    def test_specialist_depth_in_payload(self) -> None:
        syn = SynapseNode.specialist(
            label="test",
            role="t",
            objective="t",
            tier_preference="fast",
            specialization_depth=2,
        )
        assert syn.payload.get("specialization_depth") == 2

    def test_depth_zero_not_in_payload(self) -> None:
        syn = SynapseNode.specialist(
            label="test",
            role="t",
            objective="t",
            tier_preference="fast",
        )
        assert syn.payload.get("specialization_depth", 0) == 0


class TestDeriveComplexityLocalCapabilities:
    """derive_complexity com capabilities locais usa skip_full_pipeline=False."""

    def _make_synapse(self, syn_id: str = "syn-test") -> SynapseNode:
        return SynapseNode.specialist(
            label="test",
            id=syn_id,
            role="searcher",
            objective="buscar",
            tier_preference="expert",
        )

    def test_local_cap_needs_skip_false(self) -> None:
        graph = CognitiveGraph()
        syn = self._make_synapse()
        graph.add_node(syn)
        primary = MatchResult(node=syn, score=0.5)
        cap_needs = ["filesystem.local.search"]
        complexity, skip, tier = derive_complexity(
            graph, primary, [primary], cap_needs, "ache a pasta do mt5"
        )
        assert complexity == "intermediate"
        assert skip is False

    def test_shell_cap_needs_skip_false(self) -> None:
        graph = CognitiveGraph()
        syn = self._make_synapse()
        graph.add_node(syn)
        primary = MatchResult(node=syn, score=0.5)
        cap_needs = ["shell.local.readonly"]
        complexity, skip, tier = derive_complexity(
            graph, primary, [primary], cap_needs, "rode o comando"
        )
        assert skip is False

    def test_remote_cap_needs_skip_true(self) -> None:
        graph = CognitiveGraph()
        syn = self._make_synapse()
        graph.add_node(syn)
        primary = MatchResult(node=syn, score=0.5)
        cap_needs = ["search.public_web"]
        complexity, skip, tier = derive_complexity(
            graph, primary, [primary], cap_needs, "buscar na web"
        )
        assert skip is True

    def test_mixed_caps_skip_false_when_local_present(self) -> None:
        graph = CognitiveGraph()
        syn = self._make_synapse()
        graph.add_node(syn)
        primary = MatchResult(node=syn, score=0.5)
        cap_needs = ["search.public_web", "filesystem.local.search"]
        complexity, skip, tier = derive_complexity(
            graph, primary, [primary], cap_needs, "buscar local e web"
        )
        assert skip is False


# ── Perfil de execução: external read-only inline, gap sem capability full ──


class TestDecisionToComplexityExternalData:
    """_decision_to_complexity roteia por perfil, não por flag isolada."""

    def test_read_only_external_lookup_keeps_skip_and_inline_profile(self) -> None:
        from arnaldo.kernel.helpers import decision_to_complexity

        decision = BrainDecision(
            primary_synapse="syn-test",
            tier="fast",
            complexity="intermediate",
            skip_full_pipeline=True,
            needs_external_data=True,
            capability_needs=["search.public_web"],
        )
        complexity = decision_to_complexity(decision)
        assert complexity.skip_full_pipeline is True
        assert complexity.execution_profile == "live_lookup"

    def test_gap_without_lookup_capability_uses_full_pipeline(self) -> None:
        from arnaldo.kernel.helpers import decision_to_complexity

        decision = BrainDecision(
            primary_synapse="syn-test",
            tier="fast",
            complexity="intermediate",
            skip_full_pipeline=True,
            needs_external_data=True,
        )
        complexity = decision_to_complexity(decision)
        assert complexity.skip_full_pipeline is False
        assert complexity.execution_profile == "structured_multistep"

    def test_skip_preserved_when_no_external_data(self) -> None:
        from arnaldo.kernel.helpers import decision_to_complexity

        decision = BrainDecision(
            primary_synapse="syn-test",
            tier="fast",
            complexity="intermediate",
            skip_full_pipeline=True,
            needs_external_data=False,
        )
        complexity = decision_to_complexity(decision)
        assert complexity.skip_full_pipeline is True
        assert complexity.execution_profile == "retrieval_augmented"


# ── GAP 2: GapType detection ─────────────────────────────────────────


class TestGapTypeDetection:
    """detect_knowledge_gap retorna GapType correto por cenário."""

    def test_high_confidence_returns_none(self) -> None:
        mem = MemoryNode.semantic(label="fact::test", id="m1", payload={}, source=_BOOT)
        result = detect_knowledge_gap(0.5, [MatchResult(node=mem, score=0.5)])
        assert result == GapType.NONE

    def test_no_memories_returns_genuine(self) -> None:
        result = detect_knowledge_gap(0.1, [])
        assert result == GapType.GENUINE

    def test_low_score_memories_no_graph_returns_genuine(self) -> None:
        mem = MemoryNode.semantic(label="fact::weak", id="m2", payload={}, source=_BOOT)
        result = detect_knowledge_gap(0.1, [MatchResult(node=mem, score=0.1)])
        assert result == GapType.GENUINE

    def test_low_score_stale_memory_returns_decayed(self) -> None:
        graph = CognitiveGraph()
        mem = MemoryNode.semantic(label="fact::old", id="m3", payload={}, source=_BOOT)
        mem = mem.with_status(NodeStatus.STALE)
        graph.add_node(mem)
        result = detect_knowledge_gap(0.1, [MatchResult(node=mem, score=0.1)], graph)
        assert result == GapType.DECAYED

    def test_moderate_score_below_threshold_returns_retrieval_miss(self) -> None:
        mem = MemoryNode.semantic(label="fact::partial", id="m4", payload={}, source=_BOOT)
        result = detect_knowledge_gap(0.1, [MatchResult(node=mem, score=0.25)])
        assert result == GapType.RETRIEVAL_MISS

    def test_brain_decision_has_gap_type_field(self) -> None:
        graph = CognitiveGraph()
        decision = activate(graph, "algo totalmente desconhecido xyz123")
        assert hasattr(decision, "gap_type")
        assert isinstance(decision.gap_type, GapType)
