"""Hook PostToolUse — auto-format com ruff + guard de 300 linhas.

Executa após cada edição de arquivo pelo agente:
1. Roda `ruff format` no arquivo editado (se Python)
2. Roda `ruff check` no arquivo editado (se Python)
3. Verifica se o arquivo excede 300 linhas (regra 14)
"""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({"continue": True}))
        return

    data = json.loads(raw)
    tool_name = data.get("tool_name", "")

    # Só atua em ferramentas de edição de arquivo
    edit_tools = {"editFiles", "createFile", "create_file", "replace_string_in_file"}
    if tool_name not in edit_tools:
        print(json.dumps({"continue": True}))
        return

    tool_input = data.get("tool_input", {})
    file_path = _extract_file_path(tool_input)
    if not file_path or not file_path.endswith(".py"):
        print(json.dumps({"continue": True}))
        return

    messages: list[str] = []

    # 1. Auto-format com ruff
    fmt_result = subprocess.run(
        ["uv", "run", "ruff", "format", file_path],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if fmt_result.returncode == 0:
        messages.append(f"ruff format: {file_path}")

    # 2. Lint check com ruff
    check_result = subprocess.run(
        ["uv", "run", "ruff", "check", file_path],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if check_result.returncode != 0 and check_result.stdout.strip():
        messages.append(f"ruff check encontrou problemas:\n{check_result.stdout.strip()}")

    # 3. Guard de 300 linhas (regra 14)
    try:
        with open(file_path, encoding="utf-8") as f:
            line_count = sum(1 for _ in f)
        if line_count > 300:
            messages.append(
                f"VIOLAÇÃO REGRA 14: {file_path} tem {line_count} linhas (máximo: 300). "
                "Extraia responsabilidades para módulos menores."
            )
    except OSError:
        pass

    output: dict = {"continue": True}
    if messages:
        output["hookSpecificOutput"] = {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(messages),
        }
    print(json.dumps(output))


def _extract_file_path(tool_input: dict) -> str | None:
    """Extrai o path do arquivo de diferentes formatos de tool_input."""
    # editFiles / replace_string_in_file
    if "filePath" in tool_input:
        return tool_input["filePath"]
    # createFile
    if "file_path" in tool_input:
        return tool_input["file_path"]
    # editFiles com lista de files
    files = tool_input.get("files", [])
    if files and isinstance(files[0], str):
        return files[0]
    if files and isinstance(files[0], dict):
        return files[0].get("filePath") or files[0].get("file_path")
    return None


if __name__ == "__main__":
    main()
