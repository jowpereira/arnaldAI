"""Kernel principal do ArnaldAI — pipeline intent-to-execution."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

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
    CognitiveDecision,
    OrganizationIR,
    RunResult,
    TaskIR,
    new_id,
)
from arnaldo.memory import MemoryStore
from arnaldo.proactivity import ProactivityManager
from arnaldo.reality import RealityGapDetector
from arnaldo.runtime import (
    GraphRuntime,
    LocalRuntime,
    MultiAgentRuntime,
    RuntimeAdapter,
    SandboxManager,
)
from arnaldo.session import SessionManager

from . import organization as _org
from arnaldo.graph.brain import BrainDecision, activate as brain_activate, BRAIN_CONFIDENCE_THRESHOLD

from .classify import RequestComplexity, classify_request
from .fast_path import fast_response, medium_response
from .pipeline import run_full_pipeline
from .bootstrap import bootstrap_graph
from .metrics import MetricsCollector
from .plasticity import maybe_sweep_decay

logger = logging.getLogger("arnaldo.kernel")


def _resolve_runtime(
    mode_override: str | None,
    llm_client: Any,
) -> RuntimeAdapter:
    mode = (mode_override or os.environ.get("ARNALDO_RUNTIME_MODE", "graph")).strip().lower()
    if mode == "graph":
        return GraphRuntime(llm_client=llm_client)
    if mode == "multiagent":
        return MultiAgentRuntime()
    return LocalRuntime()


def _decision_to_complexity(decision: BrainDecision) -> RequestComplexity:
    """Converte BrainDecision para RequestComplexity (interface legada)."""
    return RequestComplexity(
        decision.complexity,
        f"brain_activated:{decision.primary_synapse or 'none'}",
        skip_full_pipeline=decision.skip_full_pipeline,
        use_retrieval=decision.complexity != "conversational",
        suggested_tier=decision.tier,
        needs_external_data=decision.needs_external_data,
        capability_needs=decision.capability_needs,
    )


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
        proactivity: ProactivityManager | None = None,
    ) -> None:
        # Essenciais — usados em todos os paths
        self.sessions = session_manager or SessionManager()
        self.memory = memory or MemoryStore()
        self.proactivity = proactivity or ProactivityManager()

        # Lazy-init storage — só instanciados no full pipeline
        self._runtime_override = runtime
        self._runtime_mode = runtime_mode
        self._planner_override = planner
        self._tool_forge_override = tool_forge
        self._capabilities_override = capabilities
        self._sandbox_override = sandbox_manager

        # Lazy cache
        self._intent_compiler: IntentCompiler | None = None
        self._task_compiler: TaskCompiler | None = None
        self._control_plane_inst: CognitiveControlPlane | None = None
        self._capabilities_inst: CapabilityRegistry | None = None
        self._organizations_inst: OrganizationGenerator | None = None
        self._policy_inst: PolicyEngine | None = None
        self._planner_inst: AdaptivePlanner | None = None
        self._tool_forge_inst: ToolForge | None = None
        self._runtime_inst: RuntimeAdapter | None = None
        self._gap_detector_inst: RealityGapDetector | None = None
        self._sandboxes_inst: SandboxManager | None = None
        self.metrics = MetricsCollector()

        # Bootstrap: semeia grafo se vazio e persiste
        if bootstrap_graph(self.memory.load_graph()) > 0:
            self.memory._persist_graph_state()

    # ── Lazy properties — só instanciadas quando o full pipeline precisa ──

    @property
    def intent_compiler(self) -> IntentCompiler:
        if self._intent_compiler is None:
            self._intent_compiler = IntentCompiler()
        return self._intent_compiler

    @property
    def task_compiler(self) -> TaskCompiler:
        if self._task_compiler is None:
            self._task_compiler = TaskCompiler()
        return self._task_compiler

    @property
    def control_plane(self) -> CognitiveControlPlane:
        if self._control_plane_inst is None:
            self._control_plane_inst = CognitiveControlPlane()
        return self._control_plane_inst

    @property
    def capabilities(self) -> CapabilityRegistry:
        if self._capabilities_inst is None:
            self._capabilities_inst = self._capabilities_override or CapabilityRegistry()
        return self._capabilities_inst

    @property
    def organizations(self) -> OrganizationGenerator:
        if self._organizations_inst is None:
            self._organizations_inst = OrganizationGenerator()
        return self._organizations_inst

    @property
    def policy(self) -> PolicyEngine:
        if self._policy_inst is None:
            self._policy_inst = PolicyEngine()
        return self._policy_inst

    @property
    def adaptive_planner(self) -> AdaptivePlanner:
        if self._planner_inst is None:
            self._planner_inst = self._planner_override or AdaptivePlanner()
        return self._planner_inst

    @property
    def tool_forge(self) -> ToolForge:
        if self._tool_forge_inst is None:
            self._tool_forge_inst = self._tool_forge_override or ToolForge()
        return self._tool_forge_inst

    @property
    def runtime(self) -> RuntimeAdapter:
        if self._runtime_inst is None:
            self._runtime_inst = self._runtime_override or _resolve_runtime(
                self._runtime_mode, self._llm_client
            )
        return self._runtime_inst

    @property
    def gap_detector(self) -> RealityGapDetector:
        if self._gap_detector_inst is None:
            self._gap_detector_inst = RealityGapDetector()
        return self._gap_detector_inst

    @property
    def sandboxes(self) -> SandboxManager:
        if self._sandboxes_inst is None:
            self._sandboxes_inst = self._sandbox_override or SandboxManager()
        return self._sandboxes_inst

    @property
    def _llm_client(self) -> Any:
        """Acesso ao LLM client — via intent_compiler (lazy)."""
        return self.intent_compiler.llm_client

    def run(
        self,
        request: str,
        autonomy: str = "assistido",
        output_dir: Path = Path("runs"),
        session_id: str | None = None,
        terms_accepted: bool | None = None,
        *,
        llm_classify: bool = False,
    ) -> RunResult:
        run_id = new_id("run")
        self.metrics = MetricsCollector()
        llm_for_classify = self._llm_client if llm_classify else None
        graph = self.memory.load_graph()

        # Decay automático — throttle: máx 1x por hora
        result = maybe_sweep_decay(graph)
        if result and any(v > 0 for v in result.values()):
            self.metrics.record_decay(sum(result.values()))
            self.memory._persist_graph_state()

        with self.metrics.phase("classify"):
            decision = brain_activate(graph, request)
            # Fallback: se grafo não tem ativação forte, usa classify_request
            if decision.confidence < BRAIN_CONFIDENCE_THRESHOLD:
                complexity = classify_request(request, graph=graph, llm_client=llm_for_classify)
            else:
                complexity = _decision_to_complexity(decision)
        self.metrics.set_complexity(complexity.level)
        logger.debug("classify: level=%s reason=%s", complexity.level, complexity.reason)

        # === FAST PATH: conversacional → single LLM call ===
        if complexity.skip_full_pipeline and complexity.level == "conversational":
            return fast_response(
                request=request,
                session_id=session_id,
                autonomy=autonomy,
                terms_accepted=terms_accepted,
                run_id=run_id,
                output_dir=output_dir,
                sessions=self.sessions,
                memory=self.memory,
                llm_client=self._llm_client,
            )

        # === MEDIUM PATH: intermediate → retrieval + routing + 1 LLM call ===
        if complexity.skip_full_pipeline and complexity.level == "intermediate":
            return medium_response(
                request=request,
                session_id=session_id,
                autonomy=autonomy,
                terms_accepted=terms_accepted,
                run_id=run_id,
                output_dir=output_dir,
                sessions=self.sessions,
                memory=self.memory,
                llm_client=self._llm_client,
                suggested_tier=complexity.suggested_tier,
            )

        # === FULL PIPELINE: complex → multi-step execution ===
        return run_full_pipeline(
            self,
            request=request,
            autonomy=autonomy,
            output_dir=output_dir,
            session_id=session_id,
            terms_accepted=terms_accepted,
            run_id=run_id,
            complexity=complexity,
        )

    def pop_due_proactive_messages(self, session_id: str, *, limit: int = 3) -> list[str]:
        due = self.proactivity.pop_due(session_id=session_id, limit=limit)
        return [
            str(item.get("message", "")).strip()
            for item in due
            if str(item.get("message", "")).strip()
        ]

    def pending_proactive_count(self, session_id: str) -> int:
        return self.proactivity.pending_count(session_id=session_id)

    # ── Métodos privados auxiliares ──────────────────────────────────────

    def _build_runtime_organization(
        self,
        task: TaskIR,
        decision: CognitiveDecision,
        capability_resolution: Dict[str, Any],
    ) -> OrganizationIR:
        if isinstance(self.runtime, GraphRuntime):
            return _org.build_graph_native_organization(task, decision, capability_resolution)
        return self.organizations.generate(task, decision, capability_resolution)
