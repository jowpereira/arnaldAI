"""Fast-path, medium-path e síntese de resposta — bypass do pipeline pesado."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from arnaldo.contracts import RunResult, new_id, utc_now
from arnaldo.memory import MemoryRecord
from arnaldo.prompts import build_chat_messages
from arnaldo.prompts.context import build_synthesis_messages
from arnaldo.prompts.persona import compute_persona_context
from arnaldo.storage import RunStore

from .learning import apply_learning_to_graph, compute_reward, detect_implicit_feedback
from .retrieval import retrieve_for_request
from . import session as _session

logger = logging.getLogger("arnaldo.kernel")


def fast_response(
    *,
    request: str,
    session_id: str | None,
    autonomy: str,
    terms_accepted: bool | None,
    run_id: str,
    output_dir: Path,
    sessions: Any,
    memory: Any,
    llm_client: Any,
) -> RunResult:
    """Resposta rápida para requests conversacionais — 1 LLM call."""
    session = _session.open_session(sessions, session_id, autonomy, terms_accepted)
    retrieval = retrieve_for_request(memory.load_graph(), request)
    history = session.message_history if session.message_history else []

    feedback = detect_implicit_feedback(request)
    reward = compute_reward(feedback)
    extra_context = ""
    if feedback in ("negative", "correction"):
        extra_context = "\n[O usuário indicou insatisfação com a resposta anterior. Ajuste.]"

    messages = build_chat_messages(
        user_message=request + extra_context,
        memory_context=retrieval.summary_for_prompt(),
        message_history=history,
        session_preferences=session.learned_preferences,
        graph_stats=compute_persona_context(memory.load_graph()),
    )

    if not llm_client or not getattr(llm_client, "is_configured", False):
        raise RuntimeError("LLM não configurado — fast_response exige LLM ativo.")
    resp = llm_client.chat(tier="fast", messages=messages)
    response_text = resp.content

    # Learning real: aplica feedback ao grafo
    graph = memory.load_graph()
    activated = [m.get("id", "") for m in retrieval.relevant_memories if m.get("id")]
    activated += [s.get("id", "") for s in retrieval.relevant_synapses if s.get("id")]
    if activated:
        apply_learning_to_graph(graph, activated_node_ids=activated, feedback=feedback)

    # F0: Ingestão — toda conversa vira MemoryNode no grafo
    _remember_turn(memory, request, response_text, session.id)

    session = sessions.record_turn(session, request, response_text)
    store = RunStore(output_dir, run_id).create()
    store.write_text("response.md", response_text)
    store.write_json("learning.json", {"feedback": feedback, "reward": reward})
    return RunResult(
        run_id=run_id,
        run_dir=store.run_dir,
        files={},
        session_id=session.id,
        response=response_text,
    )


def medium_response(
    *,
    request: str,
    session_id: str | None,
    autonomy: str,
    terms_accepted: bool | None,
    run_id: str,
    output_dir: Path,
    sessions: Any,
    memory: Any,
    llm_client: Any,
    suggested_tier: str = "fast",
) -> RunResult:
    """Resposta intermediária — retrieval + routing + learning + 1 LLM call.

    Mais inteligente que fast_response (usa grafo, routing, spawning),
    mais rápido que pipeline completo (1 LLM call ao invés de 15 steps).
    """
    session = _session.open_session(sessions, session_id, autonomy, terms_accepted)
    graph = memory.load_graph()
    history = session.message_history if session.message_history else []

    # 1) Retrieval — agora com TF-IDF fallback real
    retrieval = retrieve_for_request(graph, request)

    # 2) Routing — seleciona synapses relevantes (código que era dead)
    routing_context = _route_synapses(graph, request, retrieval)

    # 3) Spawning — detecta padrões recorrentes e cria novas sinapses
    _try_spawn(graph, history, request, run_id=run_id)

    # 4) Feedback implícito da mensagem anterior
    feedback = detect_implicit_feedback(request)
    reward = compute_reward(feedback)

    # 5) Monta contexto enriquecido para LLM
    memory_context = retrieval.summary_for_prompt()
    if routing_context:
        memory_context += f"\n\n{routing_context}"

    extra_context = ""
    if feedback in ("negative", "correction"):
        extra_context = "\n[O usuário indicou insatisfação com a resposta anterior. Ajuste.]"

    messages = build_chat_messages(
        user_message=request + extra_context,
        memory_context=memory_context,
        message_history=history,
        session_preferences=session.learned_preferences,
        graph_stats=compute_persona_context(graph),
    )

    # 6) LLM call com tier sugerido pela classificação
    tier = suggested_tier if suggested_tier in ("fast", "expert", "god", "codex") else "fast"
    if not llm_client or not getattr(llm_client, "is_configured", False):
        raise RuntimeError("LLM não configurado — medium_response exige LLM ativo.")
    resp = llm_client.chat(tier=tier, messages=messages)
    response_text = resp.content

    # 7) Learning real — aplica feedback ao grafo
    activated = [m.get("id", "") for m in retrieval.relevant_memories if m.get("id")]
    activated += [s.get("id", "") for s in retrieval.relevant_synapses if s.get("id")]
    if activated:
        apply_learning_to_graph(graph, activated_node_ids=activated, feedback=feedback)

    # 8) Ingestão — toda conversa vira MemoryNode no grafo
    _remember_turn(memory, request, response_text, session.id)

    session = sessions.record_turn(session, request, response_text)
    store = RunStore(output_dir, run_id).create()
    store.write_text("response.md", response_text)
    store.write_json(
        "learning.json",
        {
            "feedback": feedback,
            "reward": reward,
            "path": "medium",
            "retrieval_hits": len(retrieval.match_results),
            "activated_nodes": len(activated),
        },
    )
    return RunResult(
        run_id=run_id,
        run_dir=store.run_dir,
        files={},
        session_id=session.id,
        response=response_text,
    )


def synthesize_response(runtime_result: Any, request: str, llm_client: Any) -> str:
    """Sintetiza resposta textual a partir dos step_results."""
    steps = list(runtime_result.step_results)
    if not steps:
        return "Execução concluída sem resultados de steps."

    # Com LLM: síntese inteligente
    if llm_client and getattr(llm_client, "is_configured", False):
        messages = build_synthesis_messages(
            step_results=steps,
            original_request=request,
        )
        resp = llm_client.chat(tier="fast", messages=messages)
        return resp.content

    # Sem LLM: concatenação direta dos outputs
    parts: list[str] = []
    for step in steps:
        output = step.get("output", step.get("summary", ""))
        if isinstance(output, dict):
            output = str(output.get("summary", output.get("content", str(output))))
        if output:
            parts.append(str(output)[:500])
    return "\n\n".join(parts) if parts else "Execução concluída."


# ── Helpers internos para medium path ────────────────────────────────


def _remember_turn(memory: Any, request: str, response: str, session_id: str) -> None:
    """Ingere interação como MemoryNode — o grafo cresce a cada conversa."""
    record = MemoryRecord(
        id=new_id("memory"),
        kind="episodic",
        payload={
            "action": "conversa",
            "content": request[:500],
            "result": {"summary": response[:500]},
            "session_id": session_id,
            "timestamp": utc_now(),
        },
    )
    try:
        memory.append(record)
    except Exception as exc:
        logger.warning("falha ao ingerir memória: %s", exc)


def _route_synapses(graph: Any, request: str, retrieval: Any) -> str:
    """Seleciona synapses via routing real — wires dead code into pipeline."""
    from arnaldo.graph.execution.routing import select_synapses_for_request

    try:
        selected = select_synapses_for_request(graph, request)
        if not selected:
            return ""
        parts = []
        for syn in selected[:3]:
            label = getattr(syn, "label", str(syn))
            parts.append(f"- Synapse ativada: {label}")
        return "Rotas cognitivas:\n" + "\n".join(parts)
    except Exception as exc:
        logger.warning("routing falhou: %s", exc)
        return ""


def _try_spawn(graph: Any, history: list[dict[str, Any]], request: str, *, run_id: str) -> None:
    """Tenta spawn de novas sinapses a partir de padrões recorrentes."""
    from arnaldo.graph.execution.spawning import try_spawn_from_history
    from arnaldo.graph.nodes import NodeKind

    messages = [msg for msg in history[-6:] if isinstance(msg, dict) and msg.get("content")]
    if not messages:
        return

    existing_ids = {n.id for n in graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=False)}
    try:
        new_synapses = try_spawn_from_history(messages, existing_ids, run_id=run_id)
        for syn in new_synapses:
            graph.add_node(syn)
            logger.info("synapse spawned: %s", syn.label)
    except Exception as exc:
        logger.warning("spawning falhou: %s", exc)
