"""Capability de shell local read-only — allowlist estrita de comandos."""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from .base import CapabilityResult, make_source, timed_execution

# Allowlist estrita: apenas comandos de leitura/descoberta
_ALLOWED_COMMANDS_WINDOWS = frozenset(
    {
        "where",
        "dir",
        "type",
        "get-childitem",
        "test-path",
        "get-command",
        "get-item",
        "get-itempropertyvalue",
        "resolve-path",
        "get-process",
    }
)

_ALLOWED_COMMANDS_POSIX = frozenset(
    {
        "which",
        "ls",
        "find",
        "cat",
        "file",
        "readlink",
        "realpath",
        "stat",
        "uname",
        "ps",
    }
)

_TIMEOUT_SECONDS = 10
_MAX_OUTPUT_CHARS = 5000

# Argumentos proibidos: tokens exatos (match completo, case-insensitive)
_FORBIDDEN_EXACT = frozenset(
    {
        "-delete",
        "--delete",
        "-exec",
        "-execdir",
        "--execdir",
        "-rf",
        "-rm",
        "rm",
        "del",
        "remove-item",
        "erase",
        "format",
        "mkfs",
        "dd",
    }
)

# Operadores proibidos como substring (redireção, pipe)
_FORBIDDEN_OPERATORS = frozenset({">", ">>", "|"})

# Builtins do cmd.exe que precisam de prefixo cmd /c (não são executáveis standalone)
_WINDOWS_CMD_BUILTINS = frozenset({"dir", "type"})


class LocalShellCapability:
    """Executa comandos read-only no shell local com allowlist estrita."""

    capability_id: str = "shell.local.readonly"

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        """Executa comando read-only.

        params:
            command: str — comando a executar (deve estar na allowlist)
            args: list[str] — argumentos (sanitizados)
        """
        command = str(params.get("command", "")).strip().lower()
        args = params.get("args", [])
        if not isinstance(args, list):
            args = [str(args)]
        args = [str(a).strip() for a in args if str(a).strip()]

        # Validação do comando contra allowlist
        allowed = (
            _ALLOWED_COMMANDS_WINDOWS if platform.system() == "Windows" else _ALLOWED_COMMANDS_POSIX
        )
        if command not in allowed:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("shell.local.readonly"),
                error=f"Comando '{command}' não está na allowlist. Permitidos: {sorted(allowed)}",
            )

        # Sanitização de argumentos
        for arg in args:
            arg_lower = arg.lower()
            # Match exato contra tokens proibidos
            if arg_lower in _FORBIDDEN_EXACT:
                return CapabilityResult(
                    success=False,
                    data=None,
                    source=make_source("shell.local.readonly"),
                    error=f"Argumento '{arg}' é uma operação proibida.",
                )
            # Operadores de redireção/pipe (substring — defesa em profundidade)
            if any(op in arg for op in _FORBIDDEN_OPERATORS):
                return CapabilityResult(
                    success=False,
                    data=None,
                    source=make_source("shell.local.readonly"),
                    error=f"Argumento '{arg}' contém operador proibido.",
                )
            if ".." in arg:
                return CapabilityResult(
                    success=False,
                    data=None,
                    source=make_source("shell.local.readonly"),
                    error="Path traversal (..) não é permitido.",
                )

        # Monta e executa comando
        if platform.system() == "Windows" and command in _WINDOWS_CMD_BUILTINS:
            cmd_parts = ["cmd", "/c", command] + args
        else:
            cmd_parts = [command] + args
        try:
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                shell=False,  # NUNCA usar shell=True
            )
            output = result.stdout[:_MAX_OUTPUT_CHARS]
            if result.returncode != 0:
                error_msg = (
                    result.stderr[:1000] if result.stderr else f"exit code {result.returncode}"
                )
                return CapabilityResult(
                    success=False,
                    data={"stdout": output, "stderr": result.stderr[:1000]},
                    source=make_source("shell.local.readonly"),
                    error=error_msg,
                )
            return CapabilityResult(
                success=True,
                data={"stdout": output, "command": " ".join(cmd_parts)},
                source=make_source("shell.local.readonly"),
            )
        except subprocess.TimeoutExpired:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("shell.local.readonly"),
                error=f"Comando excedeu timeout de {_TIMEOUT_SECONDS}s.",
            )
        except FileNotFoundError:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("shell.local.readonly"),
                error=f"Comando '{command}' não encontrado no sistema.",
            )

    def describe(self) -> str:
        return "Executa comandos read-only no shell local (allowlist estrita)."
