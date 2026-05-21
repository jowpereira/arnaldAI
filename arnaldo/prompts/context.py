"""Context builder — monta messages[] para chamadas LLM."""

from __future__ import annotations

from typing import Any, Dict, List

from .persona import build_system_prompt


def build_chat_messages(
    *,
    user_message: str,
    memory_context: str = "",
    message_history: List[Dict[str, Any]] | None = None,
    session_preferences: Dict[str, Any] | None = None,
    graph_stats: Dict[str, Any] | None = None,
    max_history: int = 20,
) -> List[Dict[str, str]]:
    """Constrói lista de messages para Azure OpenAI chat completion.

    Estrutura:
    1. system prompt (persona + memory + graph_stats + preferences)
    2. message history (últimos N turnos)
    3. user message atual
    """
    system = build_system_prompt(
        memory_context=memory_context,
        session_preferences=session_preferences,
        graph_stats=graph_stats,
    )
    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]

    # Histórico de conversa (mantém contexto multi-turn)
    history = message_history or []
    if history:
        for msg in history[-max_history:]:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            if role in ("user", "assistant") and content.strip():
                messages.append({"role": role, "content": content})

    # Mensagem atual
    messages.append({"role": "user", "content": user_message})
    return messages


def build_synthesis_messages(
    *,
    step_results: List[Dict[str, Any]],
    original_request: str,
    memory_context: str = "",
) -> List[Dict[str, str]]:
    """Constrói messages para sintetizar resposta textual a partir de step_results."""
    synthesis_prompt = (
        """\
Sintetize uma resposta textual coerente a partir dos resultados abaixo.
A resposta deve ser natural, direta e em português do Brasil.
Não mencione "steps" ou "pipeline" — fale como se fosse UMA resposta integrada.

Pedido original: %s
"""
        % original_request
    )

    # Compila resultados dos steps
    step_lines: list[str] = []
    for idx, step in enumerate(step_results, 1):
        output = step.get("output", step.get("summary", ""))
        if isinstance(output, dict):
            output = str(output.get("summary", output.get("content", str(output))))
        status = "OK" if step.get("success", True) else "FALHOU"
        step_lines.append(f"[Step {idx} ({status})]: {str(output)[:500]}")

    content = synthesis_prompt + "\n\n" + "\n".join(step_lines)

    return [
        {"role": "system", "content": "Você sintetiza resultados em texto fluido e direto."},
        {"role": "user", "content": content},
    ]
