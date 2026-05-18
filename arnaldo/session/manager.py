from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
import json

from arnaldo.contracts import new_id, to_dict, utc_now


@dataclass
class SessionState:
    version: str
    id: str
    created_at: str
    updated_at: str
    autonomy_mode: str
    terms_accepted: bool
    governance_profile: str
    turns: int
    active_objectives: List[Dict[str, Any]]
    learned_preferences: Dict[str, Any]
    tool_history: List[Dict[str, Any]]


class SessionManager:
    """Persists long-lived session state and conversation history."""

    def __init__(self, base_dir: Path = Path("storage/sessions")) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def open(
        self,
        session_id: str | None = None,
        autonomy_mode: str = "assistido",
        terms_accepted: bool = False,
        governance_profile: str | None = None,
    ) -> SessionState:
        if session_id and self._session_file(session_id).exists():
            state = self.load(session_id)
            state.autonomy_mode = autonomy_mode or state.autonomy_mode
            if terms_accepted:
                state.terms_accepted = True
            if governance_profile:
                state.governance_profile = governance_profile
            elif state.terms_accepted and state.autonomy_mode in {"autonomo", "livre"}:
                state.governance_profile = "self_managed"
            self.save(state)
            return state

        created = utc_now()
        state = SessionState(
            version="session/v0",
            id=session_id or new_id("session"),
            created_at=created,
            updated_at=created,
            autonomy_mode=autonomy_mode,
            terms_accepted=bool(terms_accepted),
            governance_profile=governance_profile or self._default_profile(autonomy_mode, terms_accepted),
            turns=0,
            active_objectives=[],
            learned_preferences={},
            tool_history=[],
        )
        self.save(state)
        return state

    def load(self, session_id: str) -> SessionState:
        payload = json.loads(self._session_file(session_id).read_text(encoding="utf-8"))
        return SessionState(
            version=payload.get("version", "session/v0"),
            id=payload["id"],
            created_at=payload["created_at"],
            updated_at=payload.get("updated_at", payload["created_at"]),
            autonomy_mode=payload.get("autonomy_mode", "assistido"),
            terms_accepted=bool(payload.get("terms_accepted", False)),
            governance_profile=payload.get("governance_profile", "guarded"),
            turns=int(payload.get("turns", 0)),
            active_objectives=list(payload.get("active_objectives", [])),
            learned_preferences=dict(payload.get("learned_preferences", {})),
            tool_history=list(payload.get("tool_history", [])),
        )

    def save(self, state: SessionState) -> SessionState:
        state.updated_at = utc_now()
        self._session_file(state.id).write_text(
            json.dumps(to_dict(state), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return state

    def accept_terms(self, state: SessionState) -> SessionState:
        state.terms_accepted = True
        if state.autonomy_mode in {"autonomo", "livre"}:
            state.governance_profile = "self_managed"
        return self.save(state)

    def register_objective(self, state: SessionState, statement: str, priority: int = 5) -> SessionState:
        normalized = " ".join((statement or "").strip().split())
        if not normalized:
            return state
        lowered = normalized.lower()
        if any(item["statement"].lower() == lowered for item in state.active_objectives):
            return state

        created = utc_now()
        state.active_objectives.append(
            {
                "id": new_id("objective"),
                "statement": normalized,
                "status": "active",
                "priority": priority,
                "created_at": created,
                "updated_at": created,
            }
        )
        return self.save(state)

    def mark_objective_status(self, state: SessionState, objective_id: str, status: str) -> SessionState:
        for item in state.active_objectives:
            if item["id"] == objective_id:
                item["status"] = status
                item["updated_at"] = utc_now()
                break
        return self.save(state)

    def active_objectives(self, state: SessionState, limit: int = 3) -> List[Dict[str, Any]]:
        active = [item for item in state.active_objectives if item.get("status") == "active"]
        active.sort(key=lambda item: (item.get("priority", 5), item.get("created_at", "")))
        return active[:limit]

    def record_turn(
        self,
        state: SessionState,
        user_message: str,
        system_summary: str,
        metadata: Dict[str, Any] | None = None,
    ) -> SessionState:
        state.turns += 1
        event = {
            "id": new_id("turn"),
            "session_id": state.id,
            "index": state.turns,
            "created_at": utc_now(),
            "user_message": user_message,
            "system_summary": system_summary,
            "metadata": metadata or {},
        }
        with self._history_file(state.id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True))
            handle.write("\n")
        return self.save(state)

    def record_tool_event(
        self,
        state: SessionState,
        capability_id: str,
        status: str,
        metadata: Dict[str, Any] | None = None,
    ) -> SessionState:
        state.tool_history.append(
            {
                "id": new_id("tool_event"),
                "capability_id": capability_id,
                "status": status,
                "created_at": utc_now(),
                "metadata": metadata or {},
            }
        )
        state.tool_history = state.tool_history[-100:]
        return self.save(state)

    def update_preferences(self, state: SessionState, updates: Dict[str, Any]) -> SessionState:
        if not updates:
            return state
        state.learned_preferences.update(updates)
        return self.save(state)

    def snapshot(self, state: SessionState) -> Dict[str, Any]:
        return to_dict(state)

    def _default_profile(self, autonomy_mode: str, terms_accepted: bool) -> str:
        if terms_accepted and autonomy_mode in {"autonomo", "livre"}:
            return "self_managed"
        return "guarded"

    def _session_file(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def _history_file(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.history.jsonl"
