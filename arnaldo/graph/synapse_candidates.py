"""Candidatos a synapse derivados de padrões de execução repetidos.

Rastreia padrões de execução e materializa SynapseNodes quando evidência
suficiente é acumulada — Laplace-smoothed success rate como critério.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from arnaldo.graph import utc_now

if TYPE_CHECKING:
    from arnaldo.graph.store import CognitiveGraph


@dataclass(slots=True)
class ExecutionSynapseCandidate:
    """Candidato a synapse derivado de padrões de execução repetidos."""

    pattern_key: str  # ex: "intent.compile::plan_project"
    role: str  # papel observado (do step result)
    objective: str  # objetivo observado
    observation_count: int = 0
    successes: int = 0
    failures: int = 0
    last_seen_at: datetime = field(default_factory=utc_now)
    materialized_node_id: str | None = None

    @property
    def candidate_id(self) -> str:
        digest = hashlib.sha256(self.pattern_key.encode()).hexdigest()[:12]
        return f"exec_syn_{digest}"

    @property
    def success_rate(self) -> float:
        """Laplace-smoothed: (s+1)/(s+f+2)."""
        return (self.successes + 1) / (self.successes + self.failures + 2)

    @property
    def is_materialized(self) -> bool:
        return bool(self.materialized_node_id)

    def record_observation(self, *, success: bool) -> None:
        self.observation_count += 1
        if success:
            self.successes += 1
        else:
            self.failures += 1
        self.last_seen_at = utc_now()

    def should_materialize(
        self,
        *,
        min_observations: int = 5,
        min_success_rate: float = 0.7,
    ) -> bool:
        return (
            not self.is_materialized
            and self.observation_count >= min_observations
            and self.success_rate >= min_success_rate
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_key": self.pattern_key,
            "role": self.role,
            "objective": self.objective,
            "observation_count": self.observation_count,
            "successes": self.successes,
            "failures": self.failures,
            "last_seen_at": self.last_seen_at.isoformat(),
            "materialized_node_id": self.materialized_node_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionSynapseCandidate:
        raw_dt = data.get("last_seen_at", "")
        if isinstance(raw_dt, str) and raw_dt:
            dt = datetime.fromisoformat(raw_dt)
        else:
            dt = utc_now()
        return cls(
            pattern_key=str(data.get("pattern_key", "")),
            role=str(data.get("role", "")),
            objective=str(data.get("objective", "")),
            observation_count=int(data.get("observation_count", 0)),
            successes=int(data.get("successes", 0)),
            failures=int(data.get("failures", 0)),
            last_seen_at=dt,
            materialized_node_id=data.get("materialized_node_id"),
        )


class ExecutionSynapseTracker:
    """Rastreia candidatos de execução e materializa quando evidência suficiente."""

    def __init__(self) -> None:
        self._candidates: dict[str, ExecutionSynapseCandidate] = {}

    def observe(
        self,
        *,
        pattern_key: str,
        role: str,
        objective: str,
        success: bool,
    ) -> ExecutionSynapseCandidate:
        """Registra observação de execução. Cria candidato se novo."""
        if pattern_key not in self._candidates:
            self._candidates[pattern_key] = ExecutionSynapseCandidate(
                pattern_key=pattern_key,
                role=role,
                objective=objective,
            )
        candidate = self._candidates[pattern_key]
        candidate.record_observation(success=success)
        return candidate

    def ready_to_materialize(self, **kwargs: Any) -> list[ExecutionSynapseCandidate]:
        """Retorna candidatos prontos para materialização."""
        return [c for c in self._candidates.values() if c.should_materialize(**kwargs)]

    def materialize(self, candidate: ExecutionSynapseCandidate, graph: CognitiveGraph) -> str:
        """Materializa candidato como SynapseNode no grafo."""
        from arnaldo.graph.node_types import SynapseNode
        from arnaldo.graph.provenance import SourceKind, SourceRecord

        node = SynapseNode.specialist(
            label=f"synapse::{candidate.pattern_key}",
            role=candidate.role,
            objective=candidate.objective,
            id=candidate.candidate_id,
            source=SourceRecord(
                kind=SourceKind.INFERENCE,
                identifier="execution.synapse.tracker",
                confidence=min(0.90, candidate.success_rate),
            ),
        )
        graph.add_node(node)
        candidate.materialized_node_id = node.id
        return node.id

    @property
    def candidates(self) -> dict[str, ExecutionSynapseCandidate]:
        return dict(self._candidates)
