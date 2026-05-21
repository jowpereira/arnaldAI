"""Hook SessionStart — injeta contexto do projeto na conversa.

Fornece ao agente: versão atual, branch git, contagem de testes,
status do grafo e últimas entradas de gotchas.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    # Consome stdin (obrigatório mesmo que não use)
    sys.stdin.read()

    workspace = Path(__file__).resolve().parent.parent.parent.parent
    context_parts: list[str] = []

    # Versão do pyproject.toml
    pyproject = workspace / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version"):
                version = line.split("=", 1)[1].strip().strip('"').strip("'")
                context_parts.append(f"Versão: {version}")
                break

    # Branch git atual
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(workspace),
        )
        if branch.returncode == 0:
            context_parts.append(f"Branch: {branch.stdout.strip()}")
    except (OSError, subprocess.TimeoutExpired):
        pass

    # Contagem de arquivos de teste
    tests_dir = workspace / "tests"
    if tests_dir.exists():
        test_count = len(list(tests_dir.glob("test_*.py")))
        context_parts.append(f"Arquivos de teste: {test_count}")

    # Contagem de módulos
    arnaldo_dir = workspace / "arnaldo"
    if arnaldo_dir.exists():
        py_count = len(list(arnaldo_dir.rglob("*.py")))
        context_parts.append(f"Módulos Python: {py_count}")

    # Últimas gotchas (se existirem)
    gotchas = workspace / ".github" / "memories" / "repo" / "gotchas.md"
    if gotchas.exists():
        content = gotchas.read_text(encoding="utf-8").strip()
        lines = [l for l in content.splitlines() if l.startswith("- [")]
        if lines:
            recent = lines[-3:]  # últimas 3
            context_parts.append("Gotchas recentes: " + " | ".join(recent))

    output = {"continue": True}
    if context_parts:
        output["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": "Contexto do ArnaldAI: " + " | ".join(context_parts),
        }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
