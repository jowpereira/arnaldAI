"""Testes de ExecutionSynapseCandidate e ExecutionSynapseTracker."""

from __future__ import annotations

from arnaldo.graph import CognitiveGraph
from arnaldo.graph.synapse_candidates import (
    ExecutionSynapseCandidate,
    ExecutionSynapseTracker,
)


# ────────────────────────────────────────────────────────────────────────────
# ExecutionSynapseCandidate
# ────────────────────────────────────────────────────────────────────────────


class TestExecutionSynapseCandidate:
    def test_candidate_id_deterministic(self) -> None:
        c = ExecutionSynapseCandidate(
            pattern_key="intent.compile::plan", role="planner", objective="planeja"
        )
        assert c.candidate_id.startswith("exec_syn_")
        assert c.candidate_id == c.candidate_id  # determinístico

    def test_success_rate_laplace(self) -> None:
        """3/4 successes → (3+1)/(3+1+2) = 4/6 ≈ 0.667."""
        c = ExecutionSynapseCandidate(
            pattern_key="x",
            role="r",
            objective="o",
            successes=3,
            failures=1,
        )
        assert abs(c.success_rate - (4 / 6)) < 1e-6

    def test_record_observation_increments(self) -> None:
        c = ExecutionSynapseCandidate(pattern_key="x", role="r", objective="o")
        c.record_observation(success=True)
        assert c.observation_count == 1
        assert c.successes == 1
        assert c.failures == 0
        c.record_observation(success=False)
        assert c.observation_count == 2
        assert c.failures == 1

    def test_should_materialize_threshold(self) -> None:
        """5 obs, taxa >= 0.7 → True."""
        c = ExecutionSynapseCandidate(
            pattern_key="x",
            role="r",
            objective="o",
            observation_count=5,
            successes=4,
            failures=1,
        )
        # success_rate = (4+1)/(4+1+2) = 5/7 ≈ 0.714
        assert c.should_materialize(min_observations=5, min_success_rate=0.7)

    def test_should_materialize_too_few(self) -> None:
        """3 obs → False (mínimo 5)."""
        c = ExecutionSynapseCandidate(
            pattern_key="x",
            role="r",
            objective="o",
            observation_count=3,
            successes=3,
            failures=0,
        )
        assert not c.should_materialize(min_observations=5)

    def test_should_materialize_already_materialized(self) -> None:
        c = ExecutionSynapseCandidate(
            pattern_key="x",
            role="r",
            objective="o",
            observation_count=10,
            successes=9,
            failures=1,
            materialized_node_id="some_id",
        )
        assert not c.should_materialize()

    def test_to_dict_roundtrip(self) -> None:
        c = ExecutionSynapseCandidate(
            pattern_key="a::b",
            role="critic",
            objective="criticar",
            observation_count=3,
            successes=2,
            failures=1,
        )
        d = c.to_dict()
        restored = ExecutionSynapseCandidate.from_dict(d)
        assert restored.pattern_key == c.pattern_key
        assert restored.successes == c.successes
        assert restored.failures == c.failures

    def test_is_materialized_false_by_default(self) -> None:
        c = ExecutionSynapseCandidate(pattern_key="x", role="r", objective="o")
        assert not c.is_materialized


# ────────────────────────────────────────────────────────────────────────────
# ExecutionSynapseTracker
# ────────────────────────────────────────────────────────────────────────────


class TestExecutionSynapseTracker:
    def test_observe_creates_candidate(self) -> None:
        tracker = ExecutionSynapseTracker()
        c = tracker.observe(
            pattern_key="intent.compile::plan",
            role="planner",
            objective="planeja projeto",
            success=True,
        )
        assert c.observation_count == 1
        assert c.successes == 1
        assert "intent.compile::plan" in tracker.candidates

    def test_observe_increments_existing(self) -> None:
        tracker = ExecutionSynapseTracker()
        tracker.observe(pattern_key="k", role="r", objective="o", success=True)
        tracker.observe(pattern_key="k", role="r", objective="o", success=False)
        c = tracker.candidates["k"]
        assert c.observation_count == 2
        assert c.successes == 1
        assert c.failures == 1

    def test_ready_to_materialize_filters(self) -> None:
        tracker = ExecutionSynapseTracker()
        # Candidato pronto: 6 obs, 5 successos
        for _ in range(5):
            tracker.observe(pattern_key="ready", role="r", objective="o", success=True)
        tracker.observe(pattern_key="ready", role="r", objective="o", success=False)
        # Candidato não pronto: 2 obs
        tracker.observe(pattern_key="not_ready", role="r", objective="o", success=True)
        tracker.observe(pattern_key="not_ready", role="r", objective="o", success=True)

        ready = tracker.ready_to_materialize(min_observations=5, min_success_rate=0.7)
        assert len(ready) == 1
        assert ready[0].pattern_key == "ready"

    def test_materialize_creates_synapse_node(self) -> None:
        graph = CognitiveGraph()
        tracker = ExecutionSynapseTracker()
        for _ in range(5):
            tracker.observe(pattern_key="mat", role="builder", objective="constrói", success=True)
        candidate = tracker.candidates["mat"]
        node_id = tracker.materialize(candidate, graph)
        assert graph.has_node(node_id)
        node = graph.get_node(node_id)
        assert node is not None
        assert node.kind.value == "synapse"

    def test_materialize_marks_candidate(self) -> None:
        graph = CognitiveGraph()
        tracker = ExecutionSynapseTracker()
        for _ in range(5):
            tracker.observe(pattern_key="mat2", role="r", objective="o", success=True)
        candidate = tracker.candidates["mat2"]
        node_id = tracker.materialize(candidate, graph)
        assert candidate.is_materialized
        assert candidate.materialized_node_id == node_id
