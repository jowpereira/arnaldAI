"""MemoryStore — persistência e retrieval de memórias com grafo cognitivo."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List
import json

from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
    NodeKind,
    utc_now,
)

from .models import (
    MemoryRecord,
    MemorySynapseCandidate,
    association_signature,
    jaccard,
    tokenize_payload,
)
from .graph_bridge import ingest_record_to_graph


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
        graph: CognitiveGraph | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.graph_path = self.base_dir / "memory-graph.msgpack"
        self.candidates_path = self.base_dir / "synapse-candidates.json"
        self.association_window = max(2, int(association_window))
        self.materialize_support_threshold = max(1, int(materialize_support_threshold))
        self.materialize_score_threshold = max(0.0, min(1.0, float(materialize_score_threshold)))
        self._graph = graph if graph is not None else self._load_graph()
        self._candidates = self._load_candidates()

    def bind_graph(self, graph: CognitiveGraph) -> None:
        """Vincula grafo externo (unificado) ao store, eliminando grafo separado."""
        self._graph = graph

    def append(self, record: MemoryRecord) -> None:
        target = self.base_dir / f"{record.kind}.jsonl"
        with target.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"id": record.id, "kind": record.kind, "payload": record.payload},
                    ensure_ascii=True,
                )
            )
            handle.write("\n")
        ingest_record_to_graph(
            self._graph,
            self._candidates,
            record,
            association_window=self.association_window,
            materialize_support_threshold=self.materialize_support_threshold,
            materialize_score_threshold=self.materialize_score_threshold,
        )
        self._persist_graph_state()

    def load(self, kind: str) -> List[Dict[str, Any]]:
        target = self.base_dir / f"{kind}.jsonl"
        if not target.exists():
            return []
        return [
            json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line
        ]

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
        from arnaldo.graph import MemoryNode

        source_signature = source
        target_signature = target
        source_node = self._graph.get_node(source)
        if isinstance(source_node, MemoryNode) and isinstance(source_node.payload, dict):
            source_signature = association_signature(source_node.payload, fallback=source)
        target_node = self._graph.get_node(target)
        if isinstance(target_node, MemoryNode) and isinstance(target_node.payload, dict):
            target_signature = association_signature(target_node.payload, fallback=target)
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
        from .graph_bridge import materialize_candidates

        materialize_candidates(
            self._graph,
            self._candidates,
            support_threshold=self.materialize_support_threshold,
            score_threshold=self.materialize_score_threshold,
        )
        self._persist_graph_state()

    def build_workflow_hints(self, *, goal: str, limit: int = 12) -> dict[str, Any]:
        """Extrai preferências de workflow a partir da rede de memória."""
        goal_tokens = tokenize_payload({"goal": goal or ""})
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
            overlap = jaccard(goal_tokens, tokenize_payload(payload))
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
            transition_scores[(source_action, target_action)] += weight

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
            {"source_action": sa, "target_action": ta, "score": round(sc, 6)}
            for (sa, ta), sc in ranked_transitions
        ]

        return {
            "preferred_actions": preferred_actions,
            "action_scores": [
                {"action": a, "score": round(s, 6), "count": int(action_counts.get(a, 0))}
                for a, s in ranked_actions
            ],
            "transitions": transitions,
            "candidate_synapses": self.memory_synapses(limit=max(3, int(limit // 2) or 3)),
        }

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
        serialized = [
            candidate.to_dict()
            for candidate in sorted(self._candidates.values(), key=lambda c: c.key)
        ]
        self.candidates_path.write_text(
            json.dumps(serialized, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
