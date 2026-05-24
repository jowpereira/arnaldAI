"""Thinking events — feedback de processamento em tempo real."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from arnaldo.utils.time import utc_now

logger = logging.getLogger("arnaldo.kernel.thinking")


class ThinkingKind(str, Enum):
    """Tipos de evento de pensamento."""

    SEARCHING = "searching"
    ANALYZING = "analyzing"
    RESOLVING = "resolving"
    CLASSIFYING = "classifying"


@dataclass(frozen=True, slots=True)
class ThinkingEvent:
    """Evento de pensamento — emitido quando o kernel está processando."""

    kind: ThinkingKind
    message: str
    query: str = ""
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


# Callback type: função que recebe ThinkingEvent
ThinkingCallback = Callable[[ThinkingEvent], None]


class ThinkingEmitter:
    """Emite eventos de pensamento para callbacks registrados."""

    def __init__(self) -> None:
        self._callbacks: list[ThinkingCallback] = []

    def register(self, callback: ThinkingCallback) -> None:
        """Registra callback para receber eventos."""
        self._callbacks.append(callback)

    def reset(self) -> None:
        """Remove todos os callbacks — chamado no início de cada run."""
        self._callbacks.clear()

    def emit(self, event: ThinkingEvent) -> None:
        """Emite evento para todos os callbacks."""
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception as exc:
                logger.debug("Thinking callback error: %s", exc)

    def searching(self, query: str, *, source: str = "web") -> None:
        """Shortcut: emite evento de pesquisa."""
        self.emit(
            ThinkingEvent(
                kind=ThinkingKind.SEARCHING,
                message=f"Pesquisando: {query[:100]}...",
                query=query,
                metadata={"source": source},
            )
        )

    def analyzing(self, context: str) -> None:
        """Shortcut: emite evento de análise."""
        self.emit(
            ThinkingEvent(
                kind=ThinkingKind.ANALYZING,
                message=f"Analisando: {context[:100]}...",
            )
        )

    def resolving(self, what: str) -> None:
        """Shortcut: emite evento de resolução."""
        self.emit(
            ThinkingEvent(
                kind=ThinkingKind.RESOLVING,
                message=f"Resolvendo: {what[:100]}...",
            )
        )

    @property
    def has_listeners(self) -> bool:
        return len(self._callbacks) > 0
