"""Execução de synapses do tipo tooling (módulos dinâmicos)."""

from __future__ import annotations

import importlib.util
import platform
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import ExecutionEngine

from .context import StepContext, SynapseExecutionResult
from ..nodes import SynapseNode

# Nomes de diretórios permitidos para carregamento dinâmico de módulos
_ALLOWED_DIR_NAMES: frozenset[str] = frozenset({"tool_forge", "generated"})
_SHELL_COMMAND_HINTS: tuple[str, ...] = (
    "get-childitem",
    "resolve-path",
    "get-command",
    "test-path",
    "where",
    "which",
    "pwd",
    "ls",
    "dir",
)
_SHELL_FILLER_TOKENS: frozenset[str] = frozenset(
    {
        "a",
        "aqui",
        "agora",
        "ao",
        "as",
        "com",
        "consigo",
        "consegue",
        "da",
        "de",
        "dentro",
        "do",
        "dos",
        "e",
        "em",
        "favor",
        "faz",
        "fazer",
        "fazerum",
        "me",
        "na",
        "nas",
        "no",
        "nos",
        "o",
        "os",
        "ou",
        "para",
        "por",
        "pra",
        "que",
        "tem",
        "um",
        "uma",
        "vc",
        "voce",
        "você",
    }
)
_PATH_HINT_STOPWORDS: frozenset[str] = _SHELL_FILLER_TOKENS | frozenset(
    {
        "arquivo",
        "asta",
        "command",
        "comando",
        "comandos",
        "diretorio",
        "diretório",
        "dir",
        "find",
        "getchilditem",
        "ls",
        "path",
        "pasta",
        "pwd",
        "resolvepath",
        "shell",
        "terminal",
        "where",
        "which",
    }
)


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

    # ── Tentar execução real via CapabilityExecutor PRIMEIRO ──
    if capability_id:
        real_result = _try_real_capability(
            engine,
            node=node,
            tier=tier,
            request=request,
            context=context,
            capability_id=capability_id,
        )
        if real_result is not None:
            return real_result

    # ── Fallback: módulo dinâmico (ToolForge scaffold) ──
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


def _try_real_capability(
    engine: ExecutionEngine,
    *,
    node: SynapseNode,
    tier: str,
    request: str,
    context: StepContext,
    capability_id: str,
) -> SynapseExecutionResult | None:
    """Tenta executar capability via CapabilityExecutor. None = não disponível."""
    try:
        from arnaldo.capabilities import CapabilityExecutor
    except ImportError:
        return None

    executor = CapabilityExecutor()
    if not executor.can_execute(capability_id):
        return None

    # Extrair query do request/contexto
    params = _build_capability_params(capability_id, request, context)
    result = executor.execute(capability_id, params)

    output: dict[str, Any] = {
        "capability_id": capability_id,
        "status": "completed" if result.success else "failed",
        "real_execution": True,
        "data": result.data,
        "source": {
            "kind": result.source.kind.value
            if hasattr(result.source.kind, "value")
            else str(result.source.kind),
            "identifier": result.source.identifier,
        },
        "latency_ms": round(result.latency_ms, 1),
    }
    if result.error:
        output["error"] = result.error

    success = result.success
    with engine._graph_lock:
        engine.graph.record_outcome(node.id, success=success)
        # Proveniência: dado produzido pela capability → DERIVED_FROM
        if success and result.data:
            from .capability_provenance import link_capability_to_memory

            link_capability_to_memory(
                engine.graph,
                capability_id=capability_id,
                node_id=node.id,
                data=result.data,
                request=request,
            )

    context.write(
        node.id,
        output,
        action="execute_tooling",
        agent_id=str(node.payload.get("agent_id", "")),
        capability_id=capability_id,
        channel="tool",
    )
    return SynapseExecutionResult(
        node_id=node.id,
        tier=tier,
        success=success,
        output=output,
    )


def _build_capability_params(
    capability_id: str,
    request: str,
    context: StepContext,
) -> dict[str, Any]:
    """Constrói parâmetros para a capability a partir do request e contexto."""
    request_text = _extract_user_request(request)
    if capability_id.startswith("search."):
        return {"query": request_text or request, "max_results": 5}
    if capability_id.startswith("connector."):
        recent = context.snapshot_recent_outputs(limit=1)
        if recent and isinstance(recent, dict):
            return dict(recent)
        return {"url": request_text or request}
    if capability_id == "filesystem.local.search":
        return _build_filesystem_params(request_text or request)
    if capability_id == "shell.local.readonly":
        return _build_shell_params(request_text or request)
    return {"input": request_text or request}


def _extract_user_request(request: str) -> str:
    for line in str(request).splitlines():
        if line.startswith("UserRequest:") or line.startswith("UserMessage:"):
            return line.split(":", 1)[1].strip()
    return str(request).strip()


def _build_filesystem_params(request_text: str) -> dict[str, Any]:
    matched_root = _match_workspace_path_from_request(request_text)
    pattern = _extract_filesystem_pattern(request_text)
    if matched_root and re.search(
        r"\b(ls|listar|liste|listagem|mostrar|mostre|mostra)\b",
        request_text.lower(),
    ):
        pattern = "*"
    params: dict[str, Any] = {"pattern": pattern}
    if matched_root:
        params["roots"] = [matched_root]
    return params


def _build_shell_params(request_text: str) -> dict[str, Any]:
    command, args = _extract_shell_command(request_text)
    matched_path = _extract_explicit_path(request_text) or _match_workspace_path_from_request(
        request_text
    )
    if not command:
        command = _canonical_shell_command("ls")
    if matched_path and not args:
        args = [matched_path]
    if not args and command in {"dir", "ls", "get-childitem"}:
        args = ["."]
    return {"command": command, "args": args}


def _extract_filesystem_pattern(request_text: str) -> str:
    patterns = (
        r"(?<!\S)(\*+[A-Za-z0-9._-]+\*+|\*+[A-Za-z0-9._-]+|[A-Za-z0-9._-]+\*+)(?!\S)",
        r"[\"']([^\"']{2,80})[\"']",
        r"\b(?:pasta|asta|arquivo|diret[oó]rio|diretorio)\s+([A-Za-z0-9._-]{2,80})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, request_text, flags=re.IGNORECASE):
            candidate = next((group for group in match.groups() if group), "")
            wrapped = _wrap_glob(candidate)
            if wrapped != "*":
                return wrapped
    for token in reversed(_extract_path_hint_tokens(request_text)):
        wrapped = _wrap_glob(token)
        if wrapped != "*":
            return wrapped
    return "*"


def _extract_shell_command(request_text: str) -> tuple[str, list[str]]:
    lowered = request_text.lower()
    for command in _SHELL_COMMAND_HINTS:
        match = re.search(rf"(?<![a-z0-9_-]){re.escape(command)}(?![a-z0-9_-])", lowered)
        if not match:
            continue
        tail = request_text[match.end() :]
        return _canonical_shell_command(command), _extract_shell_args(tail)
    if any(term in lowered for term in ("listar", "liste", "listagem", "mostrar", "mostre")):
        return _canonical_shell_command("ls"), []
    return "", []


def _extract_shell_args(raw_tail: str) -> list[str]:
    args: list[str] = []
    for chunk in re.findall(r'"[^"]+"|\'[^\']+\'|[^\s,;]+', raw_tail):
        cleaned = chunk.strip("`\"' ,.;:!?()[]{}")
        normalized = cleaned.lower()
        if not cleaned or normalized in _SHELL_FILLER_TOKENS:
            continue
        args.append(cleaned)
    return args[:4]


def _canonical_shell_command(command: str) -> str:
    normalized = str(command).strip().lower()
    if platform.system() == "Windows" and normalized == "ls":
        return "dir"
    return normalized


def _wrap_glob(candidate: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "", str(candidate).strip())
    if not cleaned:
        return "*"
    return f"*{cleaned}*"


def _extract_explicit_path(request_text: str) -> str:
    patterns = (
        r"[A-Za-z]:\\[^\s\"'`]+",
        r"(?:/[^\\s\"'`]+)+",
    )
    for pattern in patterns:
        match = re.search(pattern, request_text)
        if match:
            return match.group(0)
    return ""


def _match_workspace_path_from_request(request_text: str) -> str:
    cwd = Path.cwd().resolve()
    candidates = [cwd, *cwd.parents]
    best_path = ""
    best_score = 0.0
    best_depth = -1
    for token in _extract_path_hint_tokens(request_text):
        normalized_token = _normalize_hint_token(token)
        if len(normalized_token) < 3:
            continue
        for candidate in candidates:
            candidate_name = _normalize_hint_token(candidate.name)
            if not candidate_name:
                continue
            score = SequenceMatcher(None, normalized_token, candidate_name).ratio()
            depth = len(candidate.parts)
            if score > best_score or (score == best_score and depth > best_depth):
                best_score = score
                best_depth = depth
                best_path = str(candidate)
    return best_path if best_score >= 0.74 else ""


def _extract_path_hint_tokens(request_text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9._-]{3,}", request_text):
        normalized = _normalize_hint_token(raw)
        if not normalized or normalized in _PATH_HINT_STOPWORDS:
            continue
        tokens.append(raw)
    return tokens


def _normalize_hint_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())
