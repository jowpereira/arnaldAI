from __future__ import annotations

from pathlib import Path
from typing import Dict

from arnaldo.components import (
    CapabilityRegistry,
    CognitiveControlPlane,
    IntentCompiler,
    OrganizationGenerator,
    PolicyEngine,
    TaskCompiler,
)
from arnaldo.contracts import EvidenceRecord, RunResult, new_id, to_dict, utc_now
from arnaldo.runtime import LocalRuntime
from arnaldo.storage import RunStore


class ArnaldoKernel:
    """Coordinates the generic intent-to-execution pipeline."""

    def __init__(self) -> None:
        self.intent_compiler = IntentCompiler()
        self.task_compiler = TaskCompiler()
        self.control_plane = CognitiveControlPlane()
        self.capabilities = CapabilityRegistry()
        self.organizations = OrganizationGenerator()
        self.policy = PolicyEngine()
        self.runtime = LocalRuntime()

    def run(self, request: str, autonomy: str = "assistido", output_dir: Path = Path("runs")) -> RunResult:
        run_id = new_id("run")
        store = RunStore(output_dir, run_id).create()

        intent = self.intent_compiler.compile(request, autonomy=autonomy)
        task = self.task_compiler.compile(intent)
        decision = self.control_plane.decide(task)
        capability_resolution = self.capabilities.resolve(task.capability_needs)
        organization = self.organizations.generate(task, decision, capability_resolution)
        policy = self.policy.evaluate(task, organization)

        files = {
            "intent_ir": store.write_json("intent-ir.json", to_dict(intent)),
            "task_ir": store.write_json("task-ir.json", to_dict(task)),
            "cognitive_decision": store.write_json("cognitive-decision.json", to_dict(decision)),
            "capability_resolution": store.write_json("capability-resolution.json", capability_resolution),
            "organization_ir": store.write_json("organization-ir.json", to_dict(organization)),
            "policy_decision": store.write_json("policy-decision.json", to_dict(policy)),
        }

        self._evidence(store, run_id, task.id, "request_compiled", "Pedido convertido em IRs versionadas.")
        runtime_result = self.runtime.run(run_id, task, organization, policy, store)
        files["artifact"] = Path(runtime_result["artifact_path"])
        files["trace"] = store.path("trace.jsonl")
        files["evidence"] = store.path("evidence.jsonl")
        files["result"] = store.write_text(
            "result.md",
            render_result(run_id, files, organization.topology),
        )

        return RunResult(run_id=run_id, run_dir=store.run_dir, files=files)

    def _evidence(self, store: RunStore, run_id: str, task_id: str, record_type: str, summary: str) -> None:
        record = EvidenceRecord(
            id=new_id("evidence"),
            run_id=run_id,
            task_id=task_id,
            created_at=utc_now(),
            record_type=record_type,
            summary=summary,
            payload={},
        )
        store.append_jsonl("evidence.jsonl", to_dict(record))


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
- Artifact: `%s`
- Trace: `%s`
- Evidence: `%s`

## Estado
O nucleo local executou o ciclo generico:

```text
intencao -> Intent IR -> Task IR -> decisao cognitiva -> capacidades -> organizacao -> politica -> runtime -> evidencias -> artefato
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
        files["artifact"],
        files["trace"],
        files["evidence"],
    )
