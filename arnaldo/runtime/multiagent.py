from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from arnaldo.contracts import (
    utc_now,
)
from arnaldo.storage import RunStore

from .base import RuntimeAdapter, RuntimeContext, RuntimeResult
from .local import execute_step, render_artifact
from .tooling import run_tooling_step
from .tracing import evidence as _evidence_shared, trace as _trace_shared


# ────────────────────────────────────────────────────────────────────────────
# Funções utilitárias do multiagent
# ────────────────────────────────────────────────────────────────────────────


def build_waves(workflow: list[Dict[str, Any]]) -> list[list[tuple[int, Dict[str, Any]]]]:
    parallel_keys = {"explore_paths", "design_tooling", "stabilize_tooling", "execute_tooling"}
    waves: list[list[tuple[int, Dict[str, Any]]]] = []
    current_wave: list[tuple[int, Dict[str, Any]]] = []
    current_key = ""

    for index, item in enumerate(workflow):
        action = str(item.get("action", "")).strip()
        if not action:
            continue
        key = _wave_key(action)
        if not current_wave:
            current_wave = [(index, item)]
            current_key = key
            continue
        if key == current_key and key in parallel_keys:
            current_wave.append((index, item))
            continue
        waves.append(current_wave)
        current_wave = [(index, item)]
        current_key = key

    if current_wave:
        waves.append(current_wave)
    return waves


def _wave_key(action: str) -> str:
    if action in {"explore_path_a", "explore_path_b"}:
        return "explore_paths"
    if action in {"design_tooling", "stabilize_tooling", "execute_tooling"}:
        return action
    return "serial::%s" % action


def snapshot_outputs(shared_outputs: dict[str, Any], *, limit: int = 8) -> dict[str, str]:
    if not shared_outputs:
        return {}
    items = list(shared_outputs.items())[-limit:]
    return {str(key): json.dumps(value, ensure_ascii=True)[:320] for key, value in items}


def _env_positive_int(name: str, *, default: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _trace(store: RunStore, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    _trace_shared(store, run_id, event_type, payload)


def _evidence(
    store: RunStore,
    run_id: str,
    task_id: str,
    record_type: str,
    summary: str,
    payload: Dict[str, Any],
) -> None:
    _evidence_shared(store, run_id, task_id, record_type, summary, payload)


class MultiAgentRuntime(RuntimeAdapter):
    """Runtime distribuído por agente com paralelismo por ondas de ação."""

    def __init__(self) -> None:
        self.enabled = True
        self.provider_config: dict[str, Any] = {}
        self.max_parallel = _env_positive_int("ARNALDO_MULTIAGENT_MAX_PARALLEL", default=4)

    def configure_provider(self, **kwargs: Any) -> None:
        self.provider_config = kwargs
        self.enabled = True

    def run(self, context: RuntimeContext, store: RunStore) -> RuntimeResult:
        if not self.enabled:
            raise RuntimeError("MultiAgentRuntime not configured")

        run_id = context.run_id
        task = context.task
        organization = context.organization
        policy = context.policy

        workflow = [dict(item) for item in organization.workflow]
        waves = build_waves(workflow)
        bus_path = store.write_text("agent_bus.jsonl", "")

        _trace(
            store,
            run_id,
            "multiagent_runtime_started",
            {
                "steps": len(workflow),
                "waves": len(waves),
                "max_parallel": self.max_parallel,
            },
        )

        step_results: list[dict[str, Any]] = []
        shared_outputs: dict[str, Any] = {}

        for wave_index, wave in enumerate(waves, start=1):
            wave_actions = [str(item["action"]) for _, item in wave]
            wave_agents = [str(item["agent_id"]) for _, item in wave]
            _trace(
                store,
                run_id,
                "multiagent_wave_started",
                {
                    "wave_index": wave_index,
                    "size": len(wave),
                    "actions": wave_actions,
                    "agents": wave_agents,
                },
            )

            context_snapshot = snapshot_outputs(shared_outputs)
            if len(wave) == 1:
                index, item = wave[0]
                result, events = self._execute_agent_step(
                    task=task,
                    item=item,
                    wave_index=wave_index,
                    context_snapshot=context_snapshot,
                )
                wave_results = [(index, result, events)]
            else:
                workers = max(1, min(self.max_parallel, len(wave)))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    future_map = {
                        index: executor.submit(
                            self._execute_agent_step,
                            task=task,
                            item=item,
                            wave_index=wave_index,
                            context_snapshot=context_snapshot,
                        )
                        for index, item in wave
                    }
                    wave_results = [
                        (index, *future_map[index].result()) for index in sorted(future_map.keys())
                    ]

            completed = 0
            for _, result, events in wave_results:
                for event in events:
                    store.append_jsonl("agent_bus.jsonl", event)
                step_results.append(result)
                shared_outputs[result["output"]] = result["result"]
                completed += 1
                _evidence(
                    store,
                    run_id,
                    task.id,
                    "step_completed",
                    "Etapa %s executada por %s no runtime multiagente."
                    % (result["action"], result["agent_id"]),
                    result,
                )

            _trace(
                store,
                run_id,
                "multiagent_wave_completed",
                {
                    "wave_index": wave_index,
                    "completed": completed,
                    "size": len(wave),
                },
            )

        artifact = render_artifact(
            task,
            organization,
            policy,
            step_results,
        )
        artifact_path = store.write_text("artifact.md", artifact)

        _trace(
            store,
            run_id,
            "multiagent_runtime_completed",
            {"steps": len(step_results), "artifact": str(artifact_path)},
        )

        return RuntimeResult(
            artifact_path=artifact_path,
            step_results=step_results,
            agent_bus_path=bus_path,
        )

    def _execute_agent_step(
        self,
        *,
        task: Any,
        item: Dict[str, Any],
        wave_index: int,
        context_snapshot: dict[str, str],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        action = str(item.get("action", "")).strip()
        step_id = str(item.get("id", ""))
        agent_id = str(item.get("agent_id", ""))
        output_name = str(item.get("output", ""))
        capability_id = str(item.get("capability_id", "")).strip()

        started = {
            "ts": utc_now(),
            "event": "agent_step_started",
            "wave_index": wave_index,
            "step_id": step_id,
            "agent_id": agent_id,
            "action": action,
            "output": output_name,
            "context_keys": sorted(context_snapshot.keys()),
        }
        if capability_id:
            started["capability_id"] = capability_id

        if action == "execute_tooling":
            result_payload = self._run_tooling_step(
                task=task,
                item=item,
                context_snapshot=context_snapshot,
            )
            result = {
                "step_id": step_id,
                "agent_id": agent_id,
                "action": action,
                "output": output_name,
                "result": result_payload,
                "uncertainties": [entry["question"] for entry in task.uncertainty],
            }
            if capability_id:
                result["capability_id"] = capability_id
        else:
            result = execute_step(task, item)
            result_payload = result.get("result", {})

        completed = {
            "ts": utc_now(),
            "event": "agent_step_completed",
            "wave_index": wave_index,
            "step_id": step_id,
            "agent_id": agent_id,
            "action": action,
            "status": str((result_payload or {}).get("status", "completed")),
            "output": output_name,
        }
        if capability_id:
            completed["capability_id"] = capability_id

        return result, [started, completed]

    def _run_tooling_step(
        self,
        *,
        task: Any,
        item: Dict[str, Any],
        context_snapshot: dict[str, str],
    ) -> dict[str, Any]:
        return run_tooling_step(
            task=task,
            item=item,
            context_snapshot=context_snapshot,
        )
