"""Plasticidade pós-run — feedback Hebbian e consolidação de status."""

from __future__ import annotations

from typing import Any, Dict, List

from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
    NodeKind,
    NodeStatus,
    SynapseNode,
)


def apply_post_run_plasticity(
    graph: CognitiveGraph,
    *,
    step_results: List[Dict[str, Any]],
    run_success: bool,
) -> Dict[str, Any]:
    """Aplica feedback Hebbian pós-run no grafo de execução.

    Para cada synapse executada, registra outcome baseado no resultado do step.
    Depois consolida status de synapses com evidência suficiente.
    """
    updated_synapses = 0
    consolidated = 0
    inhibits_created = 0

    for result in step_results:
        node_id = str(result.get("node_id", "")).strip()
        if not node_id:
            continue
        node = graph.get_node(node_id)
        if not isinstance(node, SynapseNode):
            continue

        step_success = bool(result.get("success", False))
        # Registra outcome no nó
        graph.record_outcome(node_id, success=step_success)
        updated_synapses += 1

        # Se falhou 3+ vezes, cria INHIBITS de nós upstream
        if not step_success:
            fail_count = _count_failures(node)
            if fail_count >= 3:
                inhibits_created += _create_inhibits_edges(graph, node_id)

    # Consolida status das synapses com evidência suficiente
    consolidated = _consolidate_synapse_status(graph)

    # Aplica feedback global (run-level)
    if run_success:
        _reinforce_path_edges(graph, step_results)

    return {
        "updated_synapses": updated_synapses,
        "consolidated": consolidated,
        "inhibits_created": inhibits_created,
        "run_success": run_success,
    }


def _count_failures(node: SynapseNode) -> int:
    """Conta falhas no payload do nó."""
    payload = node.payload if isinstance(node.payload, dict) else {}
    return int(payload.get("failures", 0))


def _create_inhibits_edges(graph: CognitiveGraph, failed_node_id: str) -> int:
    """Cria edges INHIBITS de nós que ativam o nó falhado."""
    created = 0
    for edge in graph.iter_edges_to(failed_node_id, kinds=[EdgeKind.ACTIVATES]):
        existing = list(
            e
            for e in graph.iter_edges_from(edge.source_id, kinds=[EdgeKind.INHIBITS])
            if e.target_id == failed_node_id
        )
        if not existing:
            graph.add_edge(
                source_id=edge.source_id,
                target_id=failed_node_id,
                kind=EdgeKind.INHIBITS,
                weight=0.30,
            )
            created += 1
    return created


def _consolidate_synapse_status(graph: CognitiveGraph) -> int:
    """Consolida status de synapses baseado em evidência acumulada.

    - ACTIVE com 10+ ativações e success_rate > 0.8 → CONSOLIDATED
    - ACTIVE com success_rate < 0.2 após 5+ ativações → ARCHIVED
    """
    consolidated = 0
    for node in graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=False):
        if not isinstance(node, SynapseNode):
            continue
        payload = node.payload if isinstance(node.payload, dict) else {}
        activations = int(payload.get("activations", 0))
        successes = int(payload.get("successes", 0))
        failures = int(payload.get("failures", 0))
        total = successes + failures
        if total == 0:
            continue

        success_rate = successes / total
        if node.status == NodeStatus.ACTIVE and activations >= 10 and success_rate > 0.8:
            node.status = NodeStatus.CONSOLIDATED
            consolidated += 1
        elif node.status == NodeStatus.ACTIVE and total >= 5 and success_rate < 0.2:
            node.status = NodeStatus.ARCHIVED
            consolidated += 1

    return consolidated


def _reinforce_path_edges(
    graph: CognitiveGraph,
    step_results: List[Dict[str, Any]],
) -> None:
    """Reforça edges ACTIVATES no caminho de execução bem-sucedido."""
    executed_ids = [
        str(r.get("node_id", "")).strip() for r in step_results if r.get("success", False)
    ]
    for i in range(len(executed_ids) - 1):
        src, tgt = executed_ids[i], executed_ids[i + 1]
        for edge in graph.iter_edges_from(src, kinds=[EdgeKind.ACTIVATES]):
            if edge.target_id == tgt:
                graph.record_outcome(src, success=True)
                break
