"""Kernel principal do ArnaldAI — pipeline intent-to-execution."""

from __future__ import annotations

import logging
from pathlib import Path
import re
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
    RuntimeAdapter,
    SandboxManager,
)
from arnaldo.session import SessionManager

from arnaldo.graph.brain import (
    activate as brain_activate,
    BRAIN_CONFIDENCE_THRESHOLD,
)
from arnaldo.constants.discovery_terms import (
    LIVE_LOOKUP_FRESHNESS_HINTS,
    LIVE_LOOKUP_TOPIC_HINTS,
    READONLY_SHELL_COMMAND_HINTS,
    WEB_SEARCH_FOLLOWUP_HINTS,
)

from .classify import classify_request
from .fast_path import fast_response, inline_capability_response, medium_response
from .pipeline import run_full_pipeline
from .bootstrap import bootstrap_graph
from .metrics import MetricsCollector
from .plasticity import maybe_sweep_decay
from .episteme_hooks import create_prospective_memory, collect_pending_prospective
from .episteme_bridge import maybe_forage, check_web_search_available
from arnaldo.episteme.signals import GapType
from .helpers import (
    resolve_runtime as _resolve_runtime,
    decision_to_complexity as _decision_to_complexity,
    pop_due_proactive_messages as _pop_due_proactive,
    pending_proactive_count as _pending_proactive_count,
    build_runtime_organization as _build_runtime_org,
)
from .thinking import ThinkingEmitter

logger = logging.getLogger("arnaldo.kernel")


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
        self.thinking = ThinkingEmitter()

        # Bootstrap: semeia grafo se vazio e persiste
        graph = self.memory.load_graph()
        if bootstrap_graph(graph) > 0:
            self.memory._persist_graph_state()
        # Guard: grafo unificado — garante que MemoryStore aponta para o mesmo objeto
        if self.memory.load_graph() is not graph:
            logger.warning("MemoryStore com grafo divergente — forçando bind_graph")
            self.memory.bind_graph(graph)

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
        thinking_callback: Any | None = None,
    ) -> RunResult:
        run_id = new_id("run")
        self.metrics = MetricsCollector()
        self.thinking.reset()
        if thinking_callback is not None:
            self.thinking.register(thinking_callback)
        from arnaldo.episteme.forager import WebForager
        WebForager.reset_counter()
        llm_for_classify = self._llm_client if llm_classify else None
        graph = self.memory.load_graph()

        # Decay automático — throttle: máx 1x por hora
        result = maybe_sweep_decay(graph)
        if result and any(v > 0 for v in result.values()):
            self.metrics.record_decay(sum(result.values()))
            self.memory._persist_graph_state()

        # GAP 4: Coleta memórias prospectivas pendentes
        pending = collect_pending_prospective(graph)
        if pending:
            logger.debug("Memórias prospectivas pendentes: %d", len(pending))

        with self.metrics.phase("classify"):
            decision = brain_activate(graph, request)
            # Fallback: se grafo não tem ativação forte, usa classify_request
            if decision.confidence < BRAIN_CONFIDENCE_THRESHOLD or _should_prefer_semantic_classification(
                request,
                decision,
            ):
                complexity = classify_request(request, graph=graph, llm_client=llm_for_classify)
            else:
                complexity = _decision_to_complexity(decision)
        self.metrics.set_complexity(complexity.level)
        logger.debug("classify: level=%s reason=%s", complexity.level, complexity.reason)

        # GAP 1: Cria memória prospectiva quando brain detecta gap
        prospect = create_prospective_memory(decision, request)
        if prospect is not None:
            self.memory.append(prospect)

        if complexity.execution_profile == "inline_capability":
            return inline_capability_response(
                request=request,
                session_id=session_id,
                autonomy=autonomy,
                terms_accepted=terms_accepted,
                run_id=run_id,
                output_dir=output_dir,
                sessions=self.sessions,
                memory=self.memory,
                llm_client=self._llm_client,
                capability_ids=complexity.execution_capability_ids or complexity.capability_needs,
                suggested_tier=complexity.suggested_tier,
            )

        # GAP 10: Foraging epistêmico — busca externa se gap + web disponível
        if decision.knowledge_gap and not complexity.skip_full_pipeline:
            has_web = check_web_search_available(graph)
            if self.thinking.has_listeners:
                self.thinking.searching(request, source="epistemic_gap")
            foraged = maybe_forage(
                graph,
                decision.gap_type,
                request,
                decision.confidence,
                has_web_search=has_web,
                thinking=self.thinking,
            )
            if foraged:
                decision = brain_activate(graph, request)
                if decision.confidence >= BRAIN_CONFIDENCE_THRESHOLD:
                    complexity = _decision_to_complexity(decision)
                self.memory._persist_graph_state()

        # GAP P3: Ambiguidade alta → foraging para resolver dúvida
        if not decision.knowledge_gap and not complexity.skip_full_pipeline:
            from arnaldo.components.intent_heuristics import infer_signals

            signals = infer_signals(request)
            if signals["ambiguity_score"] >= 2:
                has_web = check_web_search_available(graph)
                if has_web:
                    if self.thinking.has_listeners:
                        self.thinking.analyzing(
                            f"Ambiguidade detectada (score={signals['ambiguity_score']})"
                        )
                        self.thinking.searching(request, source="ambiguity_resolution")
                    foraged = maybe_forage(
                        graph,
                        GapType.GENUINE,
                        request,
                        decision.confidence,
                        has_web_search=True,
                        thinking=self.thinking,
                    )
                    if foraged:
                        decision = brain_activate(graph, request)
                        if decision.confidence >= BRAIN_CONFIDENCE_THRESHOLD:
                            complexity = _decision_to_complexity(decision)
                        self.memory._persist_graph_state()

        # === FAST PATH: conversacional → single LLM call ===
        if complexity.execution_profile == "fast_response":
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
        if complexity.execution_profile == "medium_response":
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
        return _pop_due_proactive(self.proactivity, session_id, limit=limit)

    def pending_proactive_count(self, session_id: str) -> int:
        return _pending_proactive_count(self.proactivity, session_id)

    def _build_runtime_organization(
        self,
        task: TaskIR,
        decision: CognitiveDecision,
        capability_resolution: Dict[str, Any],
    ) -> OrganizationIR:
        return _build_runtime_org(
            self.runtime, self.organizations, task, decision, capability_resolution
        )


def _should_prefer_semantic_classification(request: str, decision: Any) -> bool:
    lowered = " ".join(str(request or "").lower().split())
    if not lowered:
        return False
    decision_caps = {str(cap).strip() for cap in getattr(decision, "capability_needs", []) or []}
    if not any(
        re.search(rf"(?<![a-z0-9_-]){re.escape(term)}(?![a-z0-9_-])", lowered)
        for term in READONLY_SHELL_COMMAND_HINTS
    ):
        explicit_local_command_missing = False
    else:
        local_capabilities = {"shell.local.readonly", "filesystem.local.search"}
        explicit_local_command_missing = decision_caps.isdisjoint(local_capabilities)
    if explicit_local_command_missing:
        return True
    if _contains_live_lookup_signal(lowered):
        external_capabilities = {"search.public_web", "connector.http.generic"}
        return decision_caps.isdisjoint(external_capabilities)
    return False


def _contains_live_lookup_signal(text: str) -> bool:
    freshness = any(term in text for term in LIVE_LOOKUP_FRESHNESS_HINTS)
    lookup_topic = any(term in text for term in LIVE_LOOKUP_TOPIC_HINTS)
    web_followup = any(term in text for term in WEB_SEARCH_FOLLOWUP_HINTS)
    return web_followup or (freshness and lookup_topic)
