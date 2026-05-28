"""Fast-path, medium-path e síntese de resposta — bypass do pipeline pesado."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

from arnaldo.capabilities import CapabilityExecutor
from arnaldo.capabilities.semantics import summarize_capability_ids
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

    # Learning real: aplica feedback ao grafo com cross-links
    graph = memory.load_graph()
    mem_ids = [m.get("id", "") for m in retrieval.relevant_memories if m.get("id")]
    syn_ids = [s.get("id", "") for s in retrieval.relevant_synapses if s.get("id")]
    activated = mem_ids + syn_ids
    if activated:
        apply_learning_to_graph(
            graph,
            activated_node_ids=activated,
            feedback=feedback,
            synapse_ids=syn_ids,
            memory_ids=mem_ids,
        )

    # F0: Ingestão — toda conversa vira MemoryNode no grafo
    _remember_turn(memory, request, response_text, session.id)

    session = sessions.record_turn(session, request, response_text)
    store = RunStore(output_dir, run_id).create()
    response_path = store.write_text("response.md", response_text)
    learning_path = store.write_json("learning.json", {"feedback": feedback, "reward": reward})
    return RunResult(
        run_id=run_id,
        run_dir=store.run_dir,
        files={
            "response": response_path,
            "learning": learning_path,
        },
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

    # 1) Retrieval — agora com TF-IDF real
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

    # 7) Learning real — aplica feedback ao grafo com cross-links
    mem_ids = [m.get("id", "") for m in retrieval.relevant_memories if m.get("id")]
    syn_ids = [s.get("id", "") for s in retrieval.relevant_synapses if s.get("id")]
    activated = mem_ids + syn_ids
    if activated:
        apply_learning_to_graph(
            graph,
            activated_node_ids=activated,
            feedback=feedback,
            synapse_ids=syn_ids,
            memory_ids=mem_ids,
        )

    # 8) Ingestão — toda conversa vira MemoryNode no grafo
    _remember_turn(memory, request, response_text, session.id)

    session = sessions.record_turn(session, request, response_text)
    store = RunStore(output_dir, run_id).create()
    response_path = store.write_text("response.md", response_text)
    learning_path = store.write_json(
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
        files={
            "response": response_path,
            "learning": learning_path,
        },
        session_id=session.id,
        response=response_text,
    )


def inline_capability_response(
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
    capability_ids: list[str],
    suggested_tier: str = "expert",
    strict_on_llm_failure: bool = False,
) -> RunResult:
    """Resposta curta com capabilities read-only executadas inline."""
    session = _session.open_session(sessions, session_id, autonomy, terms_accepted)
    graph = memory.load_graph()
    history = session.message_history if session.message_history else []
    retrieval = retrieve_for_request(graph, request)

    feedback = detect_implicit_feedback(request)
    reward = compute_reward(feedback)

    inline_payloads, inline_context = _collect_inline_capability_results(
        request=request,
        capability_ids=capability_ids,
        message_history=history,
    )

    memory_context = retrieval.summary_for_prompt()
    if inline_context:
        memory_context = (
            f"{memory_context}\n\n{inline_context}" if memory_context else inline_context
        )

    extra_context = (
        "\n[Use os resultados reais de capabilities read-only do contexto para responder "
        "de forma direta. Se a execução falhar ou estiver inconclusiva, diga isso explicitamente.]"
    )
    extra_context += (
        "\n[Se houver capability local read-only executada com sucesso neste turno, "
        "nao diga que voce nao tem acesso ao dispositivo; responda com base no payload executado.]"
    )
    if feedback in ("negative", "correction"):
        extra_context += "\n[O usuário indicou insatisfação com a resposta anterior. Ajuste.]"

    messages = build_chat_messages(
        user_message=request + extra_context,
        memory_context=memory_context,
        message_history=history,
        session_preferences=session.learned_preferences,
        graph_stats=compute_persona_context(graph),
    )
    response_text = _inline_response_text(
        request=request,
        llm_client=llm_client,
        messages=messages,
        suggested_tier=suggested_tier,
        inline_payloads=inline_payloads,
        strict_on_llm_failure=strict_on_llm_failure,
    )

    mem_ids = [m.get("id", "") for m in retrieval.relevant_memories if m.get("id")]
    syn_ids = [s.get("id", "") for s in retrieval.relevant_synapses if s.get("id")]
    activated = mem_ids + syn_ids
    if activated:
        apply_learning_to_graph(
            graph,
            activated_node_ids=activated,
            feedback=feedback,
            synapse_ids=syn_ids,
            memory_ids=mem_ids,
        )

    _remember_turn(memory, request, response_text, session.id)

    session = sessions.record_turn(session, request, response_text)
    store = RunStore(output_dir, run_id).create()
    response_path = store.write_text("response.md", response_text)
    learning_path = store.write_json(
        "learning.json",
        {
            "feedback": feedback,
            "reward": reward,
            "path": "inline_capability",
            "retrieval_hits": len(retrieval.match_results),
            "inline_capabilities": [item["capability_id"] for item in inline_payloads],
        },
    )
    inline_path = store.write_json(
        "inline-capabilities.json",
        {"request": request, "capabilities": inline_payloads},
    )
    return RunResult(
        run_id=run_id,
        run_dir=store.run_dir,
        files={
            "response": response_path,
            "learning": learning_path,
            "inline_capabilities": inline_path,
            "external_data": inline_path,
        },
        session_id=session.id,
        response=response_text,
    )


def external_data_response(**kwargs: Any) -> RunResult:
    """Compat: alias legado para o roteamento inline de capabilities."""
    return inline_capability_response(**kwargs)


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

    # Sem LLM: concatenação direta dos conteúdos reais
    from arnaldo.prompts.context import _extract_step_content

    parts: list[str] = []
    for step in steps:
        content = _extract_step_content(step)
        if content:
            parts.append(content[:500])
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


def _collect_inline_capability_results(
    *,
    request: str,
    capability_ids: list[str],
    message_history: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    executor = CapabilityExecutor()
    payloads: list[dict[str, Any]] = []
    context_blocks: list[str] = []
    seen: set[str] = set()
    summary = summarize_capability_ids(capability_ids)
    executable_ids = list(summary.inline_lookup_executor_ids) or _dedupe_capability_ids(
        capability_ids
    )
    for capability_id in executable_ids:
        normalized = str(capability_id).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        params = _build_inline_capability_params(
            normalized,
            request,
            message_history=message_history,
        )
        if not params:
            continue
        result = executor.execute(normalized, params)
        payload = {
            "capability_id": normalized,
            "success": result.success,
            "latency_ms": result.latency_ms,
            "error": result.error,
            "data": result.data,
            "metadata": result.metadata,
        }
        payloads.append(payload)
        formatted = _format_inline_capability_context(payload)
        if formatted:
            context_blocks.append(formatted)
    return payloads, "\n\n".join(block for block in context_blocks if block.strip())


def _inline_response_text(
    *,
    request: str,
    llm_client: Any,
    messages: list[dict[str, str]],
    suggested_tier: str,
    inline_payloads: list[dict[str, Any]],
    strict_on_llm_failure: bool = False,
) -> str:
    tier = suggested_tier if suggested_tier in {"fast", "expert", "god", "codex"} else "expert"
    has_successful_payload = any(bool(item.get("success")) for item in inline_payloads)

    # Sem dados coletados, LLM não tem o que sintetizar — retorna erro direto
    if not has_successful_payload:
        return "Nao consegui confirmar dados atuais na web agora."

    # Tenta síntese via LLM
    if llm_client and getattr(llm_client, "is_configured", False):
        try:
            resp = llm_client.chat(tier=tier, messages=messages, timeout=45.0)
            content = str(getattr(resp, "content", "") or "").strip()
            if content:
                return content
        except Exception as exc:
            logger.warning("inline capability synthesis falhou: %s", exc)

    # LLM falhou — decisão via política do profile
    if strict_on_llm_failure:
        if has_successful_payload:
            return (
                "Erro: síntese LLM indisponível. "
                "Dados coletados mas o perfil exige processamento LLM."
            )
        return "Erro: síntese LLM indisponível e nenhum dado foi coletado."

    # Profile permite resposta sem LLM — usa dados brutos formatados
    if has_successful_payload:
        return _inline_raw_data_response(request=request, inline_payloads=inline_payloads)

    # Nenhum payload e LLM falhou
    return "Nenhum dado disponível para esta consulta."


def _build_inline_capability_params(
    capability_id: str,
    request: str,
    *,
    message_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    from arnaldo.graph.execution.context import StepContext
    from arnaldo.graph.execution.tooling import (
        _build_capability_params as _build_graph_capability_params,
    )

    if not capability_id:
        return None
    effective_request = request
    if capability_id == "search.public_web":
        effective_request = _resolve_inline_search_request(
            request,
            message_history=message_history,
        )
    return _build_graph_capability_params(
        capability_id,
        f"UserRequest: {effective_request}",
        StepContext(),
    )


def _format_inline_capability_context(payload: dict[str, Any]) -> str:
    formatters = {
        "search.public_web": _format_search_public_web_context,
        "filesystem.local.search": _format_filesystem_local_search_context,
        "shell.local.readonly": _format_shell_local_context,
    }
    capability_id = str(payload.get("capability_id", "")).strip().lower()
    formatter = formatters.get(capability_id, _format_generic_inline_context)
    return formatter(payload)


def _inline_raw_data_response(
    *,
    request: str,
    inline_payloads: list[dict[str, Any]],
) -> str:
    """Formata dados brutos de capabilities quando LLM não está disponível."""
    if not inline_payloads:
        return "Nenhum dado disponível para esta consulta."
    formatters = {
        "search.public_web": _format_raw_search_public_web,
        "filesystem.local.search": _format_raw_filesystem_local_search,
        "shell.local.readonly": _format_raw_shell_local,
    }
    for payload in inline_payloads:
        if not payload.get("success"):
            continue
        capability_id = str(payload.get("capability_id", "")).strip().lower()
        formatter = formatters.get(capability_id, _format_raw_generic_inline)
        text = formatter(payload)
        if text:
            return text
    # Nenhum payload com sucesso
    errors = [str(p.get("error", "desconhecido")) for p in inline_payloads if not p.get("success")]
    if errors:
        return f"Erro na execução: {'; '.join(errors)}"
    return f"Sem dados para: {request}"


def _format_search_public_web_context(payload: dict[str, Any]) -> str:
    if not payload.get("success"):
        error = str(payload.get("error", "")).strip() or "falha_desconhecida"
        return f"Busca web recente falhou: {error}"

    data = payload.get("data")
    if not isinstance(data, dict):
        return "Busca web recente sem payload estruturado."

    results = data.get("results")
    if not isinstance(results, list) or not results:
        return "Busca web recente sem resultados relevantes."

    lines = ["Resultados recentes de capability read-only (busca web):"]
    for idx, item in enumerate(results[:5], 1):
        if not isinstance(item, dict):
            continue
        title = _compact_text(item.get("title"), limit=140)
        snippet = _compact_text(item.get("snippet"), limit=240)
        url = _compact_text(item.get("url"), limit=220)
        line = f"{idx}. {title}" if title else f"{idx}."
        if snippet:
            line += f" | {snippet}"
        if url:
            line += f" | fonte={url}"
        lines.append(line)
    return "\n".join(lines)


def _format_generic_inline_context(payload: dict[str, Any]) -> str:
    capability_id = str(payload.get("capability_id", "")).strip()
    if not payload.get("success"):
        error = str(payload.get("error", "")).strip() or "falha_desconhecida"
        return f"Capability {capability_id} falhou: {error}"
    data = _compact_text(payload.get("data"), limit=360)
    if data:
        return f"Resultado inline de {capability_id}: {data}"
    return f"Capability {capability_id} executada sem payload textual relevante."


def _format_filesystem_local_search_context(payload: dict[str, Any]) -> str:
    if not payload.get("success"):
        error = str(payload.get("error", "")).strip() or "falha_desconhecida"
        return f"Busca local read-only falhou: {error}"

    data = payload.get("data")
    if not isinstance(data, dict):
        return "Busca local read-only sem payload estruturado."

    matches = data.get("matches")
    if not isinstance(matches, list) or not matches:
        pattern = _compact_text(data.get("pattern"), limit=120)
        if pattern:
            return f"Busca local read-only sem resultados para o padrão {pattern}."
        return "Busca local read-only sem resultados relevantes."

    lines = ["Resultados reais de capability read-only (filesystem local):"]
    for idx, item in enumerate(matches[:8], 1):
        if not isinstance(item, dict):
            continue
        name = _compact_text(item.get("name"), limit=160)
        path = _compact_text(item.get("path"), limit=240)
        entry_type = _compact_text(item.get("type"), limit=32)
        label = name or path or f"item {idx}"
        line = f"{idx}. {label}"
        if entry_type:
            line += f" | tipo={entry_type}"
        if path and path != label:
            line += f" | path={path}"
        lines.append(line)
    return "\n".join(lines)


def _format_shell_local_context(payload: dict[str, Any]) -> str:
    if not payload.get("success"):
        error = str(payload.get("error", "")).strip() or "falha_desconhecida"
        return f"Execução local read-only falhou: {error}"

    data = payload.get("data")
    if not isinstance(data, dict):
        return "Execução local read-only sem payload estruturado."

    command = _compact_text(data.get("command"), limit=240)
    stdout = _compact_text(data.get("stdout"), limit=1200)
    lines = ["Saída real de capability read-only (shell local):"]
    if command:
        lines.append(f"comando={command}")
    if stdout:
        lines.append(stdout)
    else:
        lines.append("Comando executado sem stdout relevante.")
    return "\n".join(lines)


def _format_raw_search_public_web(payload: dict[str, Any]) -> str:
    if not payload.get("success"):
        error = str(payload.get("error", "")).strip() or "falha_desconhecida"
        return "Nao consegui confirmar dados atuais na web agora. Motivo: %s." % error
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return "Nao encontrei resultados atuais o suficiente para responder com seguranca."
    first = _select_best_search_result(results)
    title = _compact_text(first.get("title"), limit=180)
    snippet = _compact_text(first.get("snippet"), limit=260)
    parts = ["Encontrei um resultado recente na web para sua pergunta."]
    if title:
        parts.append(title)
    if snippet:
        parts.append(snippet)
    return "\n\n".join(parts)


def _select_best_search_result(results: list[Any]) -> dict[str, Any]:
    candidates = [item for item in results if isinstance(item, dict)]
    if not candidates:
        return {}
    preferred = [
        item
        for item in candidates
        if "duckduckgo.com/y.js?ad_domain=" not in str(item.get("url", "")).lower()
    ]
    if preferred:
        return preferred[0]
    return candidates[0]


def _resolve_inline_search_request(
    request: str,
    *,
    message_history: list[dict[str, Any]] | None = None,
) -> str:
    request_text = str(request).strip()
    if not _is_generic_web_search_followup(request_text):
        return request_text
    previous = _last_substantive_user_message(message_history or [])
    return previous or request_text


def _is_generic_web_search_followup(request_text: str) -> bool:
    tokens = re.findall(r"[a-z0-9_à-ÿ-]+", str(request_text).lower())
    if not tokens:
        return False
    search_markers = ("goog", "pesq", "busc", "procur", "esquis")
    if not any(any(marker in token for marker in search_markers) for token in tokens):
        return False
    ignored_tokens = {
        "google",
        "web",
        "internet",
        "no",
        "na",
        "pra",
        "para",
        "ai",
        "aí",
        "isso",
        "isto",
        "sobre",
        "favor",
        "por",
        "favor",
    }
    content_tokens = [
        token
        for token in tokens
        if token not in ignored_tokens and not any(marker in token for marker in search_markers)
    ]
    return len(content_tokens) <= 1


def _last_substantive_user_message(message_history: list[dict[str, Any]]) -> str:
    for item in reversed(message_history):
        if str(item.get("role", "")).strip() != "user":
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if _is_generic_web_search_followup(content):
            continue
        return content
    return ""


def _format_raw_filesystem_local_search(payload: dict[str, Any]) -> str:
    if not payload.get("success"):
        error = str(payload.get("error", "")).strip() or "falha_desconhecida"
        return "Nao consegui listar ou localizar arquivos locais agora. Motivo: %s." % error
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    matches = data.get("matches")
    if not isinstance(matches, list) or not matches:
        return "Nao encontrei arquivos ou pastas locais que batam com o pedido."
    rendered: list[str] = []
    for item in matches[:5]:
        if not isinstance(item, dict):
            continue
        label = _compact_text(item.get("path") or item.get("name"), limit=180)
        if label:
            rendered.append(label)
    if rendered:
        return "Encontrei estes caminhos locais relevantes:\n\n" + "\n".join(rendered)
    return "Encontrei resultados locais, mas sem conteúdo textual suficiente para resumir."


def _format_raw_shell_local(payload: dict[str, Any]) -> str:
    if not payload.get("success"):
        error = str(payload.get("error", "")).strip() or "falha_desconhecida"
        return "Nao consegui executar o comando local read-only agora. Motivo: %s." % error
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    command = _compact_text(data.get("command"), limit=220)
    listing_response = _render_shell_listing_response(
        command=str(data.get("command", "") or ""),
        stdout=str(data.get("stdout", "") or ""),
    )
    if listing_response:
        return listing_response
    stdout = _compact_text(data.get("stdout"), limit=1200)
    if stdout:
        if command:
            return "Executei o comando local read-only `%s` e obtive:\n\n%s" % (command, stdout)
        return "Executei o comando local read-only e obtive:\n\n%s" % stdout
    if command:
        return (
            "Executei o comando local read-only `%s`, mas ele não retornou saída relevante."
            % command
        )
    return "Executei o comando local read-only, mas ele não retornou saída relevante."


def _format_raw_generic_inline(payload: dict[str, Any]) -> str:
    capability_id = str(payload.get("capability_id", "")).strip()
    if not capability_id:
        return ""
    if not payload.get("success"):
        error = str(payload.get("error", "")).strip() or "falha_desconhecida"
        return f"A capability {capability_id} falhou: {error}."
    data = payload.get("data")
    compact = _compact_text(data, limit=260)
    if compact:
        return f"A capability {capability_id} retornou: {compact}"
    return ""


def _dedupe_capability_ids(capability_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for capability_id in capability_ids:
        current = str(capability_id).strip().lower()
        if not current or current in seen:
            continue
        seen.add(current)
        normalized.append(current)
    return normalized


def _compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _has_local_inline_payload(inline_payloads: list[dict[str, Any]]) -> bool:
    return any(
        str(payload.get("capability_id", "")).strip().lower()
        in {"filesystem.local.search", "shell.local.readonly"}
        for payload in inline_payloads
    )


def _render_shell_listing_response(*, command: str, stdout: str) -> str:
    normalized_command = " ".join(str(command or "").strip().lower().split())
    raw_stdout = str(stdout or "")
    if not normalized_command or not raw_stdout.strip():
        return ""
    if normalized_command.startswith("cmd /c dir") or normalized_command.startswith("dir"):
        return _render_windows_dir_listing(raw_stdout)
    if normalized_command == "ls" or normalized_command.startswith("ls "):
        entries = [line.strip() for line in raw_stdout.splitlines() if line.strip()]
        if not entries:
            return ""
        preview = "\n".join(entries[:20])
        if len(entries) > 20:
            preview += "\n..."
        return "Listei o diretório com `ls` e encontrei:\n\n%s" % preview
    return ""


def _render_windows_dir_listing(stdout: str) -> str:
    directory = ""
    entries: list[str] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("directory of "):
            directory = line[13:].strip()
            continue
        match = re.match(
            r"^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+[AP]M\s+(<DIR>|\d[\d,]*)\s+(.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        entry_kind = match.group(1).upper()
        name = match.group(2).strip()
        if name in {".", ".."}:
            continue
        prefix = "[dir]" if entry_kind == "<DIR>" else "[file]"
        entries.append(f"{prefix} {name}")
    if not entries:
        return ""
    preview = "\n".join(entries[:20])
    if len(entries) > 20:
        preview += "\n..."
    if directory:
        return "Listei `%s` com `dir` e encontrei:\n\n%s" % (directory, preview)
    return "Listei o diretório com `dir` e encontrei:\n\n%s" % preview
