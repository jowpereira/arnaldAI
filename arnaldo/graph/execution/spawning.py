"""Synapse spawning — criação automática de synapses para padrões recorrentes."""

from __future__ import annotations

from typing import Any, Dict, List

from ..edges import GraphEdge
from ..nodes import NodeKind, SynapseNode
from ..provenance import SourceRecord


def detect_recurring_pattern(
    message_history: List[Dict[str, Any]],
    *,
    min_occurrences: int = 2,
    window: int = 20,
) -> List[Dict[str, Any]]:
    """Detecta padrões recorrentes no histórico de mensagens.

    Padrão = intent que aparece >= min_occurrences vezes no window.
    Retorna lista de padrões candidatos a virar synapses.
    """
    from ..intent import classify_intent

    recent = message_history[-window:]
    user_messages = [m for m in recent if m.get("role") == "user"]

    # Conta intents
    intent_counts: Dict[str, int] = {}
    intent_examples: Dict[str, List[str]] = {}
    for msg in user_messages:
        content = str(msg.get("content", ""))
        intent = classify_intent(content)
        intent_counts[intent] = intent_counts.get(intent, 0) + 1
        if intent not in intent_examples:
            intent_examples[intent] = []
        if len(intent_examples[intent]) < 3:
            intent_examples[intent].append(content[:100])

    patterns = []
    for intent, count in intent_counts.items():
        if count >= min_occurrences and intent != "default":
            patterns.append(
                {
                    "intent": intent,
                    "count": count,
                    "examples": intent_examples[intent],
                }
            )

    return patterns


def spawn_synapse_for_pattern(
    pattern: Dict[str, Any],
    *,
    run_id: str,
) -> tuple[SynapseNode, GraphEdge | None]:
    """Cria SynapseNode especializado para um padrão recorrente.

    Returns:
        Tuple (novo_synapse, edge_activates_opcional)
    """
    intent = pattern["intent"]
    examples = pattern.get("examples", [])

    source = SourceRecord.from_run(run_id, agent="synapse_spawner")

    synapse = SynapseNode(
        id=f"spawned-{intent}-{run_id[:8]}",
        kind=NodeKind.SYNAPSE,
        label=f"Synapse especializado: {intent}",
        source=source,
        weight=0.4,  # Nasce com peso moderado (scaffolded)
        payload={
            "action": f"handle_{intent}",
            "spawned": True,
            "pattern_intent": intent,
            "examples": examples,
            "tier_preference": "fast",
        },
    )

    return synapse, None


def try_spawn_from_history(
    message_history: List[Dict[str, Any]],
    existing_synapse_ids: set[str],
    *,
    run_id: str,
) -> List[SynapseNode]:
    """Tenta criar novos synapses baseado no histórico.

    Só cria se não existir synapse com mesmo pattern_intent.
    """
    patterns = detect_recurring_pattern(message_history)
    new_synapses: List[SynapseNode] = []

    for pattern in patterns:
        intent = pattern["intent"]
        expected_id = f"spawned-{intent}-{run_id[:8]}"

        # Não duplica
        if expected_id in existing_synapse_ids:
            continue

        # Verifica se já existe synapse para este intent
        has_existing = any(f"spawned-{intent}" in sid for sid in existing_synapse_ids)
        if has_existing:
            continue

        synapse, _ = spawn_synapse_for_pattern(pattern, run_id=run_id)
        new_synapses.append(synapse)

    return new_synapses
