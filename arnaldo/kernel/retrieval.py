"""Retrieval pré-compilação — consulta grafo cognitivo antes de compilar tarefa."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from arnaldo.graph import CognitiveGraph, EdgeKind, NodeKind
from arnaldo.graph.matching import HybridMatcher, MatchResult


@dataclass(slots=True)
class RetrievalResult:
    """Contexto recuperado do grafo para informar compilação e decisão."""

    relevant_memories: List[Dict[str, Any]] = field(default_factory=list)
    relevant_synapses: List[Dict[str, Any]] = field(default_factory=list)
    relevant_capabilities: List[Dict[str, Any]] = field(default_factory=list)
    match_results: List[MatchResult] = field(default_factory=list)
    inhibited_synapses: List[str] = field(default_factory=list)

    @property
    def has_context(self) -> bool:
        return bool(self.relevant_memories or self.relevant_synapses)

    def summary_for_prompt(self, max_items: int = 5) -> str:
        """Gera resumo textual para injeção em prompts LLM."""
        lines: list[str] = []
        for mem in self.relevant_memories[:max_items]:
            action = mem.get("action", "")
            content = mem.get("content", "")
            summary = mem.get("summary", mem.get("result_summary", ""))
            # Inclui conteúdo real da memória, não só action/summary
            if content:
                lines.append(f"- [{action}] {content[:200]}")
                if summary:
                    lines.append(f"  Resultado: {summary[:200]}")
            elif summary:
                lines.append(f"- [{action}] {summary[:200]}")
        for syn in self.relevant_synapses[:max_items]:
            label = syn.get("label", syn.get("id", ""))
            action = syn.get("action", "")
            status = syn.get("status", "")
            lines.append(f"- synapse: {label} (action={action}, status={status})")
        if self.inhibited_synapses:
            lines.append(f"- INIBIDOS: {', '.join(self.inhibited_synapses[:3])}")
        return "\n".join(lines)


def retrieve_for_request(
    graph: CognitiveGraph,
    request: str,
    *,
    max_results: int = 10,
) -> RetrievalResult:
    """Executa retrieval híbrido no grafo cognitivo para uma request."""
    result = RetrievalResult()
    if graph.node_count == 0:
        return result

    matcher = HybridMatcher(max_results=max_results)
    try:
        matches = matcher.retrieve(graph, query=request)
    except Exception:
        matches = []
    result.match_results = matches

    from arnaldo.graph.nodes import MemoryNode, SynapseNode, CapabilityNode

    for match in matches:
        node = match.node
        payload = node.payload if isinstance(node.payload, dict) else {}
        entry = {
            "id": node.id,
            "score": round(match.score, 4),
            "status": node.status.value if hasattr(node.status, "value") else str(node.status),
        }
        if isinstance(node, MemoryNode):
            entry["action"] = str(payload.get("action", ""))
            entry["content"] = str(payload.get("content", ""))[:200]
            entry["summary"] = str(payload.get("result", {}).get("summary", ""))[:200]
            result.relevant_memories.append(entry)
        elif isinstance(node, SynapseNode):
            entry["action"] = str(payload.get("action", ""))
            entry["label"] = str(node.label)
            result.relevant_synapses.append(entry)
        elif isinstance(node, CapabilityNode):
            entry["maturity"] = str(payload.get("maturity", ""))
            result.relevant_capabilities.append(entry)

    # Coleta synapses inibidos (INHIBITS com peso alto)
    for node in graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=True):
        for edge in graph.iter_edges_from(node.id, kinds=[EdgeKind.INHIBITS]):
            if edge.weight >= 0.5:
                result.inhibited_synapses.append(edge.target_id)

    return result
