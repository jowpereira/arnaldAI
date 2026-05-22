"""Registry de capabilities executáveis — resolve capability_id → executor."""

from __future__ import annotations

import importlib
import logging
from typing import Any

from .base import CapabilityBase, CapabilityResult, make_source

logger = logging.getLogger("arnaldo.capabilities")

# Mapping estático: capability_id → módulo.classe
_BUILTIN_CAPABILITIES: dict[str, str] = {
    "search.public_web": "arnaldo.capabilities.web_search.WebSearchCapability",
    "connector.http.generic": "arnaldo.capabilities.http_connector.HttpConnectorCapability",
}


class CapabilityExecutor:
    """Resolve e executa capabilities por ID."""

    def __init__(self) -> None:
        self._cache: dict[str, CapabilityBase] = {}

    def can_execute(self, capability_id: str) -> bool:
        """Verifica se a capability tem implementação real."""
        return capability_id in _BUILTIN_CAPABILITIES

    def execute(
        self,
        capability_id: str,
        params: dict[str, Any],
    ) -> CapabilityResult:
        """Executa capability pelo ID. Retorna resultado ou erro."""
        executor = self._resolve(capability_id)
        if executor is None:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"capability:{capability_id}"),
                error=f"Capability '{capability_id}' não tem implementação",
            )
        try:
            return executor.execute(params)
        except Exception as exc:
            logger.warning("capability %s falhou: %s", capability_id, exc)
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"capability:{capability_id}"),
                error=str(exc),
            )

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
