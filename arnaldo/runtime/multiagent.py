from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from arnaldo.contracts import to_dict
from arnaldo.storage import RunStore

from .base import RuntimeAdapter, RuntimeContext, RuntimeResult


class MultiAgentRuntime(RuntimeAdapter):
    """Placeholder runtime that will integrate with external LLM provider."""

    def __init__(self) -> None:
        self.enabled = False

    def configure_provider(self, **kwargs: Any) -> None:
        self.provider_config = kwargs
        self.enabled = True

    def run(self, context: RuntimeContext, store: RunStore) -> RuntimeResult:
        if not self.enabled:
            raise RuntimeError("MultiAgentRuntime not configured")

        # Placeholder: for now fallback to LocalRuntime-like behavior
        from .local import execute_step, render_artifact
        step_results = []
        for item in context.organization.workflow:
            result = execute_step(context.task, item)
            step_results.append(result)

        artifact = render_artifact(
            context.task,
            context.organization,
            context.policy,
            step_results,
        )
        artifact_path = store.write_text("artifact.md", artifact)

        agent_bus = store.write_text("agent_bus.jsonl", "")
        store.append_jsonl("trace.jsonl", to_dict({
            "event": "multiagent_runtime_placeholder",
            "details": {},
        }))

        return RuntimeResult(
            artifact_path=artifact_path,
            step_results=step_results,
            agent_bus_path=agent_bus,
        )
