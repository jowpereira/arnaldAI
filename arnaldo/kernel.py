from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Dict, Tuple
import copy

from arnaldo.components import (
    AdaptivePlanner,
    CapabilityRegistry,
    CognitiveControlPlane,
    IntentCompiler,
    OrganizationGenerator,
    PolicyEngine,
    TaskCompiler,
    ToolForge,
)
from arnaldo.contracts import (
    AgentGenome,
    Capability,
    CognitiveDecision,
    EvidenceRecord,
    OrganizationIR,
    PolicyDecision,
    RunResult,
    TaskIR,
    new_id,
    to_dict,
    utc_now,
)
from arnaldo.memory import MemoryStore, MemoryRecord
from arnaldo.reality import RealityGapDetector
from arnaldo.runtime import (
    GraphRuntime,
    LocalRuntime,
    MultiAgentRuntime,
    RuntimeAdapter,
    RuntimeContext,
    SandboxManager,
)
from arnaldo.session import SessionManager, SessionState
from arnaldo.storage import RunStore


class ArnaldoKernel:
    """Coordinates the intent-to-execution pipeline."""

    def __init__(
        self,
        runtime: RuntimeAdapter | None = None,
        runtime_mode: str | None = None,
        memory: MemoryStore | None = None,
        session_manager: SessionManager | None = None,
        planner: AdaptivePlanner | None = None,
        tool_forge: ToolForge | None = None,
        capabilities: CapabilityRegistry | None = None,
        sandbox_manager: SandboxManager | None = None,
    ) -> None:
        self.intent_compiler = IntentCompiler()
        self.task_compiler = TaskCompiler()
        self.control_plane = CognitiveControlPlane()
        self.capabilities = capabilities or CapabilityRegistry()
        self.organizations = OrganizationGenerator()
        self.policy = PolicyEngine()
        self.adaptive_planner = planner or AdaptivePlanner()
        self.sessions = session_manager or SessionManager()
        self.tool_forge = tool_forge or ToolForge()
        self.runtime = runtime or self._build_runtime(runtime_mode)
        self.gap_detector = RealityGapDetector()
        self.memory = memory or MemoryStore()
        self.sandboxes = sandbox_manager or SandboxManager()

    def run(
        self,
        request: str,
        autonomy: str = "assistido",
        output_dir: Path = Path("runs"),
        session_id: str | None = None,
        terms_accepted: bool | None = None,
    ) -> RunResult:
        run_id = new_id("run")
        store = RunStore(output_dir, run_id).create()

        session = self._open_session(session_id, autonomy, terms_accepted)
        adaptive_plan = self.adaptive_planner.plan(request, session)
        session = self._sync_objectives(session, adaptive_plan.inferred_objectives)
        session = self.sessions.update_preferences(session, adaptive_plan.learning_updates)

        intent = self.intent_compiler.compile(adaptive_plan.compiled_request, autonomy=session.autonomy_mode)
        self._apply_session_autonomy_overrides(intent.autonomy, intent.constraints, session)
        task = self.task_compiler.compile(intent)
        task.capability_needs = self.adaptive_planner.merge_capability_hints(task.capability_needs, adaptive_plan.capability_hints)
        decision = self.control_plane.decide(task)
        capability_resolution = self.capabilities.resolve(task.capability_needs)
        tool_forge_report = {"created": [], "failed": []}
        forge_targets = self._collect_forge_targets(capability_resolution)
        if forge_targets and adaptive_plan.should_forge_tools:
            tool_forge_report, session = self._run_tool_forge(forge_targets, session, run_id, task.id, store)
            capability_resolution = self.capabilities.resolve(task.capability_needs)

        organization = self._build_runtime_organization(task, decision, capability_resolution)
        policy = self._evaluate_runtime_policy(task, organization, session)
        sandbox = self.sandboxes.provision(run_id, session.id, policy_constraints=policy.constraints)

        files = {
            "adaptive_plan": store.write_json("adaptive-plan.json", to_dict(adaptive_plan)),
            "intent_ir": store.write_json("intent-ir.json", to_dict(intent)),
            "task_ir": store.write_json("task-ir.json", to_dict(task)),
            "cognitive_decision": store.write_json("cognitive-decision.json", to_dict(decision)),
            "capability_resolution": store.write_json("capability-resolution.json", capability_resolution),
            "organization_ir": store.write_json("organization-ir.json", to_dict(organization)),
            "policy_decision": store.write_json("policy-decision.json", to_dict(policy)),
            "sandbox_state": store.write_json("sandbox-state.json", to_dict(sandbox)),
            "session_state": store.write_json("session-state.json", self.sessions.snapshot(session)),
        }
        if tool_forge_report["created"] or tool_forge_report["failed"]:
            files["tool_forge_report"] = store.write_json("tool-forge-report.json", tool_forge_report)

        self._evidence(store, run_id, task.id, "request_compiled", "Pedido convertido em IRs versionadas.")
        if isinstance(self.runtime, GraphRuntime):
            self.runtime.set_seed_graph(session.learned_preferences.get("execution_graph_uri"))
        runtime_result = self.runtime.run(
            RuntimeContext(
                run_id=run_id,
                task=task,
                organization=organization,
                policy=policy,
                sandbox=to_dict(sandbox),
                capability_resolution=capability_resolution,
            ),
            store,
        )
        files["artifact"] = runtime_result.artifact_path
        files["trace"] = store.path("trace.jsonl")
        files["evidence"] = store.path("evidence.jsonl")
        prompts = store.path("prompts.jsonl")
        if prompts.exists():
            files["prompts"] = prompts
        graph_workflow = store.path("graph-workflow-materialized.json")
        if graph_workflow.exists():
            files["graph_workflow_materialized"] = graph_workflow
        execution_graph = store.path("execution-graph.msgpack")
        if execution_graph.exists():
            files["execution_graph"] = execution_graph
            session = self.sessions.update_preferences(
                session,
                {"execution_graph_uri": str(execution_graph)},
            )
            if isinstance(self.runtime, GraphRuntime):
                graph_sync_report, session = self._sync_capabilities_from_graph(
                    execution_graph,
                    session=session,
                    run_id=run_id,
                    task_id=task.id,
                    store=store,
                )
                graph_tool_forge_report = {"candidates": [], "created": [], "failed": [], "skipped": []}
                if adaptive_plan.should_forge_tools:
                    graph_tool_forge_report, session = self._auto_forge_graph_capabilities(
                        graph_path=execution_graph,
                        sync_report=graph_sync_report,
                        session=session,
                        run_id=run_id,
                        task_id=task.id,
                        store=store,
                    )
                    if graph_tool_forge_report["created"] or graph_tool_forge_report["failed"]:
                        graph_sync_report, session = self._sync_capabilities_from_graph(
                            execution_graph,
                            session=session,
                            run_id=run_id,
                            task_id=task.id,
                            store=store,
                        )
                if graph_sync_report["synced"] or graph_sync_report["skipped"]:
                    files["graph_capability_sync"] = store.write_json(
                        "graph-capability-sync.json",
                        graph_sync_report,
                    )
                if (
                    graph_tool_forge_report["candidates"]
                    or graph_tool_forge_report["created"]
                    or graph_tool_forge_report["failed"]
                    or graph_tool_forge_report["skipped"]
                ):
                    files["graph_tool_forge"] = store.write_json(
                        "graph-tool-forge.json",
                        graph_tool_forge_report,
                    )
        if runtime_result.agent_bus_path:
            files["agent_bus"] = runtime_result.agent_bus_path
        files["result"] = store.write_text(
            "result.md",
            render_result(run_id, files, organization.topology),
        )
        gap_report = self.gap_detector.analyze(task, list(runtime_result.step_results))
        if gap_report.status != "ok":
            self._evidence(
                store,
                run_id,
                task.id,
                "reality_gap_detected",
                ",".join(gap_report.warnings) or "gap_detected",
            )

        self._remember(run_id, task.goal, files, session.id, adaptive_plan)
        session = self.sessions.record_turn(
            session,
            user_message=request,
            system_summary="run_executed topology=%s artifact=%s" % (organization.topology, files["artifact"]),
            metadata={
                "run_id": run_id,
                "tool_forge_created": len(tool_forge_report["created"]),
                "missing_capabilities": len(capability_resolution["missing"]),
            },
        )
        files["session_state"] = store.write_json("session-state.json", self.sessions.snapshot(session))
        return RunResult(run_id=run_id, run_dir=store.run_dir, files=files, session_id=session.id)

    def _build_runtime_organization(
        self,
        task: TaskIR,
        decision: CognitiveDecision,
        capability_resolution: Dict[str, Any],
    ) -> OrganizationIR:
        if isinstance(self.runtime, GraphRuntime):
            return self._build_graph_native_organization(task, decision, capability_resolution)
        return self.organizations.generate(task, decision, capability_resolution)

    def _build_graph_native_organization(
        self,
        task: TaskIR,
        decision: CognitiveDecision,
        capability_resolution: Dict[str, Any],
    ) -> OrganizationIR:
        topology = self._select_runtime_topology(decision)
        agents = self._build_graph_native_agents(topology, task, capability_resolution)
        required_capabilities = sorted(
            {
                str(item.get("id", "")).strip()
                for item in task.capability_needs
                if str(item.get("id", "")).strip()
            }
            | {
                str(item.get("id", "")).strip()
                for bucket in ("available", "missing", "degraded")
                for item in (capability_resolution.get(bucket, []) or [])
                if str(item.get("id", "")).strip()
            }
        )
        return OrganizationIR(
            version="organization-ir/v0",
            id=new_id("org"),
            created_at=utc_now(),
            task_id=task.id,
            topology=topology,
            agents=agents,
            workflow=[],
            required_capabilities=required_capabilities,
            human_checkpoints=self._build_graph_native_checkpoints(decision, capability_resolution),
        )

    @staticmethod
    def _select_runtime_topology(decision: CognitiveDecision) -> str:
        selected = set(decision.selected_modes)
        if "parallel_exploration" in selected:
            return "parallel_with_synthesis"
        if "adversarial_review" in selected:
            return "pipeline_with_critic"
        return "minimal_pipeline"

    def _build_graph_native_agents(
        self,
        topology: str,
        task: TaskIR,
        capability_resolution: Dict[str, Any],
    ) -> list[AgentGenome]:
        if topology == "parallel_with_synthesis":
            agents = [
                self._graph_agent("framer", "operator", "enquadrar objetivo e critérios executáveis"),
                self._graph_agent("explorer_a", "explorer", "explorar alternativa A de execução"),
                self._graph_agent("explorer_b", "explorer", "explorar alternativa B de execução"),
                self._graph_agent("synthesizer", "synthesizer", "sintetizar alternativas em artefato único"),
                self._graph_agent("critic", "critic", "revisar lacunas e consistência do plano"),
            ]
        elif topology == "pipeline_with_critic":
            agents = [
                self._graph_agent("framer", "operator", "enquadrar objetivo e restrições"),
                self._graph_agent("planner", "operator", "decompor e estruturar execução"),
                self._graph_agent("critic", "critic", "revisar riscos e inconsistências"),
            ]
        else:
            agents = [
                self._graph_agent("operator", "operator", "executar pipeline mínimo orientado a objetivo"),
            ]

        if len(task.uncertainty) >= 2 and not self._has_graph_agent(agents, "clarifier"):
            agents.append(
                self._graph_agent(
                    "clarifier",
                    "analyst",
                    "transformar incertezas em hipóteses e perguntas operacionais",
                )
            )

        if str(task.risk.get("execution_risk", "low")) == "high" and not self._has_graph_agent(agents, "risk_auditor"):
            agents.append(
                self._graph_agent(
                    "risk_auditor",
                    "critic",
                    "isolar riscos críticos e pontos de falha antes da síntese final",
                )
            )

        tooling_capabilities = sorted(
            {
                str(item.get("id", "")).strip()
                for bucket in ("missing", "degraded")
                for item in (capability_resolution.get(bucket, []) or [])
                if str(item.get("id", "")).strip().startswith(("connector.", "tool."))
            }
        )
        for capability_id in tooling_capabilities:
            agent_id = self._toolsmith_agent_for_capability(capability_id)
            if self._has_graph_agent(agents, agent_id):
                continue
            agents.append(
                self._graph_agent(
                    agent_id,
                    "operator",
                    "especificar, forjar e estabilizar a capability dinâmica %s" % capability_id,
                )
            )

        toolrunner_capabilities = sorted(
            {
                str(item.get("id", "")).strip()
                for bucket in ("available", "degraded", "missing")
                for item in (capability_resolution.get(bucket, []) or [])
                if str(item.get("id", "")).strip().startswith(("connector.", "tool."))
                and self._capability_module_path(item)
            }
        )
        for capability_id in toolrunner_capabilities:
            agent_id = self._toolrunner_agent_for_capability(capability_id)
            if self._has_graph_agent(agents, agent_id):
                continue
            agents.append(
                self._graph_agent(
                    agent_id,
                    "operator",
                    "executar e observar em runtime a capability dinâmica %s" % capability_id,
                )
            )

        workflow_composer_targets = sorted(
            {
                str(item.get("id", "")).strip()
                for bucket in ("available", "degraded", "missing")
                for item in (capability_resolution.get(bucket, []) or [])
                if str(item.get("id", "")).strip().startswith(("connector.", "tool."))
            }
        )
        if len(workflow_composer_targets) >= 2 and not self._has_graph_agent(agents, "workflow_composer"):
            agents.append(
                self._graph_agent(
                    "workflow_composer",
                    "synthesizer",
                    "compor dinamicamente os resultados das capacidades de tooling em um fluxo integrado",
                )
            )
        return agents

    @staticmethod
    def _graph_agent(agent_id: str, role: str, objective: str) -> AgentGenome:
        return AgentGenome(
            id=agent_id,
            species="graph_native_worker",
            role=role,
            objective=objective,
            epistemic_style="evidence_first",
            required_capabilities=[],
            forbidden_capabilities=[],
            output_contract={
                "schema": "generic_step_output",
                "required_sections": ["status", "evidence", "uncertainties"],
            },
            validation={
                "require_uncertainty_marking": True,
                "require_evidence_record": True,
            },
            lifecycle={
                "max_iterations": 1,
                "expires_after_task": False,
            },
        )

    @staticmethod
    def _has_graph_agent(agents: list[AgentGenome], agent_id: str) -> bool:
        return any(agent.id == agent_id for agent in agents)

    @staticmethod
    def _toolsmith_agent_for_capability(capability_id: str) -> str:
        slug = re.sub(r"[^a-z0-9_]+", "_", capability_id.strip().lower().replace(".", "_"))
        slug = re.sub(r"_+", "_", slug).strip("_")
        return "toolsmith_%s" % (slug or "x")

    @staticmethod
    def _toolrunner_agent_for_capability(capability_id: str) -> str:
        slug = re.sub(r"[^a-z0-9_]+", "_", capability_id.strip().lower().replace(".", "_"))
        slug = re.sub(r"_+", "_", slug).strip("_")
        return "toolrunner_%s" % (slug or "x")

    @classmethod
    def _capability_module_path(cls, payload: Dict[str, Any]) -> str:
        direct = cls._normalize_module_path(payload.get("module_path"))
        if direct:
            return direct
        policies = payload.get("policies") or {}
        if isinstance(policies, dict):
            return cls._normalize_module_path(policies.get("module_path"))
        return ""

    @staticmethod
    def _build_graph_native_checkpoints(
        decision: CognitiveDecision,
        capability_resolution: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        checkpoints: list[Dict[str, Any]] = []
        if "human_checkpoint" in decision.selected_modes:
            checkpoints.append(
                {
                    "id": new_id("checkpoint"),
                    "reason": "cognitive_control_requested_human_checkpoint",
                    "blocking": True,
                }
            )
        if capability_resolution.get("missing"):
            checkpoints.append(
                {
                    "id": new_id("checkpoint"),
                    "reason": "essential_capability_missing",
                    "blocking": True,
                }
            )
        return checkpoints

    def _evaluate_runtime_policy(
        self,
        task: TaskIR,
        organization: OrganizationIR,
        session: SessionState,
    ) -> PolicyDecision:
        if isinstance(self.runtime, GraphRuntime):
            return self._build_graph_runtime_policy(task, organization, session)
        return self.policy.evaluate(task, organization, session=self.sessions.snapshot(session))

    def _build_graph_runtime_policy(
        self,
        task: TaskIR,
        organization: OrganizationIR,
        session: SessionState,
    ) -> PolicyDecision:
        snapshot = self.sessions.snapshot(session)
        return PolicyDecision(
            version="policy-decision/v0",
            id=new_id("policy"),
            task_id=task.id,
            organization_id=organization.id,
            allowed=True,
            approval_required=False,
            reasons=["graph_runtime_governance_disabled"],
            constraints={
                "network": "read_write",
                "filesystem": "workspace_write",
                "external_messages": "allowed",
                "spend_money": "blocked_unless_budget_defined",
                "unsafe_actions": "blocked",
            },
            escalation_plan={
                "contact": "human_on_demand",
                "channels": ["cli"],
                "timeout_minutes": 240,
            },
            notes=["governance bypass ativo no modo graph"],
            telemetry={
                "runtime_mode": "graph",
                "governance_enabled": False,
                "session_id": snapshot.get("id", ""),
                "terms_accepted": bool(snapshot.get("terms_accepted", False)),
            },
        )

    def _evidence(
        self,
        store: RunStore,
        run_id: str,
        task_id: str,
        record_type: str,
        summary: str,
        payload: Dict[str, Any] | None = None,
    ) -> None:
        record = EvidenceRecord(
            id=new_id("evidence"),
            run_id=run_id,
            task_id=task_id,
            created_at=utc_now(),
            record_type=record_type,
            summary=summary,
            payload=payload or {},
        )
        store.append_jsonl("evidence.jsonl", to_dict(record))

    def _sync_capabilities_from_graph(
        self,
        graph_path: Path,
        *,
        session: SessionState,
        run_id: str,
        task_id: str,
        store: RunStore,
    ) -> Tuple[Dict[str, Any], SessionState]:
        from arnaldo.graph import CapabilityNode, CognitiveGraph, NodeKind

        report: Dict[str, Any] = {"synced": [], "skipped": []}
        try:
            graph = CognitiveGraph.load(graph_path)
        except Exception as exc:
            report["error"] = str(exc)
            return report, session

        seen: set[str] = set()
        current = session
        for node in graph.iter_nodes(kind=NodeKind.CAPABILITY, active_only=False):
            if not isinstance(node, CapabilityNode):
                continue
            capability_id = str(node.payload.get("capability_id") or node.label).strip()
            if not capability_id:
                continue
            if capability_id in seen:
                continue
            seen.add(capability_id)

            if not capability_id.startswith(("connector.", "tool.", "search.")):
                report["skipped"].append(
                    {"id": capability_id, "reason": "non_dynamic_capability"}
                )
                continue

            maturity = str(node.payload.get("maturity", node.maturity)).strip() or "draft"
            module_path = self._normalize_module_path(node.payload.get("module_path"))
            real_execution_successes = self._normalize_positive_int(node.payload.get("real_execution_successes"))
            last_tool_execution_status = str(
                node.payload.get("last_tool_execution_status", "")
            ).strip()
            existing = self.capabilities.get(capability_id)
            if not module_path and existing is not None:
                module_path = self._normalize_module_path(existing.policies.get("module_path"))
            if real_execution_successes <= 0 and existing is not None:
                real_execution_successes = self._normalize_positive_int(
                    existing.policies.get("real_execution_successes")
                )
            if not last_tool_execution_status and existing is not None:
                last_tool_execution_status = str(
                    existing.policies.get("last_tool_execution_status", "")
                ).strip()
            health = self._resolve_capability_health(
                maturity=maturity,
                last_tool_execution_status=last_tool_execution_status,
            )
            policies: Dict[str, Any] = {
                "requires_approval": False,
                "maturity": maturity,
                "source": "execution_graph",
                "graph_node_id": node.id,
            }
            if module_path:
                policies["module_path"] = module_path
            if real_execution_successes > 0:
                policies["real_execution_successes"] = real_execution_successes
            if last_tool_execution_status:
                policies["last_tool_execution_status"] = last_tool_execution_status
            capability = Capability(
                id=capability_id,
                name="Graph %s" % capability_id,
                description="Capability sincronizada do grafo de execução.",
                inputs={"payload": "object"},
                outputs={"status": "object", "data": "object"},
                risk={
                    "level": str(node.payload.get("risk_level", "medium")),
                    "health": health,
                    "reasons": ["graph_runtime_sync"],
                },
                policies=policies,
            )
            self.capabilities.register(capability)
            item = {
                "id": capability_id,
                "maturity": maturity,
                "health": health,
                "graph_node_id": node.id,
            }
            if module_path:
                item["module_path"] = module_path
            if real_execution_successes > 0:
                item["real_execution_successes"] = real_execution_successes
            if last_tool_execution_status:
                item["last_tool_execution_status"] = last_tool_execution_status
            report["synced"].append(item)
            event_metadata: Dict[str, Any] = {"source": "graph_sync", "graph_node_id": node.id}
            if real_execution_successes > 0:
                event_metadata["real_execution_successes"] = real_execution_successes
            if last_tool_execution_status:
                event_metadata["last_tool_execution_status"] = last_tool_execution_status
            current = self.sessions.record_tool_event(
                current,
                capability_id=capability_id,
                status=maturity,
                metadata=event_metadata,
            )

        if report["synced"]:
            self._evidence(
                store,
                run_id,
                task_id,
                "capability_graph_synced",
                "%d capabilities sincronizadas do grafo de execução." % len(report["synced"]),
                {"capabilities": report["synced"]},
            )

        return report, current

    def _auto_forge_graph_capabilities(
        self,
        *,
        graph_path: Path,
        sync_report: Dict[str, Any],
        session: SessionState,
        run_id: str,
        task_id: str,
        store: RunStore,
    ) -> Tuple[Dict[str, Any], SessionState]:
        report: Dict[str, Any] = {"candidates": [], "created": [], "failed": [], "skipped": []}
        candidates: list[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in sync_report.get("synced", []) or []:
            capability_id = str(item.get("id", "")).strip()
            if not capability_id:
                continue
            if capability_id in seen:
                continue
            seen.add(capability_id)
            if not capability_id.startswith(("connector.", "tool.")):
                continue

            maturity = str(item.get("maturity", "")).strip().lower() or "draft"
            module_path = self._normalize_module_path(item.get("module_path"))
            existing = self.capabilities.get(capability_id)
            if not module_path and existing is not None:
                module_path = self._normalize_module_path(existing.policies.get("module_path"))
            if module_path:
                report["skipped"].append({"id": capability_id, "reason": "module_path_already_known"})
                continue

            report["candidates"].append({"id": capability_id, "maturity": maturity})
            candidates.append(
                {
                    "id": capability_id,
                    "reason": "graph_capability_missing_module",
                    "severity": "medium",
                }
            )

        if not candidates:
            return report, session

        forge = self.tool_forge.forge_missing(copy.deepcopy(candidates), session.id)
        current = session
        for capability in forge["capabilities"]:
            self.capabilities.register(capability)
        report["created"] = list(forge["created"])
        report["failed"] = list(forge["failed"])

        for item in report["created"]:
            self._evidence(
                store,
                run_id,
                task_id,
                "graph_tool_forged",
                "tool_forge do grafo criou scaffold para %s" % item["capability_id"],
                {
                    "capability_id": item["capability_id"],
                    "module_path": item.get("module_path", ""),
                    "status": item.get("status", ""),
                },
            )
            current = self.sessions.record_tool_event(
                current,
                capability_id=item["capability_id"],
                status=item.get("status", "draft"),
                metadata={
                    "source": "graph_tool_forge",
                    "module_path": item.get("module_path", ""),
                },
            )

        for item in report["failed"]:
            self._evidence(
                store,
                run_id,
                task_id,
                "graph_tool_forge_failed",
                "tool_forge do grafo falhou para %s" % item["capability_id"],
                {
                    "capability_id": item["capability_id"],
                    "error": item.get("error", ""),
                },
            )
            current = self.sessions.record_tool_event(
                current,
                capability_id=item["capability_id"],
                status="failed",
                metadata={"source": "graph_tool_forge", "error": item.get("error", "")},
            )

        if report["created"]:
            report["graph_update"] = self._apply_forge_results_to_graph(
                graph_path=graph_path,
                created=report["created"],
            )

        return report, current

    def _apply_forge_results_to_graph(
        self,
        *,
        graph_path: Path,
        created: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        from arnaldo.graph import CapabilityNode, CognitiveGraph, NodeKind

        report: Dict[str, Any] = {"updated": [], "missing": []}
        try:
            graph = CognitiveGraph.load(graph_path)
        except Exception as exc:
            report["error"] = str(exc)
            return report

        by_capability: Dict[str, Dict[str, Any]] = {}
        for item in created:
            capability_id = str(item.get("capability_id", "")).strip()
            if capability_id:
                by_capability[capability_id] = item

        touched: set[str] = set()
        for node in graph.iter_nodes(kind=NodeKind.CAPABILITY, active_only=False):
            if not isinstance(node, CapabilityNode):
                continue
            capability_id = str(node.payload.get("capability_id") or node.label).strip()
            metadata = by_capability.get(capability_id)
            if metadata is None:
                continue
            module_path = self._normalize_module_path(metadata.get("module_path"))
            maturity = str(metadata.get("status", "draft")).strip().lower() or "draft"
            if maturity not in set(CapabilityNode.MATURITY_LEVELS):
                maturity = "draft"
            updated = node.with_payload_merge(
                module_path=module_path,
                maturity=maturity,
                risk_level="low" if maturity in {"tested", "trusted"} else "medium",
                state="available",
            )
            assert isinstance(updated, CapabilityNode)
            graph.add_node(updated)
            touched.add(capability_id)
            report["updated"].append(
                {
                    "id": capability_id,
                    "graph_node_id": node.id,
                    "module_path": module_path,
                    "maturity": maturity,
                }
            )

        for capability_id in sorted(by_capability.keys()):
            if capability_id not in touched:
                report["missing"].append({"id": capability_id, "reason": "capability_node_not_found"})

        graph.persist(graph_path)
        return report

    @staticmethod
    def _normalize_module_path(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        normalized = value.strip()
        if normalized.lower() in {"none", "null"}:
            return ""
        return normalized

    @staticmethod
    def _normalize_positive_int(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0

    @staticmethod
    def _resolve_capability_health(*, maturity: str, last_tool_execution_status: str) -> str:
        status = last_tool_execution_status.strip().lower()
        if status in {"failed", "error", "not_implemented", "fallback"}:
            return "degraded"
        return "stable" if maturity in {"tested", "trusted"} else "degraded"

    def _remember(
        self,
        run_id: str,
        task_goal: Dict[str, Any],
        files: Dict[str, Path],
        session_id: str,
        adaptive_plan: Any,
    ) -> None:
        record = MemoryRecord(
            id=run_id,
            kind="episodic",
            payload={
                "run_id": run_id,
                "session_id": session_id,
                "goal": task_goal,
                "artifacts": {key: str(path) for key, path in files.items()},
            },
        )
        self.memory.append(record)
        if adaptive_plan.inferred_objectives:
            self.memory.append(
                MemoryRecord(
                    id=new_id("memory"),
                    kind="semantic",
                    payload={
                        "session_id": session_id,
                        "objectives": adaptive_plan.inferred_objectives,
                    },
                )
            )
        if adaptive_plan.learning_updates:
            self.memory.append(
                MemoryRecord(
                    id=new_id("memory"),
                    kind="procedural",
                    payload={
                        "session_id": session_id,
                        "preferences": adaptive_plan.learning_updates,
                    },
                )
            )

    def _open_session(self, session_id: str | None, autonomy: str, terms_accepted: bool | None) -> SessionState:
        state = self.sessions.open(
            session_id=session_id,
            autonomy_mode=autonomy,
            terms_accepted=bool(terms_accepted),
        )
        if terms_accepted:
            state = self.sessions.accept_terms(state)
        return state

    def _sync_objectives(self, state: SessionState, objectives: Any) -> SessionState:
        current = state
        for item in objectives:
            current = self.sessions.register_objective(current, item)
        return current

    def _apply_session_autonomy_overrides(
        self,
        autonomy: Dict[str, Any],
        constraints: Dict[str, Any],
        session: SessionState,
    ) -> None:
        if not session.terms_accepted:
            return
        if session.governance_profile == "self_managed":
            autonomy["max_level"] = max(int(autonomy.get("max_level", 3)), 6)
            constraints["external_side_effects"] = "allowed_if_policy_compliant"
            constraints["private_data"] = "user_terms_based"

    def _run_tool_forge(
        self,
        missing: Any,
        session: SessionState,
        run_id: str,
        task_id: str,
        store: RunStore,
    ) -> Tuple[Dict[str, Any], SessionState]:
        report = self.tool_forge.forge_missing(copy.deepcopy(missing), session.id)
        for capability in report["capabilities"]:
            self.capabilities.register(capability)
        for item in report["created"]:
            self._evidence(
                store,
                run_id,
                task_id,
                "tool_forged",
                "tool_forge scaffold criado para %s" % item["capability_id"],
            )
            session = self.sessions.record_tool_event(
                session,
                capability_id=item["capability_id"],
                status=item["status"],
                metadata={"module_path": item.get("module_path", "")},
            )
        for item in report["failed"]:
            self._evidence(
                store,
                run_id,
                task_id,
                "tool_forge_failed",
                "tool_forge falhou para %s" % item["capability_id"],
            )
            session = self.sessions.record_tool_event(
                session,
                capability_id=item["capability_id"],
                status="failed",
                metadata={"error": item.get("error", "")},
            )
        return (
            {
                "created": report["created"],
                "failed": report["failed"],
            },
            session,
        )

    @staticmethod
    def _collect_forge_targets(capability_resolution: Dict[str, Any]) -> list[Dict[str, Any]]:
        targets: dict[str, Dict[str, Any]] = {}
        for item in capability_resolution.get("missing", []) or []:
            capability_id = str(item.get("id", "")).strip()
            if not capability_id:
                continue
            targets[capability_id] = {
                "id": capability_id,
                "reason": str(item.get("reason", "capability_not_registered")),
                "severity": str(item.get("severity", "high")),
            }
        for item in capability_resolution.get("degraded", []) or []:
            capability_id = str(item.get("id", "")).strip()
            reason = str(item.get("reason", "")).strip()
            if not capability_id:
                continue
            if reason != "optional_capability_not_registered":
                continue
            if capability_id in targets:
                continue
            targets[capability_id] = {
                "id": capability_id,
                "reason": reason,
                "severity": str(item.get("severity", "low")),
            }
        return [targets[key] for key in sorted(targets.keys())]

    def _build_runtime(self, runtime_mode: str | None) -> RuntimeAdapter:
        mode = (runtime_mode or os.environ.get("ARNALDO_RUNTIME_MODE", "graph")).strip().lower()
        if mode == "graph":
            return GraphRuntime(llm_client=self.intent_compiler._llm_client)
        if mode == "multiagent":
            return MultiAgentRuntime()
        return LocalRuntime()


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
        files.get("sandbox_state", Path("")),
        files["artifact"],
        files["trace"],
        files["evidence"],
    )
