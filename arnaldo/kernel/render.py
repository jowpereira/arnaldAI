"""Renderização do resultado de execução."""

from __future__ import annotations

from pathlib import Path
from typing import Dict


def render_result(run_id: str, files: Dict[str, Path], topology: str) -> str:
    return """# Execucao Arnaldo

## Run
- Id: `%s`
- Topologia: `%s`

## Artefatos
- Intent IR: `%s`
- Task IR: `%s`
- Cognitive Decision: `%s`
- Capability Resolution: `%s`
- Organization IR: `%s`
- Policy Decision: `%s`
- Sandbox State: `%s`
- Artifact: `%s`
- Trace: `%s`
- Evidence: `%s`

## Estado
O nucleo local executou o ciclo generico:

```text
intencao -> Intent IR -> Task IR -> decisao cognitiva ->
capacidades -> organizacao -> politica -> runtime -> evidencias -> artefato
```
""" % (
        run_id,
        topology,
        files["intent_ir"],
        files["task_ir"],
        files["cognitive_decision"],
        files["capability_resolution"],
        files["organization_ir"],
        files["policy_decision"],
        files.get("sandbox_state", Path("")),
        files["artifact"],
        files["trace"],
        files["evidence"],
    )
