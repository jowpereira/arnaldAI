"""Testes para consistência de entrypoints (chat.py vs cli/main.py)."""

from __future__ import annotations

import ast
from pathlib import Path


_PROJECT_ROOT = Path(__file__).parent.parent


def _find_kernel_run_calls(filepath: Path) -> list[dict[str, bool]]:
    """Extrai chamadas kernel.run() e seus kwargs de um arquivo Python."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls: list[dict[str, bool]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Detecta kernel.run(...) ou self.kernel.run(...)
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "run":
            kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
            calls.append(
                {
                    "has_llm_classify": "llm_classify" in kwargs,
                    "has_autonomy": "autonomy" in kwargs,
                    "has_output_dir": "output_dir" in kwargs,
                    "has_session_id": "session_id" in kwargs,
                }
            )
    return calls


def test_chat_entrypoint_passes_llm_classify() -> None:
    """chat.py deve passar llm_classify=True ao kernel.run()."""
    chat_path = _PROJECT_ROOT / "arnaldo" / "chat.py"
    calls = _find_kernel_run_calls(chat_path)
    assert any(c["has_llm_classify"] for c in calls), (
        "chat.py não passa llm_classify ao kernel.run()"
    )


def test_cli_entrypoint_passes_llm_classify() -> None:
    """cli/main.py deve passar llm_classify=True ao kernel.run()."""
    cli_path = _PROJECT_ROOT / "arnaldo" / "cli" / "main.py"
    calls = _find_kernel_run_calls(cli_path)
    assert any(c["has_llm_classify"] for c in calls), (
        "cli/main.py não passa llm_classify ao kernel.run()"
    )


def test_both_entrypoints_pass_same_core_params() -> None:
    """Ambos entrypoints devem passar autonomy, output_dir, session_id."""
    chat_path = _PROJECT_ROOT / "arnaldo" / "chat.py"
    cli_path = _PROJECT_ROOT / "arnaldo" / "cli" / "main.py"

    chat_calls = _find_kernel_run_calls(chat_path)
    cli_calls = _find_kernel_run_calls(cli_path)

    assert chat_calls, "chat.py não tem chamadas kernel.run()"
    assert cli_calls, "cli/main.py não tem chamadas kernel.run()"

    for param in ("has_autonomy", "has_output_dir", "has_session_id"):
        assert any(c[param] for c in chat_calls), f"chat.py falta {param}"
        assert any(c[param] for c in cli_calls), f"cli/main.py falta {param}"
