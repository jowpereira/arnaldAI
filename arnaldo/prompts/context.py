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
        output = _extract_step_content(step)
        status = "OK" if step.get("success", True) else "FALHOU"
        step_lines.append(f"[Step {idx} ({status})]: {str(output)[:500]}")

    content = synthesis_prompt + "\n\n" + "\n".join(step_lines)

    return [
        {"role": "system", "content": "Você sintetiza resultados em texto fluido e direto."},
        {"role": "user", "content": content},
    ]


def _extract_step_content(step: Dict[str, Any]) -> str:
    """Extrai conteúdo textual real de um step — nunca usa nome de deliverable."""
    result = step.get("result")
    if isinstance(result, dict) and result:
        for key in ("summary", "content"):
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        sections = result.get("sections")
        if isinstance(sections, list) and sections:
            first = sections[0]
            if isinstance(first, dict):
                return str(first.get("content", first.get("summary", str(first))))
            if isinstance(first, str) and first.strip():
                return first
        return str(result)
    if isinstance(result, str) and result.strip():
        return result.strip()
    summary = step.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    # Fallback: output, mas rejeita nomes de deliverable conhecidos
    output = step.get("output", "")
    if isinstance(output, dict):
        return str(output.get("summary", output.get("content", str(output))))
    output_str = str(output)
    if output_str in _KNOWN_DELIVERABLE_IDS:
        return ""
    return output_str


# IDs de deliverable que NUNCA devem vazar para resposta ao usuário
_KNOWN_DELIVERABLE_IDS = frozenset(
    {
        "primary_artifact",
        "execution_evidence",
        "next_actions",
        "draft_artifact",
        "critic_review",
        "risk_review",
        "decision_synthesis",
    }
)
