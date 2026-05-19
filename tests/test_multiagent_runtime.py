from __future__ import annotations

from pathlib import Path
import json
import tempfile
from types import SimpleNamespace

from arnaldo.components import IntentCompiler, TaskCompiler
from arnaldo.runtime import MultiAgentRuntime, RuntimeContext
from arnaldo.storage import RunStore


def _build_task() -> object:
    intent = IntentCompiler(llm_client=False, strict_real=False).compile(
        "Planejar integração com execução distribuída por agentes",
        autonomy="autonomo",
    )
    return TaskCompiler().compile(intent)


def _build_context(*, run_id: str, workflow: list[dict[str, str]]) -> RuntimeContext:
    task = _build_task()
    organization = SimpleNamespace(
        id="org_multiagent_test",
        topology="parallel_with_synthesis",
        workflow=workflow,
    )
    policy = SimpleNamespace(
        allowed=True,
        approval_required=False,
    )
    return RuntimeContext(
        run_id=run_id,
        task=task,
        organization=organization,
        policy=policy,
        sandbox={},
        capability_resolution={},
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_multiagent_runtime_executes_parallel_exploration_wave_and_records_bus() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        runtime = MultiAgentRuntime()
        workflow = [
            {"id": "step_1", "agent_id": "framer", "action": "frame_intent", "output": "intent_frame"},
            {"id": "step_2", "agent_id": "explorer_a", "action": "explore_path_a", "output": "work_option_a"},
            {"id": "step_3", "agent_id": "explorer_b", "action": "explore_path_b", "output": "work_option_b"},
            {"id": "step_4", "agent_id": "synthesizer", "action": "synthesize_artifact", "output": "primary_artifact"},
        ]
        context = _build_context(run_id="run_multiagent_parallel", workflow=workflow)
        store = RunStore(base / "runs", context.run_id).create()

        result = runtime.run(context, store)

        assert len(list(result.step_results)) == 4
        bus_events = _read_jsonl(result.agent_bus_path or store.path("agent_bus.jsonl"))
        assert len(bus_events) == 8
        started = [event for event in bus_events if event.get("event") == "agent_step_started"]
        explore_starts = [
            event
            for event in started
            if str(event.get("action", "")).startswith("explore_path_")
        ]
        assert len(explore_starts) == 2
        assert len({int(event.get("wave_index", 0)) for event in explore_starts}) == 1


def test_multiagent_runtime_executes_dynamic_tooling_module() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        module_path = base / "connector_runtime.py"
        module_path.write_text(
            """from __future__ import annotations

def run(payload):
    context = payload.get("context", {}) or {}
    return {
        "status": "executed",
        "capability_id": payload.get("capability_id", ""),
        "context_keys": sorted(list(context.keys())),
    }
""",
            encoding="utf-8",
        )

        runtime = MultiAgentRuntime()
        workflow = [
            {"id": "step_1", "agent_id": "framer", "action": "frame_intent", "output": "intent_frame"},
            {
                "id": "step_2",
                "agent_id": "toolrunner_connector_runtime",
                "action": "execute_tooling",
                "output": "tool_exec_connector_runtime",
                "capability_id": "connector.runtime",
                "module_path": str(module_path),
            },
        ]
        context = _build_context(run_id="run_multiagent_tooling", workflow=workflow)
        store = RunStore(base / "runs", context.run_id).create()

        result = runtime.run(context, store)
        step_results = list(result.step_results)
        execute_result = next(item for item in step_results if item["action"] == "execute_tooling")

        assert execute_result["result"]["status"] == "executed"
        assert execute_result["result"]["capability_id"] == "connector.runtime"
        assert "intent_frame" in execute_result["result"]["context_keys"]


def test_multiagent_runtime_handles_missing_tool_module_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        runtime = MultiAgentRuntime()
        workflow = [
            {
                "id": "step_1",
                "agent_id": "toolrunner_connector_missing",
                "action": "execute_tooling",
                "output": "tool_exec_connector_missing",
                "capability_id": "connector.missing",
            }
        ]
        context = _build_context(run_id="run_multiagent_missing_module", workflow=workflow)
        store = RunStore(base / "runs", context.run_id).create()

        result = runtime.run(context, store)
        step_results = list(result.step_results)
        assert len(step_results) == 1
        assert step_results[0]["result"]["status"] == "not_implemented"
        assert step_results[0]["result"]["reason"] == "missing_module_path"
