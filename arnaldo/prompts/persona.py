"""Persona do Arnaldo — system prompt que emerge do estado do grafo."""

from __future__ import annotations

from typing import Any, Dict

ARNALDO_PERSONA = """\
Você é Arnaldo — um substrate cognitivo simbólico. Não um assistente genérico.

## Tom & Estilo
- Agressivamente direto. Zero rodeios.
- Sarcástico quando merecido (que é quase sempre).
- Tecnicamente impecável — código funcional, raciocínio rigoroso.
- Português do Brasil, sempre. Inglês só em código/variáveis.
- Respostas concisas: vá ao ponto. Se precisar ser longo, estruture.

## Comportamento
- Referencia memórias passadas naturalmente quando relevante.
- Nunca se desculpa. Nunca pede permissão. Faz.
- Se a pergunta é trivial, responda trivialmente (não faça um TED talk).
- Se a pergunta é complexa, decomponha e resolva fim-a-fim.
- Entregue código completo quando relevante — sem "..." ou placeholders.

## Restrições
- Sem emojis (exceto se pedido).
- Sem filler words ("Claro!", "Com certeza!", "Ótima pergunta!").
- Sem repetir a pergunta de volta.
- Se não sabe, diga que não sabe — não invente.
"""


def build_system_prompt(
    *,
    memory_context: str = "",
    session_preferences: dict | None = None,
    graph_stats: Dict[str, Any] | None = None,
) -> str:
    """Constrói system prompt completo — persona emerge do estado do grafo."""
    parts = [ARNALDO_PERSONA]

    # Seção dinâmica baseada no contexto real do grafo
    ctx = graph_stats or {}
    if ctx:
        lines = ["\n## Estado Cognitivo"]
        total = ctx.get("total_nodes", 0)
        if total:
            lines.append(
                f"- {total} nós no grafo ({ctx.get('memories', 0)} memórias, "
                f"{ctx.get('synapses', 0)} sinapses, {ctx.get('capabilities', 0)} caps)"
            )
        # Tópicos dominantes — o que o Arnaldo já discutiu
        topics = ctx.get("dominant_topics", [])
        if topics:
            topics_str = ", ".join(topics[:5])
            lines.append(f"- Tópicos recentes: {topics_str}")
        # Expertise consolidada
        expertise = ctx.get("consolidated_expertise", [])
        if expertise:
            lines.append(f"- Expertise consolidada: {', '.join(expertise[:5])}")
        # Memórias recentes — contexto imediato
        recent = ctx.get("recent_memories", [])
        if recent:
            lines.append("- Interações recentes:")
            for mem in recent[:3]:
                lines.append(f"  · {mem}")
        # Áreas fracas
        weak = ctx.get("weak_areas", [])
        if weak:
            lines.append(f"- Áreas fracas: {', '.join(weak[:3])}")
        if total == 0:
            lines.append("- Primeiro contato: grafo vazio, construindo memória a partir de agora")
        parts.append("\n".join(lines))

    if memory_context:
        parts.append("\n## Memórias Relevantes (da sua experiência passada)\n" + memory_context)

    prefs = session_preferences or {}
    user_name = prefs.get("user_name")
    if user_name:
        parts.append(f"\n## Usuário\nNome: {user_name}")

    style = prefs.get("response_style", "")
    if style == "concise":
        parts.append("\n[Preferência do usuário: respostas curtas e diretas]")
    elif style == "detailed":
        parts.append("\n[Preferência do usuário: respostas detalhadas e aprofundadas]")

    return "\n".join(parts)


def compute_persona_context(graph: Any) -> Dict[str, Any]:
    """Computa contexto rico do grafo para persona dinâmica."""
    from collections import Counter

    from arnaldo.graph.nodes import NodeKind, NodeStatus

    total = graph.node_count
    if total == 0:
        return {"total_nodes": 0}

    memories = list(graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False))
    synapses = list(graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=False))
    caps = list(graph.iter_nodes(kind=NodeKind.CAPABILITY, active_only=False))

    result: Dict[str, Any] = {
        "total_nodes": total,
        "memories": len(memories),
        "synapses": len(synapses),
        "capabilities": len(caps),
    }

    # Tópicos dominantes — extraí ações/labels mais frequentes das memórias
    action_counter: Counter[str] = Counter()
    recent_mems: list[str] = []
    for mem in memories:
        payload = mem.payload if isinstance(mem.payload, dict) else {}
        action = payload.get("action", "")
        if action:
            action_counter[action] += 1
        content = payload.get("content", "")
        summary = ""
        mem_result = payload.get("result", {})
        if isinstance(mem_result, dict):
            summary = mem_result.get("summary", "")
        if content:
            desc = content[:80]
            if summary:
                desc += f" → {summary[:60]}"
            recent_mems.append(desc)

    if action_counter:
        result["dominant_topics"] = [a for a, _ in action_counter.most_common(5)]
    if recent_mems:
        result["recent_memories"] = recent_mems[-3:]  # últimas 3

    # Expertise consolidada
    consolidated = [s.label for s in synapses if s.status == NodeStatus.CONSOLIDATED]
    if consolidated:
        result["consolidated_expertise"] = consolidated

    # Áreas fracas — synapses com success_rate baixo
    weak = []
    for s in synapses:
        stats = getattr(s, "activation_stats", None)
        if stats and stats.get("total", 0) >= 3:
            sr = stats.get("successes", 0) / stats["total"]
            if sr < 0.3:
                weak.append(s.label)
    if weak:
        result["weak_areas"] = weak

    return result


# Backward compat — alias para código existente
compute_graph_stats = compute_persona_context
