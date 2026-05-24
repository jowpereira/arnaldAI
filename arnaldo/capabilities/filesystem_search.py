"""Capability de busca em filesystem local — read-only, segura."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

from .base import CapabilityResult, make_source, timed_execution


# Diretórios comuns por plataforma para busca
_WINDOWS_SEARCH_ROOTS = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
    Path(os.environ.get("LOCALAPPDATA", "")),
    Path(os.environ.get("APPDATA", "")),
    Path(os.environ.get("USERPROFILE", "")),
]

_POSIX_SEARCH_ROOTS = [
    Path("/usr/local"),
    Path("/opt"),
    Path.home(),
    Path.home() / ".local",
]

_MAX_RESULTS = 20
_MAX_DEPTH = 4


class FilesystemSearchCapability:
    """Busca arquivos/diretórios por padrão glob — read-only."""

    capability_id: str = "filesystem.local.search"

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        """Busca por padrão no filesystem local.

        params:
            pattern: str — glob pattern (ex: "*mt5*", "*.exe")
            roots: list[str] | None — diretórios raiz opcionais
            max_depth: int — profundidade máxima (default 4)
        """
        pattern = str(params.get("pattern", "")).strip()
        if not pattern:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("filesystem.local.search"),
                error="Parâmetro 'pattern' é obrigatório.",
            )

        # Sanitização: rejeita path traversal e chars perigosos
        if ".." in pattern or any(c in pattern for c in (";", "|", "&", "`", "$")):
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("filesystem.local.search"),
                error="Padrão contém caracteres não permitidos.",
            )

        max_depth = min(int(params.get("max_depth", _MAX_DEPTH)), 6)
        custom_roots = params.get("roots")
        if custom_roots and isinstance(custom_roots, list):
            roots = [Path(r) for r in custom_roots if isinstance(r, str)]
        else:
            roots = _get_platform_roots()

        found: list[dict[str, str]] = []
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            _search_recursive(root, pattern, max_depth, 0, found)
            if len(found) >= _MAX_RESULTS:
                break

        return CapabilityResult(
            success=True,
            data={"matches": found[:_MAX_RESULTS], "pattern": pattern},
            source=make_source("filesystem.local.search"),
            metadata={"roots_searched": [str(r) for r in roots], "total": len(found)},
        )

    def describe(self) -> str:
        return "Busca arquivos e diretórios no filesystem local por padrão glob."


def _get_platform_roots() -> list[Path]:
    """Retorna raízes de busca para a plataforma atual."""
    if platform.system() == "Windows":
        return [r for r in _WINDOWS_SEARCH_ROOTS if str(r)]
    return [r for r in _POSIX_SEARCH_ROOTS if str(r)]


def _search_recursive(
    root: Path,
    pattern: str,
    max_depth: int,
    current_depth: int,
    results: list[dict[str, str]],
    *,
    _boundary: Path | None = None,
) -> None:
    """Busca recursiva com limite de profundidade e resultados.

    Não segue symlinks e valida que paths resolvidos permanecem sob root.
    """
    if current_depth > max_depth or len(results) >= _MAX_RESULTS:
        return
    boundary = _boundary or root.resolve()
    try:
        for entry in root.iterdir():
            if len(results) >= _MAX_RESULTS:
                return
            try:
                # Segurança: nunca seguir symlinks
                if entry.is_symlink():
                    continue
                # Validar que path resolvido permanece sob boundary
                try:
                    resolved = entry.resolve(strict=False)
                    if not str(resolved).startswith(str(boundary)):
                        continue
                except (ValueError, OSError):
                    continue
                name_lower = entry.name.lower()
                pattern_lower = pattern.lower().replace("*", "")
                if pattern_lower in name_lower:
                    results.append(
                        {
                            "path": str(entry),
                            "name": entry.name,
                            "type": "dir" if entry.is_dir() else "file",
                        }
                    )
                if entry.is_dir() and current_depth < max_depth:
                    _search_recursive(
                        entry, pattern, max_depth, current_depth + 1, results,
                        _boundary=boundary,
                    )
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        return
