"""Registry de capabilities executáveis — resolve capability_id → executor."""

from __future__ import annotations

import importlib
import logging
from datetime import datetime, timezone
from typing import Any

from arnaldo.graph.events import EventKind, GraphEvent

from .base import CapabilityBase, CapabilityResult, make_source

logger = logging.getLogger("arnaldo.capabilities")

# Mapping estático: capability_id → módulo.classe
_BUILTIN_CAPABILITIES: dict[str, str] = {
    "search.public_web": "arnaldo.capabilities.web_search.WebSearchCapability",
    "connector.http.generic": "arnaldo.capabilities.http_connector.HttpConnectorCapability",
    "filesystem.local.search": "arnaldo.capabilities.filesystem_search.FilesystemSearchCapability",
    "shell.local.readonly": "arnaldo.capabilities.local_shell.LocalShellCapability",
}


class CapabilityExecutor:
    """Resolve e executa capabilities por ID."""

    def __init__(self) -> None:
        self._cache: dict[str, CapabilityBase] = {}
        self._events: list[GraphEvent] = []

    def can_execute(self, capability_id: str) -> bool:
        """Verifica se a capability tem implementação real."""
        return capability_id in _BUILTIN_CAPABILITIES

    def drain_events(self) -> list[GraphEvent]:
        """Retorna e limpa eventos pendentes — I6 compliance."""
        events = list(self._events)
        self._events.clear()
        return events

    def execute(
        self,
        capability_id: str,
        params: dict[str, Any],
    ) -> CapabilityResult:
        """Executa capability pelo ID. Retorna resultado ou erro."""
        executor = self._resolve(capability_id)
        if executor is None:
            result = CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"capability:{capability_id}"),
                error=f"Capability '{capability_id}' não tem implementação",
            )
            self._events.append(
                GraphEvent(
                    kind=EventKind.CAPABILITY_EXECUTED,
                    target_id=f"cap_{capability_id.replace('.', '_')}",
                    at=datetime.now(timezone.utc),
                    metadata={
                        "capability_id": capability_id,
                        "success": False,
                        "latency_ms": 0,
                        "error": "no_implementation",
                    },
                )
            )
            return result
        try:
            result = executor.execute(params)
        except Exception as exc:
            logger.warning("capability %s falhou: %s", capability_id, exc)
            result = CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"capability:{capability_id}"),
                error=str(exc),
            )
        self._events.append(
            GraphEvent(
                kind=EventKind.CAPABILITY_EXECUTED,
                target_id=f"cap_{capability_id.replace('.', '_')}",
                at=datetime.now(timezone.utc),
                metadata={
                    "capability_id": capability_id,
                    "success": result.success,
                    "latency_ms": result.latency_ms,
                    "error": result.error or None,
                },
            )
        )
        return result

    def _resolve(self, capability_id: str) -> CapabilityBase | None:
        """Resolve capability_id para instância, com cache."""
        if capability_id in self._cache:
            return self._cache[capability_id]

        fqn = _BUILTIN_CAPABILITIES.get(capability_id)
        if not fqn:
            return None

        try:
            module_path, class_name = fqn.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            instance = cls()
            self._cache[capability_id] = instance
            return instance
        except Exception as exc:
            logger.warning("falha ao carregar capability %s: %s", capability_id, exc)
            return None
