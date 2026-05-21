"""GraphRuntime — runtime baseado em CognitiveGraph + ExecutionEngine tipado.

Módulo principal mantém a classe GraphRuntime com __init__, set_seed_graph e run().
Lógica extraída em módulos irmãos:
  graph_runtime_models      — dataclasses + constantes
  graph_runtime_classify    — classificação de tarefas e defaults
  graph_runtime_workflow    — materialização de workflow
  graph_runtime_build       — construção do grafo de execução
  graph_runtime_capabilities — gestão de capabilities
  graph_runtime_nodes       — operações de nó/aresta/memória
  graph_runtime_evolution   — evolução de capabilities + orquestrador
  graph_runtime_infra       — utilitários, trace, evidence, sandbox
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from arnaldo.graph import ExecutionEngine, SynapseExecutionResult
from arnaldo.llm import ContractModelRegistry
from arnaldo.storage import RunStore

from ..base import RuntimeAdapter, RuntimeContext, RuntimeResult

from .models import (
    ArtifactDraftOutput,
    CriticReviewOutput,
    GenericStepOutput,
    IntentFrameOutput,
    WorkPlanOutput,
)
from .build import _build_execution_graph
from .workflow import _materialize_runtime_workflow
from .evolution import _evolve_capability_nodes
from .infra import (
    _build_request,
    _load_seed_graph,
    _select_execution_mode,
)
from .postprocess import _finalize_run, _process_execution_results
from .tracing import (
    _bootstrap_step_context,
    _record_prompt_payload,
    _resolve_sandbox_dir,
    _trace,
)


class GraphRuntime(RuntimeAdapter):
    """Runtime baseado em `CognitiveGraph` + `ExecutionEngine` tipado."""

    def __init__(self, llm_client: Any | None = None, strict_real: bool = True) -> None:
        self.llm_client = llm_client
        self.strict_real = bool(strict_real)
        self.seed_graph_path: Path | None = None
        self.contract_registry = ContractModelRegistry()
        self.contract_registry.register_many(
            {
                model.__name__: model
                for model in {
                    IntentFrameOutput,
                    WorkPlanOutput,
                    ArtifactDraftOutput,
                    CriticReviewOutput,
                    GenericStepOutput,
                }
            }
        )

    def set_seed_graph(self, graph_path: str | Path | None) -> None:
        if graph_path is None:
            self.seed_graph_path = None
            return
        self.seed_graph_path = Path(str(graph_path))

    # ------------------------------------------------------------------
    # Delegate stubs — métodos chamados diretamente por testes
    # ------------------------------------------------------------------

    def _materialize_runtime_workflow(
        self,
        *,
        organization: Any,
        task: Any,
        capability_resolution: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        return _materialize_runtime_workflow(
            organization=organization,
            task=task,
            capability_resolution=capability_resolution,
        )

    @staticmethod
    def _build_request(task: Any, capability_resolution: Dict[str, Any]) -> str:
        return _build_request(task, capability_resolution)

    def _build_execution_graph(self, organization, **kwargs):
        return _build_execution_graph(self.contract_registry, organization, **kwargs)

    def _evolve_capability_nodes(self, **kwargs):
        return _evolve_capability_nodes(**kwargs)

    # ------------------------------------------------------------------
    # run() — pipeline principal
    # ------------------------------------------------------------------

    def run(self, context: RuntimeContext, store: RunStore) -> RuntimeResult:
        run_id = context.run_id
        task = context.task
        organization = context.organization
        policy = context.policy
        if self.strict_real and not bool(
            self.llm_client and getattr(self.llm_client, "is_configured", False)
        ):
            raise RuntimeError(
                "strict_real habilitado: GraphRuntime exige LLM configurado (sem fallback)."
            )
        sandbox = context.sandbox or {}
        workspace_path = _resolve_sandbox_dir(sandbox.get("workspace_path"))
        artifacts_path = _resolve_sandbox_dir(sandbox.get("artifacts_path"))
        temp_path = _resolve_sandbox_dir(sandbox.get("temp_path"))

        _trace(
            store,
            run_id,
            "graph_runtime_started",
            {
                "organization_id": organization.id,
                "topology": organization.topology,
                "llm_enabled": bool(
                    self.llm_client and getattr(self.llm_client, "is_configured", False)
                ),
                "sandbox_workspace": sandbox.get("workspace_path", ""),
                "sandbox_artifacts": sandbox.get("artifacts_path", ""),
            },
        )
        if workspace_path:
            (workspace_path / "runtime-session.txt").write_text(
                "run_id=%s\ntask_id=%s\norganization_id=%s\nruntime=graph\n"
                % (run_id, task.id, organization.id),
                encoding="utf-8",
            )
            _trace(
                store,
                run_id,
                "sandbox_prepared",
                {"workspace": str(workspace_path), "artifacts": str(artifacts_path or "")},
            )

        memory_hints = context.memory_hints if isinstance(context.memory_hints, dict) else {}
        if memory_hints:
            _trace(
                store,
                run_id,
                "memory_hints_loaded",
                {
                    "preferred_actions": len(memory_hints.get("preferred_actions", []) or []),
                    "transitions": len(memory_hints.get("transitions", []) or []),
                    "candidate_synapses": len(memory_hints.get("candidate_synapses", []) or []),
                },
            )

        base_graph = _load_seed_graph(self.seed_graph_path)

        # 1.3: sweep_decay pré-run — aplica decay temporal antes de executar
        if base_graph.node_count > 0:
            base_graph.sweep_decay()

        graph, step_by_node, path = _build_execution_graph(
            self.contract_registry,
            organization,
            task=task,
            capability_resolution=context.capability_resolution or {},
            memory_hints=memory_hints,
            graph=base_graph,
        )
        store.write_text("prompts.jsonl", "")
        engine = ExecutionEngine(
            graph=graph,
            llm_client=self.llm_client,
            contract_registry=self.contract_registry,
            strict_real=self.strict_real,
            on_prompt_prepared=lambda payload: _record_prompt_payload(
                store=store,
                run_id=run_id,
                payload=payload,
            ),
        )

        request = _build_request(task, context.capability_resolution or {})
        execution_mode = _select_execution_mode(organization.topology)
        materialized_steps = [
            {
                "index": idx,
                "node_id": node_id,
                **step_by_node[node_id],
            }
            for idx, node_id in enumerate(path, start=1)
            if node_id in step_by_node
        ]
        store.write_json(
            "graph-workflow-materialized.json",
            {
                "topology": organization.topology,
                "execution_mode": execution_mode,
                "root_synapse": path[0] if path else "",
                "step_count": len(materialized_steps),
                "steps": materialized_steps,
            },
        )
        _trace(
            store,
            run_id,
            "graph_workflow_materialized",
            {
                "topology": organization.topology,
                "execution_mode": execution_mode,
                "step_count": len(materialized_steps),
            },
        )
        _trace(
            store,
            run_id,
            "graph_execution_planned",
            {
                "mode": execution_mode,
                "root_synapse": path[0] if path else "",
                "workflow_steps": len(path),
            },
        )

        allowed_node_ids = set(step_by_node.keys())
        step_context, bootstrap_payload = _bootstrap_step_context(
            graph=graph,
            path=path,
        )
        _trace(store, run_id, "graph_context_bootstrapped", bootstrap_payload)
        execution_results: list[SynapseExecutionResult] = []
        if path:
            if execution_mode == "activates_parallel_levels":
                _, step_context, execution_results = engine.execute_activates_parallel(
                    path[0],
                    request=request,
                    context=step_context,
                    max_steps=max(16, len(path) * 3),
                    max_parallel=4,
                    allowed_node_ids=allowed_node_ids,
                )
            else:
                _, step_context, execution_results = engine.execute_activates_reachable(
                    path[0],
                    request=request,
                    context=step_context,
                    max_steps=max(16, len(path) * 3),
                    allowed_node_ids=allowed_node_ids,
                )

        step_results = _process_execution_results(
            execution_results=execution_results,
            step_by_node=step_by_node,
            graph=graph,
            store=store,
            run_id=run_id,
            task=task,
            artifacts_path=artifacts_path,
        )

        return _finalize_run(
            graph=graph,
            store=store,
            run_id=run_id,
            task=task,
            organization=organization,
            policy=policy,
            step_results=step_results,
            step_context=step_context,
            allowed_node_ids=allowed_node_ids,
            artifacts_path=artifacts_path,
            temp_path=temp_path,
        )
