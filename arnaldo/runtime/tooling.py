"""Execução dinâmica de módulos de tooling no runtime multiagente."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict

# Nomes de diretórios permitidos para carregamento dinâmico de módulos
_ALLOWED_DIR_NAMES: frozenset[str] = frozenset({"tool_forge", "generated"})


def _is_safe_module_path(module_path: Path) -> bool:
    """Valida que o módulo está em diretório com nome permitido e é .py."""
    if module_path.suffix != ".py":
        return False
    parts = module_path.resolve().parts
    return any(part in _ALLOWED_DIR_NAMES for part in parts)


def run_tooling_step(
    *,
    task: Any,
    item: Dict[str, Any],
    context_snapshot: dict[str, str],
) -> dict[str, Any]:
    """Carrega e executa um módulo de tooling dinamicamente.

    Localiza o módulo via ``item["module_path"]``, importa-o, e chama
    ``module.run(payload)`` com o contexto da execução.
    """
    module_path_raw = str(item.get("module_path", "")).strip()
    capability_id = str(item.get("capability_id", "")).strip()
    if not module_path_raw:
        return {
            "status": "not_implemented",
            "reason": "missing_module_path",
            "capability_id": capability_id,
        }

    module_path = Path(module_path_raw)
    if not module_path.exists():
        return {
            "status": "failed",
            "reason": "module_path_not_found",
            "capability_id": capability_id,
            "module_path": str(module_path),
        }

    if not _is_safe_module_path(module_path):
        return {
            "status": "failed",
            "reason": "module_path_outside_allowed_roots",
            "capability_id": capability_id,
            "module_path": str(module_path),
        }

    try:
        module_name = "arnaldo_multiagent_tool_%s" % abs(hash(str(module_path)))
        spec = importlib.util.spec_from_file_location(module_name, str(module_path))
        if spec is None or spec.loader is None:
            raise RuntimeError("nao foi possivel carregar modulo %s" % module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        runner = getattr(module, "run", None)
        if not callable(runner):
            raise RuntimeError("modulo %s nao define run(payload)" % module_path)
        payload = {
            "request": str(task.goal.get("statement", "")),
            "capability_id": capability_id,
            "context": context_snapshot,
        }
        raw = runner(payload)
        if isinstance(raw, dict):
            result = dict(raw)
        else:
            result = {"result": raw}
        result.setdefault("status", "completed")
        if capability_id:
            result.setdefault("capability_id", capability_id)
        result.setdefault("module_path", str(module_path))
        return result
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "capability_id": capability_id,
            "module_path": str(module_path),
        }
