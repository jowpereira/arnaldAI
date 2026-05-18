"""Registry canônico para modelos de contrato tipado."""
from __future__ import annotations

import dataclasses as dc
from threading import RLock
from typing import Any


class ContractModelRegistry:
    """Registro thread-safe de modelos dataclass por nome lógico."""

    def __init__(self) -> None:
        self._models: dict[str, type[Any]] = {}
        self._lock = RLock()

    def register(self, model: type[Any], *, name: str | None = None) -> str:
        if not dc.is_dataclass(model):
            raise TypeError(f"{model!r} não é dataclass; contratos devem ser dataclass")
        key = (name or model.__name__).strip()
        if not key:
            raise ValueError("nome do contrato não pode ser vazio")
        with self._lock:
            existing = self._models.get(key)
            if existing is not None and existing is not model:
                raise ValueError(f"contract model '{key}' já registrado com outro tipo")
            self._models[key] = model
        return key

    def register_many(self, models: dict[str, type[Any]] | list[type[Any]]) -> None:
        if isinstance(models, dict):
            for name, model in models.items():
                self.register(model, name=name)
            return
        for model in models:
            self.register(model)

    def resolve(self, name: str) -> type[Any] | None:
        with self._lock:
            return self._models.get(name)

    def has(self, name: str) -> bool:
        return self.resolve(name) is not None

    def snapshot(self) -> dict[str, type[Any]]:
        with self._lock:
            return dict(self._models)


DEFAULT_CONTRACT_REGISTRY = ContractModelRegistry()

