from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from arnaldo.contracts import (
    EvidenceRecord,
    RuntimeEvent,
    new_id,
    to_dict,
    utc_now,
)
from arnaldo.storage import RunStore

from .base import RuntimeAdapter, RuntimeContext, RuntimeResult


class LocalRuntime(RuntimeAdapter):
    """Deterministic runtime adapter used before external agent frameworks exist."""

    def run(
        self,
        context: RuntimeContext,
        store: RunStore,
    ) -> RuntimeResult:
        run_id = context.run_id
        task = context.task
        organization = context.organization
        policy = context.policy
        sandbox = context.sandbox or {}
        workspace_path = self._resolve_sandbox_dir(sandbox.get("workspace_path"))
        artifacts_path = self._resolve_sandbox_dir(sandbox.get("artifacts_path"))
        temp_path = self._resolve_sandbox_dir(sandbox.get("temp_path"))

        self._trace(
            store,
            run_id,
            "runtime_started",
            {
                "organization_id": organization.id,
                "sandbox_id": sandbox.get("id", ""),
                "sandbox_workspace": sandbox.get("workspace_path", ""),
                "sandbox_artifacts": sandbox.get("artifacts_path", ""),
                "sandbox_temp": sandbox.get("temp_path", ""),
            },
        )
        if workspace_path:
            (workspace_path / "runtime-session.txt").write_text(
                "run_id=%s\ntask_id=%s\norganization_id=%s\n"
                % (run_id, task.id, organization.id),
                encoding="utf-8",
            )
            self._trace(
                store,
                run_id,
                "sandbox_prepared",
                {"workspace": str(workspace_path), "artifacts": str(artifacts_path or "")},
            )
        step_results = []

        for index, item in enumerate(organization.workflow, start=1):
            self._trace(store, run_id, "step_started", item)
            result = execute_step(task, item)
            step_artifact = self._write_step_artifact(artifacts_path, index, item["action"], result)
            if step_artifact:
                result["sandbox_artifact"] = str(step_artifact)
            step_results.append(result)
            self._evidence(
                store,
                run_id,
                task.id,
                "step_completed",
                "Etapa %s executada pelo agente %s." % (item["action"], item["agent_id"]),
                result,
            )
            self._trace(store, run_id, "step_completed", result)

        artifact = render_artifact(task, organization, policy, step_results)
        artifact_path = store.write_text("artifact.md", artifact)
        sandbox_artifact_path = None
        if artifacts_path:
            sandbox_artifact_path = artifacts_path / "artifact.md"
            sandbox_artifact_path.write_text(artifact, encoding="utf-8")
        self._evidence(
            store,
            run_id,
            task.id,
            "artifact_created",
            "Artefato principal gerado pelo runtime local.",
            {
                "path": str(artifact_path),
                "sandbox_path": str(sandbox_artifact_path or ""),
            },
        )
        if temp_path:
            temp_marker = temp_path / "runtime-finished.txt"
            temp_marker.write_text("completed=true\n", encoding="utf-8")
        self._trace(
            store,
            run_id,
            "runtime_completed",
            {
                "artifact": str(artifact_path),
                "sandbox_artifact": str(sandbox_artifact_path or ""),
            },
        )
        agent_bus = store.write_text("agent_bus.jsonl", "")

        return RuntimeResult(
            artifact_path=artifact_path,
            step_results=step_results,
            agent_bus_path=agent_bus,
        )

    def _trace(self, store: RunStore, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        event = RuntimeEvent(
            id=new_id("event"),
            run_id=run_id,
            created_at=utc_now(),
            event_type=event_type,
            payload=payload,
        )
        store.append_jsonl("trace.jsonl", to_dict(event))

    def _evidence(
        self,
        store: RunStore,
        run_id: str,
        task_id: str,
        record_type: str,
        summary: str,
        payload: Dict[str, Any],
    ) -> None:
        record = EvidenceRecord(
            id=new_id("evidence"),
            run_id=run_id,
            task_id=task_id,
            created_at=utc_now(),
            record_type=record_type,
            summary=summary,
            payload=payload,
        )
        store.append_jsonl("evidence.jsonl", to_dict(record))

    def _resolve_sandbox_dir(self, raw_path: Any) -> Path | None:
        if not raw_path:
            return None
        path = Path(str(raw_path))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_step_artifact(
        self,
        artifacts_path: Path | None,
        index: int,
        action: str,
        payload: Dict[str, Any],
    ) -> Path | None:
        if artifacts_path is None:
            return None
        safe_action = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in action)
        path = artifacts_path / ("step-%02d-%s.json" % (index, safe_action))
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return path


def execute_step(task: TaskIR, item: Dict[str, Any]) -> Dict[str, Any]:
    action = item["action"]
    if action == "frame_intent":
        result = {
            "goal": task.goal["statement"],
            "goal_type": task.goal["type"],
            "constraints": task.constraints,
        }
    elif action in ("decompose_work", "explore_path_a", "explore_path_b"):
        result = {
            "steps": [
                "fixar contrato de saida",
                "selecionar capacidades necessarias",
                "executar menor workflow suficiente",
                "validar lacunas e criterios",
            ]
        }
    elif action in ("draft_artifact", "synthesize_artifact"):
        result = {
            "sections": [
                "objetivo",
                "plano de execucao",
                "criterios de sucesso",
                "evidencias",
                "proximas acoes",
            ]
        }
    elif action == "critic_review":
        result = {
            "status": "passed_with_warnings",
            "warnings": [
                "runtime local ainda nao usa ferramentas externas",
                "evidencias atuais sao internas ao processo",
            ],
        }
    else:
        result = {"status": "completed"}

    return {
        "step_id": item["id"],
        "agent_id": item["agent_id"],
        "action": action,
        "output": item["output"],
        "result": result,
        "uncertainties": [entry["question"] for entry in task.uncertainty],
    }


def render_artifact(
    task: TaskIR,
    organization: OrganizationIR,
    policy: PolicyDecision,
    step_results: List[Dict[str, Any]],
) -> str:
    workflow_lines = "\n".join(
        "- `%s` por `%s` -> `%s`" % (step["action"], step["agent_id"], step["output"])
        for step in organization.workflow
    )
    criteria_lines = "\n".join(
        "- `%s`: %s" % (item["id"], item["description"])
        for item in task.success_criteria
    )
    uncertainty_lines = "\n".join(
        "- %s" % item["question"]
        for item in task.uncertainty
    ) or "- nenhuma incerteza relevante marcada neste corte"
    result_lines = "\n".join(
        "- `%s`: %s" % (item["action"], item["output"])
        for item in step_results
    )

    return """# Artifact

## Goal
%s

## Generic Execution Contract
- Goal type: `%s`
- Topology: `%s`
- Policy allowed: `%s`
- Approval required: `%s`

## Workflow
%s

## Step Outputs
%s

## Success Criteria
%s

## Uncertainties
%s

## Next Actions
- conectar um provider de raciocinio opcional mantendo fallback local
- adicionar validacao de schema para cada IR
- registrar capacidades reais no Capability Registry
""" % (
        task.goal["statement"],
        task.goal["type"],
        organization.topology,
        policy.allowed,
        policy.approval_required,
        workflow_lines,
        result_lines,
        criteria_lines,
        uncertainty_lines,
    )
