"""Learning loop — sinais implícitos de qualidade e feedback adaptativo."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List

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
    activated_node_ids: List[str],
    feedback: str,
    reward: float | None = None,
) -> int:
    """Aplica aprendizado real ao grafo — plasticidade Hebbian de verdade.

    Chama record_outcome() nos nós ativados durante a resposta,
    conectando o loop de feedback à plasticidade do grafo.

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
        except (KeyError, ValueError):
            continue

    return updated


def extract_quality_signals(
    message_history: List[Dict[str, Any]],
    *,
    window: int = 4,
) -> Dict[str, Any]:
    """Extrai sinais de qualidade dos últimos turnos.

    Analisa as mensagens do user depois de cada assistant response
    para inferir se o user ficou satisfeito.
    """
    recent = message_history[-window:] if message_history else []
    signals: List[Dict[str, Any]] = []
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
