from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List
import json

from arnaldo.contracts import new_id


@dataclass(slots=True)
class ProactiveMessage:
    id: str
    session_id: str
    created_at: str
    due_at: str
    kind: str
    priority: float
    message: str
    status: str
    metadata: Dict[str, Any]
    delivered_at: str = ""


class ProactivityManager:
    """Fila persistente de mensagens proativas por sessão.

    Objetivos:
    - permitir iniciativa ativa do agente no chat;
    - manter trilha auditável (JSONL por sessão);
    - reduzir spam com deduplicação + cooldown.
    """

    def __init__(
        self,
        base_dir: Path = Path("storage/proactivity"),
        *,
        dedupe_window: timedelta = timedelta(minutes=30),
        max_pending_per_session: int = 5,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.dedupe_window = dedupe_window
        self.max_pending_per_session = max(1, int(max_pending_per_session))
        self._lock = Lock()

    def schedule(
        self,
        *,
        session_id: str,
        message: str,
        kind: str = "follow_up",
        priority: float = 0.5,
        delay_seconds: int = 0,
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        text = " ".join((message or "").strip().split())
        sid = str(session_id or "").strip()
        if not sid or not text:
            return False

        now = datetime.now(timezone.utc)
        due_at = now + timedelta(seconds=max(0, int(delay_seconds)))
        normalized_message = text.lower()

        with self._lock:
            records = self._load_records_locked(sid)
            pending = [item for item in records if str(item.get("status", "")) == "pending"]
            if len(pending) >= self.max_pending_per_session:
                return False
            if self._has_recent_duplicate(
                records=records,
                normalized_message=normalized_message,
                now=now,
            ):
                return False

            record = ProactiveMessage(
                id=new_id("proactive"),
                session_id=sid,
                created_at=now.isoformat(),
                due_at=due_at.isoformat(),
                kind=str(kind or "follow_up").strip() or "follow_up",
                priority=max(0.0, min(1.0, float(priority))),
                message=text,
                status="pending",
                metadata=dict(metadata or {}),
            )
            records.append(self._to_dict(record))
            self._write_records_locked(sid, records)
        return True

    def pop_due(
        self,
        *,
        session_id: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        sid = str(session_id or "").strip()
        if not sid:
            return []
        now = datetime.now(timezone.utc)
        max_items = max(1, int(limit))

        with self._lock:
            records = self._load_records_locked(sid)
            pending_due = [
                item
                for item in records
                if str(item.get("status", "")).strip() == "pending"
                and _parse_dt(item.get("due_at")) <= now
            ]
            pending_due.sort(
                key=lambda item: (
                    -float(item.get("priority", 0.0) or 0.0),
                    str(item.get("created_at", "")),
                )
            )
            selected = pending_due[:max_items]
            if not selected:
                return []

            selected_ids = {str(item.get("id", "")).strip() for item in selected}
            for item in records:
                if str(item.get("id", "")).strip() in selected_ids:
                    item["status"] = "delivered"
                    item["delivered_at"] = now.isoformat()
            self._write_records_locked(sid, records)
        return selected

    def schedule_from_run(
        self,
        *,
        session: Any,
        task: Any,
        adaptive_plan: Any,
        run_id: str,
    ) -> int:
        sid = str(getattr(session, "id", "")).strip()
        if not sid:
            return 0
        if self._is_lightweight_chat_turn(task):
            return 0
        scheduled = 0
        user_name = str(getattr(session, "learned_preferences", {}).get("user_name", "")).strip()
        vocative = (user_name + ", ") if user_name else ""

        uncertainties = []
        for item in getattr(task, "uncertainty", []) or []:
            question = str(item.get("question", "")).strip() if isinstance(item, dict) else ""
            if question and not self._is_generic_uncertainty(question):
                uncertainties.append(question)
        if uncertainties:
            created = self.schedule(
                session_id=sid,
                kind="clarification",
                priority=0.85,
                delay_seconds=15,
                message=f"{vocative}posso seguir agora nesta frente: {uncertainties[0]}",
                metadata={"run_id": run_id, "source": "task.uncertainty"},
            )
            scheduled += 1 if created else 0

        active_objective = ""
        for item in getattr(session, "active_objectives", []) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")).strip() != "active":
                continue
            active_objective = str(item.get("statement", "")).strip()
            if active_objective:
                break
        if active_objective and int(getattr(session, "turns", 0) or 0) >= 1:
            created = self.schedule(
                session_id=sid,
                kind="objective_followup",
                priority=0.65,
                delay_seconds=35,
                message=f"{vocative}quer que eu retome agora o objetivo ativo: {active_objective}?",
                metadata={"run_id": run_id, "source": "session.active_objective"},
            )
            scheduled += 1 if created else 0

        inferred_objectives = list(getattr(adaptive_plan, "inferred_objectives", []) or [])
        if inferred_objectives:
            objective = str(inferred_objectives[0]).strip()
            if objective and len(objective.split()) >= 3:
                created = self.schedule(
                    session_id=sid,
                    kind="continuity",
                    priority=0.55,
                    delay_seconds=25,
                    message=f"{vocative}se quiser, eu continuo daqui e avanço em: {objective}",
                    metadata={"run_id": run_id, "source": "adaptive.inferred_objective"},
                )
                scheduled += 1 if created else 0
        return scheduled

    @staticmethod
    def _is_lightweight_chat_turn(task: Any) -> bool:
        goal = task.goal if isinstance(getattr(task, "goal", None), dict) else {}
        if str(goal.get("type", "")).strip() != "open_ended_execution":
            return False
        context_raw = getattr(task, "context", {})
        context = context_raw if isinstance(context_raw, dict) else {}
        raw = str(context.get("raw_request") or context.get("original_request") or "").strip().lower()
        if not raw:
            return False
        if len(raw.split()) <= 5:
            return True
        return False

    @staticmethod
    def _is_generic_uncertainty(question: str) -> bool:
        lowered = question.strip().lower()
        generic_markers = (
            "qual artefato final",
            "nivel de profundidade",
            "quais acoes externas",
        )
        return any(marker in lowered for marker in generic_markers)

    def pending_count(self, *, session_id: str) -> int:
        sid = str(session_id or "").strip()
        if not sid:
            return 0
        with self._lock:
            records = self._load_records_locked(sid)
        return sum(1 for item in records if str(item.get("status", "")).strip() == "pending")

    def _has_recent_duplicate(
        self,
        *,
        records: List[Dict[str, Any]],
        normalized_message: str,
        now: datetime,
    ) -> bool:
        threshold = now - self.dedupe_window
        for item in reversed(records):
            msg = " ".join(str(item.get("message", "")).strip().split()).lower()
            if not msg or msg != normalized_message:
                continue
            created_at = _parse_dt(item.get("created_at"))
            if created_at >= threshold:
                return True
        return False

    def _session_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.jsonl"

    def _load_records_locked(self, session_id: str) -> List[Dict[str, Any]]:
        path = self._session_path(session_id)
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _write_records_locked(self, session_id: str, rows: List[Dict[str, Any]]) -> None:
        path = self._session_path(session_id)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=True))
                handle.write("\n")

    @staticmethod
    def _to_dict(item: ProactiveMessage) -> Dict[str, Any]:
        return {
            "id": item.id,
            "session_id": item.session_id,
            "created_at": item.created_at,
            "due_at": item.due_at,
            "kind": item.kind,
            "priority": item.priority,
            "message": item.message,
            "status": item.status,
            "metadata": item.metadata,
            "delivered_at": item.delivered_at,
        }


def _parse_dt(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc) if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    text = str(raw or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
