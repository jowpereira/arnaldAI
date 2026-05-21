"""CLI do Arnaldo — interface de linha de comando com streaming e proatividade.

Usage::

    from arnaldo.cli import main
    main()

Ou via CLI::

    uv run python -m arnaldo "Crie um plano"
    uv run python -m arnaldo --chat
"""

from __future__ import annotations

from .main import main, run_chat_loop, run_with_live_streaming
from .output import build_run_summary, print_chat_result, print_run_result, print_runtime_error
from .builders import build_agent_response_preview, build_chat_response
from .streaming import RunStreamer, ProactiveNotifier
from .utils import (
    discover_new_run_dir,
    list_run_dir_names,
    safe_pending_proactive_count,
    safe_read_json,
    safe_read_jsonl,
)

# Backward compat aliases (usados por testes antigos via `cli._nome`)
_build_agent_response_preview = build_agent_response_preview
_discover_new_run_dir = discover_new_run_dir
_RunStreamer = RunStreamer

__all__ = [
    "main",
    "run_chat_loop",
    "run_with_live_streaming",
    "print_chat_result",
    "print_run_result",
    "print_runtime_error",
    "build_run_summary",
    "build_agent_response_preview",
    "build_chat_response",
    "RunStreamer",
    "ProactiveNotifier",
]
