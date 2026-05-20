from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
import hashlib
import json
import re

from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
    GraphEdge,
    MemoryNode,
    NodeKind,
    SourceRecord,
    SynapseNode,
    utc_now,
)


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
    materialized_synapse_id: str | None = None
    last_seen_at: datetime = field(default_factory=utc_now)

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
        self.last_seen_at = at or utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_memory_id": self.source_memory_id,
            "target_memory_id": self.target_memory_id,
            "source_signature": self.source_signature,
            "target_signature": self.target_signature,
            "support": self.support,
            "greedy_score": self.greedy_score,
            "materialized_synapse_id": self.materialized_synapse_id,
            "last_seen_at": self.last_seen_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemorySynapseCandidate":
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
            materialized_synapse_id=materialized,
            last_seen_at=_parse_dt(payload.get("last_seen_at")),
        )


class MemoryStore:
    """Persist records e materializa uma rede de memórias/sinapses.

    O store mantém dois planos em paralelo:
    1. Ledger append-only em JSONL (compatibilidade e auditoria).
    2. Grafo cognitivo incremental (``memory-graph.msgpack``), onde memórias
       viram ``MemoryNode`` e associações recorrentes viram ``SynapseNode``.
    """

    def __init__(
        self,
        base_dir: Path = Path("storage/memory"),
        *,
        association_window: int = 6,
        materialize_support_threshold: int = 2,
        materialize_score_threshold: float = 0.45,
    ) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.graph_path = self.base_dir / "memory-graph.msgpack"
        self.candidates_path = self.base_dir / "synapse-candidates.json"
        self.association_window = max(2, int(association_window))
        self.materialize_support_threshold = max(1, int(materialize_support_threshold))
        self.materialize_score_threshold = max(0.0, min(1.0, float(materialize_score_threshold)))
        self._graph = self._load_graph()
        self._candidates = self._load_candidates()

    def append(self, record: MemoryRecord) -> None:
        target = self.base_dir / f"{record.kind}.jsonl"
        with target.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "id": record.id,
                        "kind": record.kind,
                        "payload": record.payload,
                    },
                    ensure_ascii=True,
                )
            )
            handle.write("\n")
        self._ingest_record_to_graph(record)
        self._persist_graph_state()

    def load(self, kind: str) -> List[Dict[str, Any]]:
        target = self.base_dir / f"{kind}.jsonl"
        if not target.exists():
            return []
        return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line]

    def load_graph(self) -> CognitiveGraph:
        return self._graph

    def memory_synapses(self, *, limit: int = 20) -> list[dict[str, Any]]:
        ranked = sorted(
            self._candidates.values(),
            key=lambda item: (item.is_materialized, item.greedy_score, item.support),
            reverse=True,
        )
        return [item.to_dict() for item in ranked[: max(1, int(limit))]]

    def record_feedback(
        self,
        *,
        source_memory_id: str,
        target_memory_id: str,
        reward: float,
    ) -> None:
        source = str(source_memory_id).strip()
        target = str(target_memory_id).strip()
        if not source or not target or source == target:
            return
        source_signature = source
        target_signature = target
        source_node = self._graph.get_node(source)
        if isinstance(source_node, MemoryNode) and isinstance(source_node.payload, dict):
            source_signature = _association_signature(source_node.payload, fallback=source)
        target_node = self._graph.get_node(target)
        if isinstance(target_node, MemoryNode) and isinstance(target_node.payload, dict):
            target_signature = _association_signature(target_node.payload, fallback=target)
        candidate = self._candidates.get(f"{source_signature}->{target_signature}")
        if candidate is None:
            candidate = self._candidates.get(f"{source}->{target}")
        if candidate is None:
            candidate = MemorySynapseCandidate(
                source_memory_id=source,
                target_memory_id=target,
                source_signature=source_signature,
                target_signature=target_signature,
            )
            self._candidates[candidate.key] = candidate
        candidate.source_memory_id = source
        candidate.target_memory_id = target
        candidate.register_observation(reward=reward)
        self._materialize_candidates()
        self._persist_graph_state()

    def build_workflow_hints(self, *, goal: str, limit: int = 12) -> dict[str, Any]:
        """Extrai preferências de workflow a partir da rede de memória.

        A saída é usada pelo runtime para reforçar transições dinâmicas:
        - ``preferred_actions``: ações com melhor evidência histórica.
        - ``transitions``: pares source->target com score agregado.
        """
        goal_tokens = _tokenize_payload({"goal": goal or ""})
        action_scores: dict[str, float] = defaultdict(float)
        action_counts: dict[str, int] = defaultdict(int)

        memory_by_id = {
            node.id: node
            for node in self._graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False)
        }
        for node_id, node in memory_by_id.items():
            payload = node.payload if isinstance(node.payload, dict) else {}
            action = str(payload.get("action", "")).strip()
            if not action:
                continue
            base = 1.0
            overlap = _jaccard(goal_tokens, _tokenize_payload(payload))
            if overlap > 0.0:
                base += min(1.0, overlap * 2.0)
            action_scores[action] += base
            action_counts[action] += 1

        transition_scores: dict[tuple[str, str], float] = defaultdict(float)
        for edge in self._graph.iter_edges(active_only=False):
            if edge.kind not in {EdgeKind.TEMPORAL_BEFORE, EdgeKind.SEMANTIC, EdgeKind.ACTIVATES}:
                continue
            source = memory_by_id.get(edge.source_id)
            target = memory_by_id.get(edge.target_id)
            if source is None or target is None:
                continue
            source_payload = source.payload if isinstance(source.payload, dict) else {}
            target_payload = target.payload if isinstance(target.payload, dict) else {}
            source_action = str(source_payload.get("action", "")).strip()
            target_action = str(target_payload.get("action", "")).strip()
            if not source_action or not target_action or source_action == target_action:
                continue
            weight = max(0.05, min(1.0, float(edge.weight)))
            key = (source_action, target_action)
            transition_scores[key] += weight

        ranked_actions = sorted(
            action_scores.items(),
            key=lambda item: (item[1], action_counts[item[0]]),
            reverse=True,
        )[: max(1, int(limit))]
        preferred_actions = [item[0] for item in ranked_actions]

        ranked_transitions = sorted(
            transition_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )[: max(1, int(limit))]
        transitions = [
            {
                "source_action": source_action,
                "target_action": target_action,
                "score": round(score, 6),
            }
            for (source_action, target_action), score in ranked_transitions
        ]

        return {
            "preferred_actions": preferred_actions,
            "action_scores": [
                {
                    "action": action,
                    "score": round(score, 6),
                    "count": int(action_counts.get(action, 0)),
                }
                for action, score in ranked_actions
            ],
            "transitions": transitions,
            "candidate_synapses": self.memory_synapses(limit=max(3, int(limit // 2) or 3)),
        }

    # ── Grafo de memória ──────────────────────────────────────────────────

    def _ingest_record_to_graph(self, record: MemoryRecord) -> None:
        node = self._to_memory_node(record)
        self._graph.add_node(node)
        related = self._related_memories(node_id=node.id, payload=node.payload)
        target_signature = _association_signature(node.payload, fallback=node.id)
        for source_id, reward in related:
            source_node = self._graph.get_node(source_id)
            source_payload = source_node.payload if isinstance(source_node, MemoryNode) and isinstance(source_node.payload, dict) else {}
            source_signature = _association_signature(source_payload, fallback=source_id)
            candidate = self._upsert_candidate(
                source_id=source_id,
                target_id=node.id,
                source_signature=source_signature,
                target_signature=target_signature,
                reward=reward,
            )
            self._ensure_memory_transition(source_id=source_id, target_id=node.id, weight=reward)
            if candidate.is_materialized:
                self._refresh_materialized_synapse(candidate)
        self._materialize_candidates()

    def _to_memory_node(self, record: MemoryRecord) -> MemoryNode:
        record_id = str(record.id).strip()
        if not record_id:
            digest = hashlib.sha1(json.dumps(record.payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
            record_id = f"memory_{digest}"
        payload = dict(record.payload or {})
        payload["record_kind"] = record.kind
        payload.setdefault("record_id", record_id)
        label = self._build_label(record.kind, payload)
        domain = self._domain_for_record(record.kind, payload)

        if record.kind == "episodic":
            run_id = str(payload.get("run_id") or payload.get("session_id") or "memory_run").strip()
            return MemoryNode.episodic(
                label=label,
                id=record_id,
                run_id=run_id,
                payload=payload,
                domain=domain,
            )

        source = self._source_for_payload(payload)
        if record.kind == "procedural":
            pattern = str(payload.get("pattern") or payload.get("action") or label).strip()
            return MemoryNode.procedural(
                label=label,
                id=record_id,
                pattern=pattern,
                payload=payload,
                source=source,
                domain=domain,
            )

        return MemoryNode.semantic(
            label=label,
            id=record_id,
            payload=payload,
            source=source,
            domain=domain,
        )

    def _related_memories(self, *, node_id: str, payload: dict[str, Any]) -> list[tuple[str, float]]:
        run_id = str(payload.get("run_id", "")).strip()
        session_id = str(payload.get("session_id", "")).strip()
        action = str(payload.get("action", "")).strip()
        capability_id = str(payload.get("capability_id", "")).strip()
        tokens = _tokenize_payload(payload)
        scored: list[tuple[str, float, datetime]] = []
        for node in self._graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False):
            if node.id == node_id:
                continue
            node_payload = node.payload if isinstance(node.payload, dict) else {}
            score = 0.0
            node_run_id = str(node_payload.get("run_id", "")).strip()
            node_session_id = str(node_payload.get("session_id", "")).strip()
            node_action = str(node_payload.get("action", "")).strip()
            node_capability = str(node_payload.get("capability_id", "")).strip()

            if run_id and node_run_id == run_id:
                score += 0.45
            if session_id and node_session_id == session_id:
                score += 0.35
            if action and node_action and action == node_action:
                score += 0.15
            if capability_id and node_capability and capability_id == node_capability:
                score += 0.15

            overlap = _jaccard(tokens, _tokenize_payload(node_payload))
            if overlap > 0.0:
                score += min(0.4, overlap)
            if score <= 0.0:
                continue
            scored.append((node.id, min(1.0, score), node.bitemp.recorded_at))

        scored.sort(key=lambda item: (item[1], item[2]), reverse=True)
        top = scored[: self.association_window]
        return [(source_id, reward) for source_id, reward, _ in top]

    def _upsert_candidate(
        self,
        *,
        source_id: str,
        target_id: str,
        source_signature: str,
        target_signature: str,
        reward: float,
    ) -> MemorySynapseCandidate:
        key = f"{source_signature}->{target_signature}"
        candidate = self._candidates.get(key)
        if candidate is None:
            candidate = MemorySynapseCandidate(
                source_memory_id=source_id,
                target_memory_id=target_id,
                source_signature=source_signature,
                target_signature=target_signature,
            )
            self._candidates[key] = candidate
        else:
            candidate.source_memory_id = source_id
            candidate.target_memory_id = target_id
            if source_signature:
                candidate.source_signature = source_signature
            if target_signature:
                candidate.target_signature = target_signature
        candidate.register_observation(reward=reward)
        return candidate

    def _materialize_candidates(self) -> None:
        for candidate in self._candidates.values():
            if candidate.support < self.materialize_support_threshold:
                continue
            if candidate.greedy_score < self.materialize_score_threshold:
                continue
            if candidate.is_materialized:
                self._refresh_materialized_synapse(candidate)
                continue
            if not (self._graph.has_node(candidate.source_memory_id) and self._graph.has_node(candidate.target_memory_id)):
                continue
            synapse_id = _memory_synapse_id(candidate.key)
            synapse = SynapseNode.specialist(
                label=(
                    "memory_association::%s->%s"
                    % (candidate.source_signature or candidate.source_memory_id, candidate.target_signature or candidate.target_memory_id)
                ),
                id=synapse_id,
                role="memory_associator",
                objective="ativar memória relacionada com base em coocorrência recorrente",
                epistemic_style="associative_retrieval",
                tier_preference="fast",
                action="memory_association",
                source_memory_id=candidate.source_memory_id,
                target_memory_id=candidate.target_memory_id,
                source_signature=candidate.source_signature or candidate.source_memory_id,
                target_signature=candidate.target_signature or candidate.target_memory_id,
                support=candidate.support,
                greedy_score=round(candidate.greedy_score, 6),
            )
            self._graph.add_node(synapse)
            self._ensure_edge(
                source_id=candidate.source_memory_id,
                target_id=synapse_id,
                kind=EdgeKind.ACTIVATES,
                weight=min(0.95, 0.5 + (0.08 * candidate.support)),
            )
            self._ensure_edge(
                source_id=synapse_id,
                target_id=candidate.target_memory_id,
                kind=EdgeKind.MENTIONS,
                weight=min(0.95, 0.5 + (0.3 * candidate.greedy_score)),
            )
            candidate.materialized_synapse_id = synapse_id

    def _refresh_materialized_synapse(self, candidate: MemorySynapseCandidate) -> None:
        synapse_id = str(candidate.materialized_synapse_id or "").strip()
        if not synapse_id:
            return
        node = self._graph.get_node(synapse_id)
        if not isinstance(node, SynapseNode):
            candidate.materialized_synapse_id = None
            return
        updated = node.with_payload_merge(
            support=candidate.support,
            greedy_score=round(candidate.greedy_score, 6),
            source_memory_id=candidate.source_memory_id,
            target_memory_id=candidate.target_memory_id,
            source_signature=candidate.source_signature or candidate.source_memory_id,
            target_signature=candidate.target_signature or candidate.target_memory_id,
        )
        assert isinstance(updated, SynapseNode)
        self._graph.add_node(updated)
        self._ensure_edge(
            source_id=candidate.source_memory_id,
            target_id=synapse_id,
            kind=EdgeKind.ACTIVATES,
            weight=min(0.95, 0.5 + (0.08 * candidate.support)),
        )
        self._ensure_edge(
            source_id=synapse_id,
            target_id=candidate.target_memory_id,
            kind=EdgeKind.MENTIONS,
            weight=min(0.95, 0.5 + (0.3 * candidate.greedy_score)),
        )

    def _ensure_memory_transition(self, *, source_id: str, target_id: str, weight: float) -> None:
        self._ensure_edge(
            source_id=source_id,
            target_id=target_id,
            kind=EdgeKind.TEMPORAL_BEFORE,
            weight=min(0.95, 0.35 + (0.45 * max(0.0, min(1.0, weight)))),
        )

    def _ensure_edge(self, *, source_id: str, target_id: str, kind: EdgeKind, weight: float) -> None:
        if not (self._graph.has_node(source_id) and self._graph.has_node(target_id)):
            return
        for edge in self._graph.iter_edges_from(source_id, kinds=[kind], active_only=False):
            if edge.target_id == target_id:
                return
        self._graph.add_edge(
            GraphEdge.connect(
                source_id=source_id,
                target_id=target_id,
                kind=kind,
                weight=max(0.0, min(1.0, float(weight))),
            )
        )

    # ── Persistência interna ──────────────────────────────────────────────

    def _load_graph(self) -> CognitiveGraph:
        if self.graph_path.exists():
            try:
                return CognitiveGraph.load(self.graph_path)
            except (ValueError, OSError):
                pass
        return CognitiveGraph()

    def _load_candidates(self) -> dict[str, MemorySynapseCandidate]:
        if not self.candidates_path.exists():
            return {}
        try:
            raw = json.loads(self.candidates_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, list):
            return {}
        candidates: dict[str, MemorySynapseCandidate] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            candidate = MemorySynapseCandidate.from_dict(item)
            if not candidate.source_memory_id or not candidate.target_memory_id:
                continue
            candidates[candidate.key] = candidate
        return candidates

    def _persist_graph_state(self) -> None:
        self._graph.persist(self.graph_path)
        serialized = [candidate.to_dict() for candidate in sorted(self._candidates.values(), key=lambda c: c.key)]
        self.candidates_path.write_text(
            json.dumps(serialized, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _source_for_payload(payload: dict[str, Any]) -> SourceRecord:
        run_id = str(payload.get("run_id", "")).strip()
        session_id = str(payload.get("session_id", "")).strip()
        if run_id:
            agent_id = str(payload.get("agent_id", "")).strip()
            if agent_id:
                return SourceRecord.from_run(run_id, agent=agent_id)
            return SourceRecord.from_run(run_id)
        if session_id:
            return SourceRecord.from_user(session_id)
        return SourceRecord.from_bootstrap("memory.store")

    @staticmethod
    def _build_label(kind: str, payload: dict[str, Any]) -> str:
        for key in ("summary", "statement", "goal", "action", "step_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return f"{kind}::{value.strip()[:180]}"
        return f"{kind}::memory_record"

    @staticmethod
    def _domain_for_record(kind: str, payload: dict[str, Any]) -> str:
        if kind == "episodic":
            return "episodic"
        if kind == "procedural":
            return "procedural"
        base = str(payload.get("domain", "")).strip()
        return base or "semantic_stable"


def _tokenize_payload(payload: dict[str, Any]) -> set[str]:
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


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / float(len(union))


def _memory_synapse_id(key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"synmem_{digest}"


def _association_signature(payload: dict[str, Any], *, fallback: str) -> str:
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
    return str(fallback).strip() or "memory"


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return utc_now()
    return utc_now()
