"""Contrato base para capabilities executáveis."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from arnaldo.graph import SourceKind, SourceRecord


@dataclass(slots=True)
class CapabilityResult:
    """Resultado de execução de capability."""

    success: bool
    data: Any
    source: SourceRecord
    latency_ms: float = 0.0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary_for_prompt(self, max_chars: int = 2000) -> str:
        """Resumo formatado para injeção no system prompt do LLM."""
        if not self.success:
            return f"[Capability falhou: {self.error}]"
        text = str(self.data)
        if len(text) > max_chars:
            text = text[:max_chars] + "... [truncado]"
        return text


@runtime_checkable
class CapabilityBase(Protocol):
    """Interface que toda capability deve implementar."""

    capability_id: str

    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        """Executa a capability com os parâmetros fornecidos."""
        ...

    def describe(self) -> str:
        """Descrição para TF-IDF indexing e prompt context."""
        ...


def timed_execution(func: Any) -> Any:
    """Decorator que mede latência de execução."""

    def wrapper(self: Any, params: dict[str, Any]) -> CapabilityResult:
        start = time.monotonic()
        result = func(self, params)
        result.latency_ms = (time.monotonic() - start) * 1000
        return result

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def make_source(identifier: str) -> SourceRecord:
    """Cria SourceRecord para dados de capability externa."""
    return SourceRecord(
        kind=SourceKind.EXTERNAL_AUTHORITY,
        identifier=identifier,
        confidence=0.70,
    )
