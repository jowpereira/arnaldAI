"""Modelos de dados e utilitários para o MemoryStore."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable

from arnaldo.graph import utc_now


@dataclass
class MemoryRecord:
    id: str
    kind: str
    payload: Dict[str, Any]


@dataclass(slots=True)
class MemorySynapseCandidate:
    source_memory_id: str
    target_memory_id: str
    source_signature: str = ""
    target_signature: str = ""
    support: int = 0
    greedy_score: float = 0.0
    successes: int = 0
    failures: int = 0
    materialized_synapse_id: str | None = None
    last_seen_at: datetime = field(default_factory=utc_now)

    @property
    def success_rate(self) -> float:
        """Laplace-smoothed success rate: (s+1)/(s+f+2)."""
        return (self.successes + 1) / (self.successes + self.failures + 2)

    @property
    def key(self) -> str:
        source = self.source_signature or self.source_memory_id
        target = self.target_signature or self.target_memory_id
        return f"{source}->{target}"

    @property
    def is_materialized(self) -> bool:
        return bool(self.materialized_synapse_id)

    def register_observation(self, *, reward: float, at: datetime | None = None) -> None:
        self.support += 1
        alpha = 1.0 / float(self.support)
        clipped = max(0.0, min(1.0, float(reward)))
        self.greedy_score = ((1.0 - alpha) * self.greedy_score) + (alpha * clipped)
        # Classificação Bayesiana: reward > 0.5 = sucesso, < 0.5 = falha
        if clipped > 0.5:
            self.successes += 1
        elif clipped < 0.5:
            self.failures += 1
        self.last_seen_at = at or utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_memory_id": self.source_memory_id,
            "target_memory_id": self.target_memory_id,
            "source_signature": self.source_signature,
            "target_signature": self.target_signature,
            "support": self.support,
            "greedy_score": self.greedy_score,
            "successes": self.successes,
            "failures": self.failures,
            "materialized_synapse_id": self.materialized_synapse_id,
            "last_seen_at": self.last_seen_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MemorySynapseCandidate:
        materialized_raw = payload.get("materialized_synapse_id")
        materialized = None
        if materialized_raw is not None:
            normalized = str(materialized_raw).strip()
            if normalized and normalized.lower() not in {"none", "null"}:
                materialized = normalized
        source_memory_id = str(payload.get("source_memory_id", "")).strip()
        target_memory_id = str(payload.get("target_memory_id", "")).strip()
        source_signature = str(payload.get("source_signature", "")).strip()
        target_signature = str(payload.get("target_signature", "")).strip()
        return cls(
            source_memory_id=source_memory_id,
            target_memory_id=target_memory_id,
            source_signature=source_signature or source_memory_id,
            target_signature=target_signature or target_memory_id,
            support=max(0, int(payload.get("support", 0))),
            greedy_score=max(0.0, min(1.0, float(payload.get("greedy_score", 0.0)))),
            successes=max(0, int(payload.get("successes", 0))),
            failures=max(0, int(payload.get("failures", 0))),
            materialized_synapse_id=materialized,
            last_seen_at=parse_dt(payload.get("last_seen_at")),
        )


def tokenize_payload(payload: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    queue: list[Any] = [payload]
    while queue:
        item = queue.pop()
        if isinstance(item, dict):
            queue.extend(item.values())
            continue
        if isinstance(item, (list, tuple, set)):
            queue.extend(item)
            continue
        if isinstance(item, str):
            for token in re.findall(r"[a-zA-Z0-9_]{3,}", item.lower()):
                tokens.add(token)
    return tokens


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / float(len(union))


def memory_synapse_id(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"synmem_{digest}"


def association_signature(payload: dict[str, Any], *, default: str) -> str:
    action = str(payload.get("action", "")).strip().lower()
    capability_id = str(payload.get("capability_id", "")).strip().lower()
    agent_id = str(payload.get("agent_id", "")).strip().lower()
    record_kind = str(payload.get("record_kind", "")).strip().lower()
    if action:
        return "|".join(
            [
                record_kind or "memory",
                action,
                capability_id or "-",
                agent_id or "-",
            ]
        )
    summary = str(payload.get("summary", "")).strip().lower()
    if summary:
        summary_tokens = re.findall(r"[a-z0-9_]{3,}", summary)
        if summary_tokens:
            return "|".join([record_kind or "memory", "summary", "_".join(summary_tokens[:6])])
    return str(default).strip() or "memory"


def parse_dt(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return utc_now()
    return utc_now()
