from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import re

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
            payload = {
                "id": capability_id,
                "required": bool(hint.get("required", True)),
                "reason": hint.get("reason", "adaptive_hint"),
            }
            if capability_id in merged:
                merged[capability_id]["required"] = merged[capability_id].get("required", False) or payload["required"]
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

    if not objectives:
        objectives.append(text[:180])
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
    return preference


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
    if any(term in lowered for term in ["ferramenta", "tool", "desenvolve ferramenta", "cria ferramenta"]):
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
    return dedupe_hints(hints)


def compose_turn_request(text: str, session: SessionState, inferred_objectives: List[str]) -> str:
    context = [text]
    active = [item["statement"] for item in session.active_objectives if item.get("status") == "active"]
    if active:
        context.append("contexto_objetivos_ativos: " + " | ".join(active[:3]))
    if inferred_objectives:
        context.append("objetivos_extraidos_no_turno: " + " | ".join(inferred_objectives[:3]))
    if session.turns > 0:
        context.append("continuidade_sessao: manter coerencia com historico recente")
    return "\n".join(context)


def build_priority_actions(inferred_objectives: List[str], should_forge_tools: bool) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = [
        {"id": "sync_objectives", "description": "sincronizar objetivos ativos da sessao", "priority": 1},
        {"id": "execute_turn", "description": "compilar e executar pedido do turno", "priority": 2},
        {"id": "learn", "description": "atualizar preferencias e memoria procedural", "priority": 4},
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
    lowered = text.lower()
    if any(term in lowered for term in ["crie ferramenta", "desenvolve ferramenta", "conector", "integra"]):
        return True
    if capability_hints:
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
        merged[capability_id]["required"] = merged[capability_id].get("required", False) or bool(hint.get("required", False))
    return list(merged.values())
