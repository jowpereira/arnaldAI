"""Contexto de execução e resultado de synapse."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass(slots=True)
class StepContext:
    """Blackboard entre execuções de synapse com histórico versionado."""

    outputs: dict[str, Any] = field(default_factory=dict)
    tool_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_history: list[dict[str, Any]] = field(default_factory=list)
    version: int = 0
    history_limit: int = 512
    refusals: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def write(
        self,
        node_id: str,
        value: Any,
        *,
        action: str = "",
        agent_id: str = "",
        capability_id: str = "",
        channel: str = "llm",
    ) -> None:
        normalized_action = str(action).strip()
        normalized_agent = str(agent_id).strip()
        normalized_capability = str(capability_id).strip()
        normalized_channel = str(channel).strip() or "llm"
        with self._lock:
            self.outputs[node_id] = value
            if normalized_capability:
                payload = value if isinstance(value, dict) else {"result": value}
                self.tool_outputs[normalized_capability] = {
                    "node_id": node_id,
                    "action": normalized_action,
                    "agent_id": normalized_agent,
                    "channel": normalized_channel,
                    "output": payload,
                }
            self.version += 1
            event = {
                "version": self.version,
                "node_id": node_id,
                "action": normalized_action,
                "agent_id": normalized_agent,
                "capability_id": normalized_capability,
                "channel": normalized_channel,
                "status": self._extract_status(value),
                "excerpt": str(value)[:300],
            }
            self.output_history.append(event)
            overflow = len(self.output_history) - self.history_limit
            if overflow > 0:
                del self.output_history[:overflow]

    def read(self, node_id: str) -> Any | None:
        with self._lock:
            return self.outputs.get(node_id)

    def record_refusal(self, node_id: str, reason: str) -> None:
        with self._lock:
            self.refusals.append({"node_id": node_id, "reason": reason})

    def record_error(self, node_id: str, error: str) -> None:
        with self._lock:
            self.errors.append({"node_id": node_id, "error": error})

    def record_tool_output(self, node_id: str, capability_id: str, value: Any) -> None:
        if not capability_id:
            return
        self.write(
            node_id,
            value,
            capability_id=capability_id,
            channel="tool",
        )

    def snapshot_recent_outputs(self, *, limit: int = 3) -> dict[str, str]:
        with self._lock:
            if limit <= 0:
                return {}
            return {
                str(item["node_id"]): str(item["excerpt"]) for item in self.output_history[-limit:]
            }

    def snapshot_recent_tool_outputs(self, *, limit: int = 3) -> dict[str, dict[str, str]]:
        with self._lock:
            if limit <= 0:
                return {}
            return {
                capability_id: {
                    "node_id": str(item.get("node_id", "")),
                    "action": str(item.get("action", ""))[:120],
                    "channel": str(item.get("channel", ""))[:40],
                    "status": str((item.get("output") or {}).get("status", ""))[:120],
                    "excerpt": str(item.get("output", {}))[:300],
                }
                for capability_id, item in list(self.tool_outputs.items())[-limit:]
            }

    def snapshot_related_outputs(
        self,
        *,
        action: str = "",
        capability_id: str = "",
        limit: int = 3,
    ) -> list[dict[str, str]]:
        normalized_action = str(action).strip()
        normalized_capability = str(capability_id).strip()
        if limit <= 0:
            return []

        with self._lock:
            history = list(self.output_history)

        if not history:
            return []

        ranked: list[tuple[int, int, dict[str, Any]]] = []
        for item in history:
            item_action = str(item.get("action", "")).strip()
            item_capability = str(item.get("capability_id", "")).strip()
            item_channel = str(item.get("channel", "")).strip()
            score = 0
            if (
                normalized_capability
                and item_capability
                and item_capability == normalized_capability
            ):
                score += 4
            if normalized_action and item_action and item_action == normalized_action:
                score += 3
            if item_channel == "tool":
                score += 1
            if score <= 0 and (normalized_action or normalized_capability):
                continue
            ranked.append((score, int(item.get("version", 0)), item))

        if not ranked:
            return []

        ranked.sort(key=lambda bucket: (bucket[0], bucket[1]), reverse=True)
        selected = [bucket[2] for bucket in ranked[:limit]]
        selected.sort(key=lambda item: int(item.get("version", 0)))
        return [
            {
                "version": str(item.get("version", "")),
                "node_id": str(item.get("node_id", "")),
                "action": str(item.get("action", "")),
                "capability_id": str(item.get("capability_id", "")),
                "channel": str(item.get("channel", "")),
                "status": str(item.get("status", "")),
                "excerpt": str(item.get("excerpt", "")),
            }
            for item in selected
        ]

    @staticmethod
    def _extract_status(value: Any) -> str:
        if isinstance(value, dict):
            status = str(value.get("status", "")).strip()
            if status:
                return status
        return "ok"


@dataclass(slots=True)
class SynapseExecutionResult:
    """Resultado padronizado de uma execução de synapse."""

    node_id: str
    tier: str
    success: bool
    output: Any | None = None
    refusal: str | None = None
    error: str | None = None
    fallback_used: bool = False
