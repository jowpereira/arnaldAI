"""Normalização de módulos e paths — fonte canônica."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ── Nomes de diretórios permitidos para carregamento dinâmico ─────────────

_ALLOWED_DIR_NAMES: frozenset[str] = frozenset({"tool_forge", "generated"})


def normalize_module_path(value: Any) -> str:
    """Normaliza path de módulo, retornando '' para valores inválidos."""
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    if normalized.lower() in {"none", "null", ""}:
        return ""
    return normalized


def validate_module_path(raw_path: str, *, allowed_dir_names: frozenset[str] | None = None) -> Path:
    """Valida e resolve path de módulo dinâmico contra nomes de diretório permitidos.

    Raises:
        ValueError: Se o path é vazio, não existe, ou não contém diretório permitido.
    """
    if not raw_path.strip():
        raise ValueError("module_path vazio")

    path = Path(raw_path).resolve()
    names = allowed_dir_names or _ALLOWED_DIR_NAMES

    if not path.exists():
        raise ValueError(f"module_path não encontrado: {path}")

    if not path.suffix == ".py":
        raise ValueError(f"module_path deve ser .py: {path}")

    # Verifica se algum componente do path está na lista de nomes permitidos
    if not any(part in names for part in path.parts):
        raise ValueError(
            f"module_path fora dos diretórios permitidos: {path}. Nomes permitidos: {sorted(names)}"
        )

    return path


def sanitize_identifier(value: str) -> str:
    """Sanitiza um identificador para uso seguro em nomes de módulo/arquivo."""
    normalized = value.strip().lower().replace(".", "_")
    sanitized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        return "x"
    # Garante que não começa com dígito
    if sanitized[0].isdigit():
        sanitized = "m_" + sanitized
    return sanitized
