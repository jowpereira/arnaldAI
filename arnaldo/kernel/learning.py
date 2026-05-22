"""Learning loop — sinais implícitos de qualidade e feedback adaptativo."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from arnaldo.graph.edges import EdgeKind
from arnaldo.graph.edge_ops import ensure_edge

logger = logging.getLogger("arnaldo.kernel.learning")

if TYPE_CHECKING:
    from arnaldo.graph.store import CognitiveGraph


# Padrões que indicam feedback positivo implícito
_POSITIVE_PATTERNS = re.compile(
    r"\b(obrigado|valeu|perfeito|excelente|ótimo|show|isso|exato|"
    r"massa|top|thanks|great|perfect|nice)\b",
    re.IGNORECASE,
)

# Padrões que indicam feedback negativo implícito
_NEGATIVE_PATTERNS = re.compile(
    r"\b(errado|incorreto|não era isso|wrong|nope|falhou|ruim|"
    r"péssimo|horrível|isso não|tá errado|não funciona|"
    r"tenta de novo|refaz|corrige)\b",
    re.IGNORECASE,
)

# Padrões que indicam correção explícita
_CORRECTION_PATTERNS = re.compile(
    r"\b(na verdade|actually|mas eu quis dizer|eu quis|quero dizer|"
    r"não, eu|na real|correto seria)\b",
    re.IGNORECASE,
)


def detect_implicit_feedback(message: str) -> str:
    """Detecta sinal de qualidade implícito na mensagem do usuário.

    Returns:
        "positive" | "negative" | "correction" | "neutral"
    """
    if not message or not message.strip():
        return "neutral"

    text = message.strip()

    if _CORRECTION_PATTERNS.search(text):
        return "correction"
    if _NEGATIVE_PATTERNS.search(text):
        return "negative"
    if _POSITIVE_PATTERNS.search(text):
        return "positive"
    return "neutral"


def compute_reward(feedback: str) -> float:
    """Converte feedback em reward numérico para plasticidade."""
    rewards = {
        "positive": 0.8,
        "neutral": 0.5,
        "negative": 0.1,
        "correction": 0.15,
    }
    return rewards.get(feedback, 0.5)


def apply_learning_to_graph(
    graph: CognitiveGraph,
    *,
    activated_node_ids: list[str],
    feedback: str,
    reward: float | None = None,
    synapse_ids: list[str] | None = None,
    memory_ids: list[str] | None = None,
) -> int:
    """Aplica aprendizado real ao grafo — plasticidade Hebbian de verdade.

    Chama record_outcome() nos nós ativados durante a resposta,
    conectando o loop de feedback à plasticidade do grafo.
    Se synapse_ids e memory_ids são fornecidos, cria edges ACTIVATES
    cross-layer entre synapses e memórias co-ativadas.

    Returns:
        Número de nós atualizados.
    """
    if not activated_node_ids:
        return 0

    effective_reward = reward if reward is not None else compute_reward(feedback)
    success = effective_reward >= 0.5
    updated = 0

    for node_id in activated_node_ids:
        node = graph.get_node(node_id)
        if node is None:
            continue
        try:
            graph.record_outcome(node_id, success=success)
            updated += 1
        except (KeyError, ValueError) as exc:
            logger.warning("record_outcome failed for %s: %s", node_id, exc)
            continue

    # Cross-layer: synapses ACTIVATES memórias co-ativadas
    if synapse_ids and memory_ids and success:
        _link_synapses_to_memories(graph, synapse_ids, memory_ids, effective_reward)

    return updated


# Limitar produto cartesiano a O(25) max
_MAX_CROSS_LINKS_PER_AXIS = 5


def _link_synapses_to_memories(
    graph: CognitiveGraph,
    synapse_ids: list[str],
    memory_ids: list[str],
    reward: float,
) -> None:
    """Cria/reforça arestas RECALLS entre synapses e memórias co-ativadas.

    Quando uma synapse e uma memória são ativadas juntas com sucesso,
    o link entre elas se fortalece — plasticidade Hebbian cross-layer.
    RECALLS desambigua: ACTIVATES = syn→syn, RECALLS = syn→mem.
    """
    weight = min(0.85, 0.2 + (0.4 * reward))
    for syn_id in synapse_ids[:_MAX_CROSS_LINKS_PER_AXIS]:
        if not graph.has_node(syn_id):
            continue
        for mem_id in memory_ids[:_MAX_CROSS_LINKS_PER_AXIS]:
            ensure_edge(
                graph,
                source_id=syn_id,
                target_id=mem_id,
                kind=EdgeKind.RECALLS,
                weight=weight,
            )


def extract_quality_signals(
    message_history: list[dict[str, Any]],
    *,
    window: int = 4,
) -> dict[str, Any]:
    """Extrai sinais de qualidade dos últimos turnos.

    Analisa as mensagens do user depois de cada assistant response
    para inferir se o user ficou satisfeito.
    """
    recent = message_history[-window:] if message_history else []
    signals: list[dict[str, Any]] = []
    total_reward = 0.0
    count = 0

    for i, msg in enumerate(recent):
        if msg.get("role") != "user":
            continue
        feedback = detect_implicit_feedback(str(msg.get("content", "")))
        reward = compute_reward(feedback)
        signals.append({"index": i, "feedback": feedback, "reward": reward})
        total_reward += reward
        count += 1

    avg_reward = total_reward / max(count, 1)
    return {
        "signals": signals,
        "avg_reward": round(avg_reward, 3),
        "trend": "positive" if avg_reward > 0.6 else "negative" if avg_reward < 0.4 else "neutral",
    }
