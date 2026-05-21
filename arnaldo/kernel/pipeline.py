"""Pipeline completo do kernel — execução multi-step fim-a-fim."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from arnaldo.contracts import RunResult, to_dict
from arnaldo.runtime import GraphRuntime, RuntimeContext
from arnaldo.storage import RunStore

from . import organization as _org
from . import session as _session
from .artifacts import build_memory_hints, collect_runtime_outputs, write_pipeline_artifacts
from .retrieval import retrieve_for_request

if TYPE_CHECKING:
    from .kernel import ArnaldoKernel


def run_full_pipeline(
    kernel: ArnaldoKernel,
    *,
    request: str,
    autonomy: str,
    output_dir: Path,
    session_id: str | None,
    terms_accepted: bool | None,
    run_id: str,
    complexity: Any,
) -> RunResult:
    """Executa pipeline completo: compile → plan → execute → postprocess."""
    store = RunStore(output_dir, run_id).create()
    session = _session.open_session(kernel.sessions, session_id, autonomy, terms_accepted)
    adaptive_plan = kernel.adaptive_planner.plan(request, session)
    session = _session.sync_objectives(kernel.sessions, session, adaptive_plan.inferred_objectives)
    session = kernel.sessions.update_preferences(session, adaptive_plan.learning_updates)

    intent = kernel.intent_compiler.compile(
        adaptive_plan.compiled_request, autonomy=session.autonomy_mode
    )
    _session.apply_session_autonomy_overrides(intent.autonomy, intent.constraints, session)

    retrieval = retrieve_for_request(kernel.memory.load_graph(), request)

    task = kernel.task_compiler.compile(intent, retrieval=retrieval)
    _session.inject_task_runtime_context(
        task=task,
        request=request,
        session=session,
        adaptive_plan=adaptive_plan,
    )
    task.capability_needs = kernel.adaptive_planner.merge_capability_hints(
        task.capability_needs, adaptive_plan.capability_hints
    )
    decision = kernel.control_plane.decide(task, retrieval=retrieval)
    capability_resolution = kernel.capabilities.resolve(task.capability_needs)
    tool_forge_report: Dict[str, Any] = {"created": [], "failed": []}
    forge_targets = _session.collect_forge_targets(capability_resolution)
    if forge_targets and adaptive_plan.should_forge_tools:
        tool_forge_report, session = _session.run_tool_forge(
            kernel.tool_forge,
            kernel.capabilities,
            kernel.sessions,
            forge_targets,
            session,
            run_id,
            task.id,
            store,
        )
        capability_resolution = kernel.capabilities.resolve(task.capability_needs)

    organization = kernel._build_runtime_organization(task, decision, capability_resolution)
    policy = _org.evaluate_runtime_policy(
        kernel.runtime,
        kernel.policy,
        kernel.sessions,
        task,
        organization,
        session,
    )
    sandbox = kernel.sandboxes.provision(run_id, session.id, policy_constraints=policy.constraints)

    files = write_pipeline_artifacts(
        store,
        kernel.sessions,
        adaptive_plan,
        intent,
        task,
        decision,
        capability_resolution,
        organization,
        policy,
        sandbox,
        tool_forge_report,
        session,
    )
    _session.evidence(
        store, run_id, task.id, "request_compiled", "Pedido convertido em IRs versionadas."
    )
    memory_hints = build_memory_hints(kernel.memory, request, task, store, files)

    if isinstance(kernel.runtime, GraphRuntime):
        kernel.runtime.set_seed_graph(session.learned_preferences.get("execution_graph_uri"))
    runtime_result = kernel.runtime.run(
        RuntimeContext(
            run_id=run_id,
            task=task,
            organization=organization,
            policy=policy,
            sandbox=to_dict(sandbox),
            capability_resolution=capability_resolution,
            memory_hints=memory_hints,
        ),
        store,
    )
    collect_runtime_outputs(files, store, runtime_result)

    from .postprocess import post_process_run

    session, gap_report = post_process_run(
        store=store,
        run_id=run_id,
        task=task,
        organization=organization,
        session=session,
        runtime_result=runtime_result,
        adaptive_plan=adaptive_plan,
        files=files,
        gap_detector=kernel.gap_detector,
        memory=kernel.memory,
        sessions=kernel.sessions,
        capabilities=kernel.capabilities,
        tool_forge=kernel.tool_forge,
        runtime=kernel.runtime,
        retrieval=retrieval,
        complexity=complexity,
    )

    proactive_scheduled = kernel.proactivity.schedule_from_run(
        session=session,
        task=task,
        adaptive_plan=adaptive_plan,
        run_id=run_id,
    )
    if proactive_scheduled > 0:
        _session.evidence(
            store,
            run_id,
            task.id,
            "proactive_scheduled",
            "Mensagens proativas agendadas para continuidade de sessão.",
            {"count": proactive_scheduled, "session_id": session.id},
        )
    response = kernel._synthesize_response(runtime_result, request)
    session = kernel.sessions.record_turn(
        session,
        user_message=request,
        system_summary=response,
        metadata={
            "run_id": run_id,
            "tool_forge_created": len(tool_forge_report["created"]),
            "missing_capabilities": len(capability_resolution["missing"]),
        },
    )
    files["session_state"] = store.write_json(
        "session-state.json", kernel.sessions.snapshot(session)
    )
    kernel.memory._persist_graph_state()
    return RunResult(
        run_id=run_id,
        run_dir=store.run_dir,
        files=files,
        session_id=session.id,
        response=response,
    )
