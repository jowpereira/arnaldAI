from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import re

from arnaldo.capabilities.semantics import build_capability_need
from arnaldo.constants.discovery_terms import (
    ALL_LOCAL_DISCOVERY_TERMS,
    READONLY_SHELL_COMMAND_HINTS,
    SHELL_CONTEXT_NOUNS,
    SHELL_EXECUTION_VERBS,
)
from arnaldo.contracts import new_id, utc_now
from arnaldo.session import SessionState


@dataclass
class AdaptivePlan:
    version: str
    id: str
    created_at: str
    session_id: str
    compiled_request: str
    inferred_objectives: List[str]
    priority_actions: List[Dict[str, Any]]
    capability_hints: List[Dict[str, Any]]
    learning_updates: Dict[str, Any]
    should_forge_tools: bool


class AdaptivePlanner:
    """Builds a turn-level plan that preserves continuity and adapts over time."""

    def plan(self, request: str, session: SessionState) -> AdaptivePlan:
        text = normalize_request(request)
        if not text:
            raise ValueError("Informe uma mensagem para o turno atual.")

        inferred_objectives = infer_objectives(text)
        learning_updates = infer_learning_updates(text)
        capability_hints = infer_capability_hints(text)

        compiled_request = compose_turn_request(text, session, inferred_objectives)
        should_forge_tools = should_forge(text, capability_hints, session)

        return AdaptivePlan(
            version="adaptive-plan/v0",
            id=new_id("adaptive"),
            created_at=utc_now(),
            session_id=session.id,
            compiled_request=compiled_request,
            inferred_objectives=inferred_objectives,
            priority_actions=build_priority_actions(inferred_objectives, should_forge_tools),
            capability_hints=capability_hints,
            learning_updates=learning_updates,
            should_forge_tools=should_forge_tools,
        )

    def merge_capability_hints(
        self,
        current_needs: List[Dict[str, Any]],
        hints: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged = {item["id"]: dict(item) for item in current_needs}
        for hint in hints:
            capability_id = hint["id"]
            payload = build_capability_need(
                capability_id,
                required=bool(hint.get("required", True)),
                reason=str(hint.get("reason", "adaptive_hint")),
            )
            if capability_id in merged:
                merged[capability_id]["required"] = (
                    merged[capability_id].get("required", False) or payload["required"]
                )
                for field in (
                    "family",
                    "locality",
                    "access_mode",
                    "effect",
                    "freshness",
                    "abstract",
                    "inline_lookup_executor_id",
                ):
                    if field in payload:
                        merged[capability_id][field] = payload[field]
                if payload.get("reason"):
                    merged[capability_id]["reason"] = payload["reason"]
            else:
                merged[capability_id] = payload
        return list(merged.values())


def normalize_request(request: str) -> str:
    return " ".join((request or "").strip().split())


def infer_objectives(text: str) -> List[str]:
    lowered = text.lower()
    objectives: List[str] = []
    patterns = [
        r"(?:quero|preciso|objetivo|meta)\s+(?:que\s+)?(.+)",
        r"(?:foco|prioridade)\s*[:\-]\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            candidate = match.group(1).strip(" .")
            if candidate:
                objectives.append(candidate[:180])
    return dedupe(objectives)


def infer_learning_updates(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    preference = {
        "response_style": "balanced",
        "depth": "standard",
    }
    if any(term in lowered for term in ["direto", "curto", "resumido"]):
        preference["response_style"] = "concise"
    if any(term in lowered for term in ["detalhado", "profundo", "completo"]):
        preference["depth"] = "deep"
    if any(term in lowered for term in ["rapido", "agil", "urgente"]):
        preference["depth"] = "shallow"
    user_name = infer_user_name(text)
    if user_name:
        preference["user_name"] = user_name
    return preference


def infer_user_name(text: str) -> str:
    normalized = normalize_request(text)
    lowered = normalized.lower()
    patterns = [
        r"\bmeu nome\s+(?:e|é)\s+([a-zA-Z][a-zA-Z0-9_'-]{0,40})",
        r"\bme chama de\s+([a-zA-Z][a-zA-Z0-9_'-]{0,40})",
        r"\bpode me chamar de\s+([a-zA-Z][a-zA-Z0-9_'-]{0,40})",
        r"^\s*([a-zA-Z][a-zA-Z0-9_'-]{0,40})\s*,?\s*me\s+chama\s+assim\b",
        r"^\s*([a-zA-Z][a-zA-Z0-9_'-]{0,40})\s*,?\s*pode\s+me\s+chamar\s+assim\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1).strip(" .,!?:;\"'()[]{}")
        if raw:
            return raw[:1].upper() + raw[1:]
    return ""


def infer_capability_hints(text: str) -> List[Dict[str, Any]]:
    lowered = text.lower()
    hints: List[Dict[str, Any]] = []

    if any(term in lowered for term in ["conector", "connector", "integra", "api", "plugin"]):
        hints.append(
            {
                "id": "connector.http.generic",
                "required": True,
                "reason": "pedido_explicitamente_envolve_conector_ou_integracao",
            }
        )
    if "github" in lowered:
        hints.append(
            {
                "id": "connector.github",
                "required": False,
                "reason": "pedido_cita_github",
            }
        )
    if any(term in lowered for term in ["crm", "hubspot", "salesforce"]):
        hints.append(
            {
                "id": "connector.crm",
                "required": False,
                "reason": "pedido_cita_crm",
            }
        )
    if any(
        term in lowered
        for term in ["ferramenta", "tool", "desenvolve ferramenta", "cria ferramenta"]
    ):
        hints.append(
            {
                "id": "tool.dynamic.build",
                "required": False,
                "reason": "pedido_indica_construcao_de_ferramenta",
            }
        )
    if any(term in lowered for term in ["web", "internet", "pesquisa"]):
        hints.append(
            {
                "id": "search.public_web",
                "required": False,
                "reason": "pedido_indica_busca_externa",
            }
        )
    # Descoberta local: filesystem / shell / comandos
    if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in ALL_LOCAL_DISCOVERY_TERMS):
        hints.append(
            {
                "id": "filesystem.local.search",
                "required": True,
                "reason": "pedido_indica_descoberta_local",
            }
        )
    # Shell local: verbos de execução ou substantivos de terminal
    _shell_terms = (*SHELL_EXECUTION_VERBS, *SHELL_CONTEXT_NOUNS)
    if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in _shell_terms):
        hints.append(
            {
                "id": "shell.local.readonly",
                "required": False,
                "reason": "pedido_indica_execucao_local",
            }
        )
    if any(
        re.search(rf"(?<![a-z0-9_-]){re.escape(term)}(?![a-z0-9_-])", lowered)
        for term in READONLY_SHELL_COMMAND_HINTS
    ):
        hints.append(
            {
                "id": "shell.local.readonly",
                "required": True,
                "reason": "pedido_indica_comando_read_only_explicito",
            }
        )
    return dedupe_hints(hints)


def compose_turn_request(text: str, session: SessionState, inferred_objectives: List[str]) -> str:
    context = [text]
    active = [
        item["statement"] for item in session.active_objectives if item.get("status") == "active"
    ]
    if active:
        context.append("contexto_objetivos_ativos: " + " | ".join(active[:3]))
    if inferred_objectives:
        context.append("objetivos_extraidos_no_turno: " + " | ".join(inferred_objectives[:3]))
    if session.turns > 0 and (active or inferred_objectives):
        context.append("continuidade_sessao: manter coerencia com historico recente")
    return "\n".join(context)


def build_priority_actions(
    inferred_objectives: List[str], should_forge_tools: bool
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = [
        {
            "id": "sync_objectives",
            "description": "sincronizar objetivos ativos da sessao",
            "priority": 1,
        },
        {"id": "execute_turn", "description": "compilar e executar pedido do turno", "priority": 2},
        {
            "id": "learn",
            "description": "atualizar preferencias e memoria procedural",
            "priority": 4,
        },
    ]
    if inferred_objectives:
        actions.append(
            {
                "id": "objective_alignment",
                "description": "alinhar execucao aos objetivos inferidos",
                "priority": 2,
            }
        )
    if should_forge_tools:
        actions.append(
            {
                "id": "tool_forge",
                "description": "propor ou gerar conectores para lacunas",
                "priority": 3,
            }
        )
    actions.sort(key=lambda item: item["priority"])
    return actions


def should_forge(text: str, capability_hints: List[Dict[str, Any]], session: SessionState) -> bool:
    from arnaldo.capabilities.catalog import get_catalog

    lowered = text.lower()
    if any(
        term in lowered
        for term in ["crie ferramenta", "desenvolve ferramenta", "conector", "integra"]
    ):
        return True
    # Filtrar builtins — não forjar o que já existe
    if capability_hints:
        catalog = get_catalog()
        missing = [h for h in capability_hints if not catalog.can_execute(h["id"])]
        if missing:
            return True
    return False


def dedupe(items: List[str]) -> List[str]:
    seen = set()
    output = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item.strip())
    return output


def dedupe_hints(hints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for hint in hints:
        capability_id = hint["id"]
        if capability_id not in merged:
            merged[capability_id] = dict(hint)
            continue
        merged[capability_id]["required"] = merged[capability_id].get("required", False) or bool(
            hint.get("required", False)
        )
    return list(merged.values())
