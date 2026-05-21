from __future__ import annotations

from arnaldo.storage import RunStore

from .base import RuntimeAdapter, RuntimeContext, RuntimeResult
from .local_render import execute_step, render_artifact
from .tracing import evidence, resolve_sandbox_dir, trace, write_step_artifact


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
        workspace_path = resolve_sandbox_dir(sandbox.get("workspace_path"))
        artifacts_path = resolve_sandbox_dir(sandbox.get("artifacts_path"))
        temp_path = resolve_sandbox_dir(sandbox.get("temp_path"))

        trace(
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
                "run_id=%s\ntask_id=%s\norganization_id=%s\n" % (run_id, task.id, organization.id),
                encoding="utf-8",
            )
            trace(
                store,
                run_id,
                "sandbox_prepared",
                {"workspace": str(workspace_path), "artifacts": str(artifacts_path or "")},
            )
        step_results = []

        for index, item in enumerate(organization.workflow, start=1):
            trace(store, run_id, "step_started", item)
            result = execute_step(task, item)
            step_artifact = write_step_artifact(
                artifacts_path,
                index=index,
                action=item["action"],
                payload=result,
            )
            if step_artifact:
                result["sandbox_artifact"] = str(step_artifact)
            step_results.append(result)
            evidence(
                store,
                run_id,
                task.id,
                "step_completed",
                "Etapa %s executada pelo agente %s." % (item["action"], item["agent_id"]),
                result,
            )
            trace(store, run_id, "step_completed", result)

        artifact = render_artifact(task, organization, policy, step_results)
        artifact_path = store.write_text("artifact.md", artifact)
        sandbox_artifact_path = None
        if artifacts_path:
            sandbox_artifact_path = artifacts_path / "artifact.md"
            sandbox_artifact_path.write_text(artifact, encoding="utf-8")
        evidence(
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
        trace(
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


__all__ = ["LocalRuntime", "execute_step", "render_artifact"]
