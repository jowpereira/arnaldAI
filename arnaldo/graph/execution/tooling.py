"""Execução de synapses do tipo tooling (módulos dinâmicos)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import ExecutionEngine

from .context import StepContext, SynapseExecutionResult
from ..nodes import SynapseNode

# Nomes de diretórios permitidos para carregamento dinâmico de módulos
_ALLOWED_DIR_NAMES: frozenset[str] = frozenset({"tool_forge", "generated"})


def _is_safe_module_path(module_path: Path) -> bool:
    """Valida que o módulo está em diretório com nome permitido e é .py.

    Aceita qualquer path que contenha 'tool_forge' ou 'generated' como
    componente ancestral, evitando carregamento de módulos arbitrários.
    """
    if module_path.suffix != ".py":
        return False
    parts = module_path.resolve().parts
    return any(part in _ALLOWED_DIR_NAMES for part in parts)


def _is_tool_execution_node(node: SynapseNode) -> bool:
    return str(node.payload.get("action", "")).strip() == "execute_tooling"


def _context_snapshot(
    context: StepContext,
    *,
    limit: int = 3,
    capability_id: str = "",
) -> dict[str, Any]:
    return {
        "context_version": context.version,
        "recent_outputs": context.snapshot_recent_outputs(limit=limit),
        "recent_tool_outputs": context.snapshot_recent_tool_outputs(limit=limit),
        "related_outputs": context.snapshot_related_outputs(
            capability_id=capability_id,
            limit=limit,
        ),
    }


def _execute_tooling_synapse(
    engine: ExecutionEngine,
    *,
    node: SynapseNode,
    tier: str,
    request: str,
    context: StepContext,
) -> SynapseExecutionResult:
    capability_id = str(node.payload.get("capability_id", "")).strip()
    module_path_raw = str(node.payload.get("module_path", "")).strip()
    if not module_path_raw:
        if engine.strict_real:
            with engine._graph_lock:
                engine.graph.record_outcome(node.id, success=False)
            error = "execute_tooling sem module_path"
            context.record_error(node.id, error)
            raise RuntimeError(
                f"strict_real habilitado: execute_tooling sem module_path no synapse '{node.id}'."
            )
        with engine._graph_lock:
            engine.graph.record_outcome(node.id, success=False)
        error = "execute_tooling sem module_path"
        context.record_error(node.id, error)
        return SynapseExecutionResult(
            node_id=node.id,
            tier=tier,
            success=False,
            error=error,
        )

    module_path = Path(module_path_raw)
    if not module_path.exists():
        if engine.strict_real:
            with engine._graph_lock:
                engine.graph.record_outcome(node.id, success=False)
            error = "module_path_not_found: %s" % module_path
            context.record_error(node.id, error)
            raise RuntimeError(
                f"strict_real habilitado: module_path não encontrado no synapse "
                f"'{node.id}': {module_path}"
            )
        with engine._graph_lock:
            engine.graph.record_outcome(node.id, success=False)
        error = "module_path_not_found: %s" % module_path
        context.record_error(node.id, error)
        return SynapseExecutionResult(
            node_id=node.id,
            tier=tier,
            success=False,
            error=error,
        )

    if not _is_safe_module_path(module_path):
        with engine._graph_lock:
            engine.graph.record_outcome(node.id, success=False)
        error = "module_path_outside_allowed_roots: %s" % module_path
        context.record_error(node.id, error)
        if engine.strict_real:
            raise RuntimeError(
                f"strict_real: module_path fora dos diretórios permitidos: {module_path}"
            )
        return SynapseExecutionResult(
            node_id=node.id,
            tier=tier,
            success=False,
            error=error,
        )

    try:
        module_name = "arnaldo_tool_%s_%s" % (node.id, abs(hash(str(module_path))))
        spec = importlib.util.spec_from_file_location(module_name, str(module_path))
        if spec is None or spec.loader is None:
            raise RuntimeError("nao foi possivel criar spec para %s" % module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        runner = getattr(module, "run", None)
        if not callable(runner):
            raise RuntimeError("modulo %s nao define funcao run(payload)" % module_path)

        raw_output = runner(
            {
                "request": request,
                "capability_id": capability_id,
                "node_id": node.id,
                "context": _context_snapshot(context, capability_id=capability_id),
            }
        )
        if isinstance(raw_output, dict):
            output = dict(raw_output)
        else:
            output = {"result": raw_output}
        output.setdefault("status", "completed")
        if capability_id:
            output.setdefault("capability_id", capability_id)

        with engine._graph_lock:
            engine.graph.record_outcome(node.id, success=True)
        context.write(
            node.id,
            output,
            action=str(node.payload.get("action", "")),
            agent_id=str(node.payload.get("agent_id", "")),
            capability_id=capability_id,
            channel="tool",
        )
        return SynapseExecutionResult(
            node_id=node.id,
            tier=tier,
            success=True,
            output=output,
        )
    except Exception as exc:
        if engine.strict_real:
            with engine._graph_lock:
                engine.graph.record_outcome(node.id, success=False)
            error = "tool_execution_failed: %s" % exc
            context.record_error(node.id, error)
            raise RuntimeError(
                f"strict_real habilitado: falha em execute_tooling no synapse '{node.id}': {exc}"
            ) from exc
        with engine._graph_lock:
            engine.graph.record_outcome(node.id, success=False)
        error = "tool_execution_failed: %s" % exc
        context.record_error(node.id, error)
        return SynapseExecutionResult(
            node_id=node.id,
            tier=tier,
            success=False,
            error=error,
        )
