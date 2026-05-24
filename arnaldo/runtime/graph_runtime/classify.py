"""Classificação de tarefas e defaults de ações para o GraphRuntime."""

from __future__ import annotations

import re
from typing import Any, Dict

from arnaldo.constants.discovery_terms import (
    AMBIGUOUS_VERBS,
    FILESYSTEM_DISCOVERY_VERBS,
    LOCAL_CONTEXT_NOUNS,
    SHELL_CONTEXT_NOUNS,
    SHELL_EXECUTION_VERBS,
    TECHNICAL_CONTEXT,
    TOOLING_PREFIXES,
)


def _is_lightweight_conversational_task(task: Any) -> bool:
    goal = task.goal if isinstance(task.goal, dict) else {}
    goal_type = str(goal.get("type", "")).strip()
    if goal_type != "open_ended_execution":
        return False

    candidate = _extract_primary_user_request(task).lower()
    if candidate and re.match(r"^(oi|ol[aá]|hello|hi|bom dia|boa tarde|boa noite)\b", candidate):
        return True
    identity_patterns = (
        r"\bquem sou eu\b",
        r"\bqual (?:e|é) meu nome\b",
        r"\bcomo eu me chamo\b",
        r"\blembra do meu nome\b",
        r"\bmeu nome (?:e|é)\b",
        r"\bme chama de\b",
        r"\bpode me chamar de\b",
        r"\bme chama assim\b",
        r"\bpode me chamar assim\b",
    )
    if candidate and any(re.search(pattern, candidate) for pattern in identity_patterns):
        return True

    statement = str(goal.get("statement", "")).strip().lower()
    if statement:
        markers = (
            "sauda",
            "cumpriment",
            "conversa inicial",
            "greeting",
            "olá",
            "ola",
            "oi",
            "identidade no contexto da conversa",
            "nome informado",
        )
        if any(marker in statement for marker in markers):
            return True
    return False


def _extract_primary_user_request(task: Any) -> str:
    context_raw = getattr(task, "context", {})
    context = context_raw if isinstance(context_raw, dict) else {}
    raw = str(context.get("raw_request") or context.get("original_request") or "").strip()
    if not raw:
        return ""
    cleaned = " ".join(raw.split())
    markers = (
        "contexto_objetivos_ativos:",
        "objetivos_extraidos_no_turno:",
        "continuidade_sessao:",
    )
    lower_cleaned = cleaned.lower()
    cut = len(cleaned)
    for marker in markers:
        pos = lower_cleaned.find(marker)
        if pos >= 0:
            cut = min(cut, pos)
    primary = cleaned[:cut].strip(" |;-")
    return primary or cleaned


def _is_latency_sensitive_cli_turn(
    *,
    task: Any,
    capability_resolution: Dict[str, Any],
) -> bool:
    goal = task.goal if isinstance(task.goal, dict) else {}
    goal_type = str(goal.get("type", "")).strip()
    if goal_type not in {"analyze_or_evaluate", "decide_or_compare"}:
        return False

    context_raw = getattr(task, "context", {})
    context = context_raw if isinstance(context_raw, dict) else {}
    source = str(context.get("source", "")).strip().lower()
    if source != "cli":
        return False
    request = _extract_primary_user_request(task)
    if not request:
        return False
    word_count = _word_count(request)
    if word_count > 6:
        return False

    for bucket in ("missing", "degraded"):
        for item in capability_resolution.get(bucket, []) or []:
            capability_id = str(item.get("id", "")).strip()
            if capability_id.startswith(TOOLING_PREFIXES):
                return False
    return True


def _is_conversational_cli_turn(
    *,
    task: Any,
    capability_resolution: Dict[str, Any] | None = None,
) -> bool:
    goal = task.goal if isinstance(task.goal, dict) else {}
    if str(goal.get("type", "")).strip() != "open_ended_execution":
        return False
    context_raw = getattr(task, "context", {})
    context = context_raw if isinstance(context_raw, dict) else {}
    source = str(context.get("source", "")).strip().lower()
    if source != "cli":
        return False
    context_text = str(context.get("original_request", "")).strip().lower()
    continuity_markers = (
        "contexto_objetivos_ativos:",
        "objetivos_extraidos_no_turno:",
        "continuidade_sessao:",
    )
    has_chat_continuity = any(marker in context_text for marker in continuity_markers)
    has_raw_chat_turn = bool(str(context.get("raw_request", "")).strip())
    if (
        not has_chat_continuity
        and not has_raw_chat_turn
        and not _is_lightweight_conversational_task(task)
    ):
        return False
    request = _extract_primary_user_request(task)
    if not request:
        return False
    if _contains_structured_execution_intent(request):
        return False
    if capability_resolution:
        for bucket in ("missing", "degraded"):
            for item in capability_resolution.get(bucket, []) or []:
                capability_id = str(item.get("id", "")).strip()
                if capability_id.startswith(TOOLING_PREFIXES):
                    return False
    if _word_count(request) > 36 and not _is_lightweight_conversational_task(task):
        return False
    return True


def _word_count(text: str) -> int:
    return len([chunk for chunk in str(text).split() if chunk.strip()])


def _contains_structured_execution_intent(text: str) -> bool:
    candidate = str(text).lower()
    if not candidate:
        return False

    # Patterns inequívocos — match direto, sem co-ocorrência
    unambiguous_patterns = (
        r"\bapi\b",
        r"\bconector\b",
        r"\bconnector\b",
        r"\bworkflow\b",
        r"\bferramenta\b",
        r"\btool(?:ing)?\b",
        r"\bintegrar\b",
        r"\bimplement(?:ar|acao|ação)\b",
        r"\bdesenvolver\b",
        r"\bprojetar\b",
        r"\barquitetura\b",
        r"\bgrafo\b",
        r"\bc[oó]digo\b",
        r"\bbackend\b",
        r"\bfrontend\b",
        r"\brl\b",
        r"\breinforcement\b",
    )
    if any(re.search(p, candidate) for p in unambiguous_patterns):
        return True

    # Verbos de descoberta local — match direto
    for verb in FILESYSTEM_DISCOVERY_VERBS:
        if re.search(rf"\b{re.escape(verb)}\b", candidate):
            return True

    # Verbos de execução shell — match direto
    for verb in SHELL_EXECUTION_VERBS:
        if re.search(rf"\b{re.escape(verb)}\b", candidate):
            return True

    # Substantivos de contexto local/shell — match direto
    for noun in (*LOCAL_CONTEXT_NOUNS, *SHELL_CONTEXT_NOUNS):
        if re.search(rf"\b{re.escape(noun)}\b", candidate):
            return True

    # Verbos ambíguos ("criar", "abrir", "mostrar") — SÓ com co-ocorrência técnica
    for verb in AMBIGUOUS_VERBS:
        if re.search(rf"\b{re.escape(verb)}\b", candidate):
            if any(ctx in candidate for ctx in TECHNICAL_CONTEXT):
                return True

    return False


def _default_agent_for_action(action: str) -> str:
    return {
        "frame_intent": "framer",
        "clarify_uncertainties": "clarifier",
        "explore_path_a": "explorer_a",
        "explore_path_b": "explorer_b",
        "decompose_work": "planner",
        "design_tooling": "toolsmith",
        "stabilize_tooling": "toolsmith",
        "execute_tooling": "toolrunner",
        "compose_tooling": "workflow_composer",
        "synthesize_artifact": "synthesizer",
        "draft_artifact": "planner",
        "critic_review": "critic",
        "risk_review": "risk_auditor",
        "decision_synthesis": "critic",
    }.get(action, "operator")


def _default_role_for_action(action: str) -> str:
    return {
        "frame_intent": "operator",
        "clarify_uncertainties": "analyst",
        "explore_path_a": "explorer",
        "explore_path_b": "explorer",
        "decompose_work": "operator",
        "design_tooling": "operator",
        "stabilize_tooling": "operator",
        "execute_tooling": "operator",
        "compose_tooling": "synthesizer",
        "synthesize_artifact": "synthesizer",
        "draft_artifact": "operator",
        "critic_review": "critic",
        "risk_review": "critic",
        "decision_synthesis": "critic",
    }.get(action, "operator")


def _default_objective_for_action(action: str, item: Dict[str, Any]) -> str:
    if action == "design_tooling":
        capability_id = str(item.get("capability_id", "")).strip()
        return (
            "definir e especificar a capability ausente %s" % capability_id
            if capability_id
            else "definir especificacao de tooling"
        )
    if action == "stabilize_tooling":
        capability_id = str(item.get("capability_id", "")).strip()
        return (
            "estabilizar e validar a capability degradada %s" % capability_id
            if capability_id
            else "estabilizar tooling degradado"
        )
    if action == "execute_tooling":
        capability_id = str(item.get("capability_id", "")).strip()
        return (
            "executar e validar em runtime a capability dinâmica %s" % capability_id
            if capability_id
            else "executar tooling dinâmico"
        )
    if action == "compose_tooling":
        return "compor os resultados das sinapses de tooling em um plano integrado de execução"
    return {
        "frame_intent": "enquadrar objetivo e critérios operacionais",
        "clarify_uncertainties": "transformar incertezas em perguntas acionáveis",
        "explore_path_a": "propor primeira alternativa de execução",
        "explore_path_b": "propor segunda alternativa de execução",
        "decompose_work": "decompor o trabalho em etapas executáveis",
        "synthesize_artifact": "sintetizar alternativas em um artefato único",
        "draft_artifact": "construir artefato inicial executável",
        "critic_review": "revisar lacunas e evidências",
        "risk_review": "revisar riscos e pontos de falha",
        "decision_synthesis": "produzir síntese de decisão",
    }.get(action, action)


def _default_output_for_action(action: str) -> str:
    return {
        "frame_intent": "intent_frame",
        "clarify_uncertainties": "uncertainty_map",
        "explore_path_a": "work_option_a",
        "explore_path_b": "work_option_b",
        "decompose_work": "work_plan",
        "design_tooling": "tool_specs",
        "stabilize_tooling": "tool_stability",
        "execute_tooling": "tool_exec",
        "compose_tooling": "tooling_composition",
        "synthesize_artifact": "primary_artifact",
        "draft_artifact": "primary_artifact",
        "critic_review": "critic_review",
        "risk_review": "risk_report",
        "decision_synthesis": "decision_brief",
    }.get(action, "step_output")


def _toolsmith_agent_for_capability(capability_id: str) -> str:
    from .infra import _slug

    return "toolsmith_%s" % _slug(capability_id)


def _toolrunner_agent_for_capability(capability_id: str) -> str:
    from .infra import _slug

    return "toolrunner_%s" % _slug(capability_id)
