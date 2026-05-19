from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
from typing import Any, Dict
import json

from arnaldo.contracts import (
    EvidenceRecord,
    RuntimeEvent,
    new_id,
    to_dict,
    utc_now,
)
from arnaldo.storage import RunStore

from .base import RuntimeAdapter, RuntimeContext, RuntimeResult
from .local import execute_step, render_artifact


class MultiAgentRuntime(RuntimeAdapter):
    """Runtime distribuído por agente com paralelismo por ondas de ação."""

    def __init__(self) -> None:
        self.enabled = True
        self.provider_config: dict[str, Any] = {}
        self.max_parallel = self._env_positive_int("ARNALDO_MULTIAGENT_MAX_PARALLEL", default=4)

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
        waves = self._build_waves(workflow)
        bus_path = store.write_text("agent_bus.jsonl", "")

        self._trace(
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
            self._trace(
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

            context_snapshot = self._snapshot_outputs(shared_outputs)
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
                        (index, *future_map[index].result())
                        for index in sorted(future_map.keys())
                    ]

            completed = 0
            for _, result, events in wave_results:
                for event in events:
                    store.append_jsonl("agent_bus.jsonl", event)
                step_results.append(result)
                shared_outputs[result["output"]] = result["result"]
                completed += 1
                self._evidence(
                    store,
                    run_id,
                    task.id,
                    "step_completed",
                    "Etapa %s executada por %s no runtime multiagente."
                    % (result["action"], result["agent_id"]),
                    result,
                )

            self._trace(
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

        self._trace(
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
        module_path_raw = str(item.get("module_path", "")).strip()
        capability_id = str(item.get("capability_id", "")).strip()
        if not module_path_raw:
            return {
                "status": "not_implemented",
                "reason": "missing_module_path",
                "capability_id": capability_id,
            }

        module_path = Path(module_path_raw)
        if not module_path.exists():
            return {
                "status": "failed",
                "reason": "module_path_not_found",
                "capability_id": capability_id,
                "module_path": str(module_path),
            }

        try:
            module_name = "arnaldo_multiagent_tool_%s" % abs(hash(str(module_path)))
            spec = importlib.util.spec_from_file_location(module_name, str(module_path))
            if spec is None or spec.loader is None:
                raise RuntimeError("nao foi possivel carregar modulo %s" % module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            runner = getattr(module, "run", None)
            if not callable(runner):
                raise RuntimeError("modulo %s nao define run(payload)" % module_path)
            payload = {
                "request": str(task.goal.get("statement", "")),
                "capability_id": capability_id,
                "context": context_snapshot,
            }
            raw = runner(payload)
            if isinstance(raw, dict):
                result = dict(raw)
            else:
                result = {"result": raw}
            result.setdefault("status", "completed")
            if capability_id:
                result.setdefault("capability_id", capability_id)
            result.setdefault("module_path", str(module_path))
            return result
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "capability_id": capability_id,
                "module_path": str(module_path),
            }

    @staticmethod
    def _build_waves(workflow: list[Dict[str, Any]]) -> list[list[tuple[int, Dict[str, Any]]]]:
        parallel_keys = {"explore_paths", "design_tooling", "stabilize_tooling", "execute_tooling"}
        waves: list[list[tuple[int, Dict[str, Any]]]] = []
        current_wave: list[tuple[int, Dict[str, Any]]] = []
        current_key = ""

        for index, item in enumerate(workflow):
            action = str(item.get("action", "")).strip()
            if not action:
                continue
            key = MultiAgentRuntime._wave_key(action)
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

    @staticmethod
    def _wave_key(action: str) -> str:
        if action in {"explore_path_a", "explore_path_b"}:
            return "explore_paths"
        if action in {"design_tooling", "stabilize_tooling", "execute_tooling"}:
            return action
        return "serial::%s" % action

    @staticmethod
    def _snapshot_outputs(shared_outputs: dict[str, Any], *, limit: int = 8) -> dict[str, str]:
        if not shared_outputs:
            return {}
        items = list(shared_outputs.items())[-limit:]
        return {
            str(key): json.dumps(value, ensure_ascii=True)[:320]
            for key, value in items
        }

    @staticmethod
    def _env_positive_int(name: str, *, default: int) -> int:
        raw = str(os.environ.get(name, "")).strip()
        if not raw:
            return default
        try:
            parsed = int(raw)
        except ValueError:
            return default
        return parsed if parsed > 0 else default

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
