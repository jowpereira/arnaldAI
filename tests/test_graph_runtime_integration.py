from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
from typing import Any
from types import SimpleNamespace
from dataclasses import fields
from typing import get_origin

from arnaldo.components import CapabilityRegistry, ToolForge
from arnaldo.graph import CapabilityNode, CognitiveGraph, EdgeKind, GraphEdge, NodeKind, SynapseNode
from arnaldo.kernel import ArnaldoKernel
from arnaldo.llm.structured import TypedResponse
from arnaldo.memory import MemoryStore
from arnaldo.proactivity import ProactivityManager
from arnaldo.runtime import GraphRuntime, SandboxManager
from arnaldo.session import SessionManager
from arnaldo.storage import RunStore


def build_payload_for_model(model: type[Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in fields(model):
        origin = get_origin(field.type)
        if field.name in {"goal", "goal_type", "status"}:
            payload[field.name] = "ok"
        elif field.name in {"evidence", "uncertainties", "warnings", "steps", "sections"}:
            payload[field.name] = []
        elif field.name == "constraints":
            payload[field.name] = []
        elif origin is list:
            payload[field.name] = []
        elif origin is dict:
            payload[field.name] = {}
        else:
            payload[field.name] = "ok"
    return payload


class RefusalClient:
    is_configured = True

    def chat_typed(self, **kwargs: Any) -> TypedResponse[Any]:
        return TypedResponse(
            parsed=None,
            refusal="refusal_for_test",
            raw={},
            schema_used={},
            retries=0,
        )


class AlwaysSuccessClient:
    is_configured = True

    def chat_typed(self, **kwargs: Any) -> TypedResponse[Any]:
        model = kwargs["response_model"]
        payload = build_payload_for_model(model)
        return TypedResponse(
            parsed=model(**payload),
            refusal=None,
            raw={},
            schema_used={},
            retries=0,
        )


class CaptureMessagesClient:
    is_configured = True

    def __init__(self) -> None:
        self.user_messages: list[str] = []

    def chat_typed(self, **kwargs: Any) -> TypedResponse[Any]:
        messages = kwargs.get("messages") or []
        if messages:
            self.user_messages.append(str(messages[-1].get("content", "")))
        model = kwargs["response_model"]
        payload = build_payload_for_model(model)
        return TypedResponse(
            parsed=model(**payload),
            refusal=None,
            raw={},
            schema_used={},
            retries=0,
        )


class GraphRuntimeIntegrationTest(unittest.TestCase):
    def _build_kernel(self, base: Path, *, runtime=None) -> ArnaldoKernel:
        runtime_adapter = runtime or GraphRuntime(llm_client=AlwaysSuccessClient())
        kernel = ArnaldoKernel(
            runtime=runtime_adapter,
            memory=MemoryStore(base / "memory"),
            session_manager=SessionManager(base / "sessions"),
            tool_forge=ToolForge(base / "tool_forge"),
            capabilities=CapabilityRegistry(registry_path=base / "capability_registry.json"),
            sandbox_manager=SandboxManager(base / "sandboxes"),
            proactivity=ProactivityManager(base / "proactivity"),
        )
        llm_client = getattr(runtime_adapter, "llm_client", None)
        if llm_client is not None:
            kernel.intent_compiler._llm_client = llm_client  # type: ignore[attr-defined]
        return kernel

    def test_default_runtime_mode_is_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            result = kernel.run(
                "Crie um plano inicial para uma ferramenta B2B de automacao",
                output_dir=base / "runs",
            )

            sandbox = json.loads(result.files["sandbox_state"].read_text(encoding="utf-8"))
            runtime_marker = Path(sandbox["workspace_path"]) / "runtime-session.txt"
            self.assertTrue(runtime_marker.exists())
            marker_content = runtime_marker.read_text(encoding="utf-8")
            self.assertIn("runtime=graph", marker_content)

    def test_graph_runtime_raises_on_llm_refusal_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = GraphRuntime(llm_client=RefusalClient())
            kernel = self._build_kernel(base, runtime=runtime)
            with self.assertRaises(RuntimeError) as ctx:
                kernel.run(
                    "Analise riscos de um plano sem executar nada externo",
                    output_dir=base / "runs",
                )
            self.assertIn("refusal", str(ctx.exception))

    def test_graph_runtime_materializes_lightweight_workflow_for_greeting(self) -> None:
        runtime = GraphRuntime(llm_client=AlwaysSuccessClient())
        organization = SimpleNamespace(
            topology="pipeline_with_critic",
            workflow=[],
            agents=[],
        )
        task = SimpleNamespace(
            goal={
                "statement": "saudacao inicial do usuario para abrir conversa",
                "type": "open_ended_execution",
            },
            capability_needs=[],
            uncertainty=[],
            risk={"execution_risk": "low"},
        )

        workflow = runtime._materialize_runtime_workflow(  # pylint: disable=protected-access
            organization=organization,
            task=task,
            capability_resolution={"available": [], "missing": [], "degraded": []},
        )

        self.assertEqual(len(workflow), 1)
        self.assertEqual(workflow[0]["action"], "draft_artifact")
        self.assertEqual(workflow[0]["tier_preference"], "fast")
        self.assertEqual(workflow[0]["max_tokens"], 320)

    def test_graph_runtime_materializes_lightweight_workflow_for_greeting_prefix_in_context(self) -> None:
        runtime = GraphRuntime(llm_client=AlwaysSuccessClient())
        organization = SimpleNamespace(
            topology="pipeline_with_critic",
            workflow=[],
            agents=[],
        )
        task = SimpleNamespace(
            goal={
                "statement": "objetivo genérico",
                "type": "open_ended_execution",
            },
            context={
                "source": "cli",
                "original_request": "oi objetivos_extraidos_no_turno: oi",
            },
            capability_needs=[],
            uncertainty=[],
            risk={"execution_risk": "low"},
        )

        workflow = runtime._materialize_runtime_workflow(  # pylint: disable=protected-access
            organization=organization,
            task=task,
            capability_resolution={"available": [], "missing": [], "degraded": []},
        )

        self.assertEqual(len(workflow), 1)
        self.assertEqual(workflow[0]["action"], "draft_artifact")
        self.assertEqual(workflow[0]["tier_preference"], "fast")
        self.assertEqual(workflow[0]["max_tokens"], 320)

    def test_graph_runtime_materializes_lightweight_workflow_for_identity_query(self) -> None:
        runtime = GraphRuntime(llm_client=AlwaysSuccessClient())
        organization = SimpleNamespace(
            topology="pipeline_with_critic",
            workflow=[],
            agents=[],
        )
        task = SimpleNamespace(
            goal={
                "statement": "usuario pergunta quem ele e no contexto da conversa",
                "type": "open_ended_execution",
            },
            context={
                "source": "cli",
                "raw_request": "quem sou eu?",
                "session_user_name": "Jonathan",
            },
            capability_needs=[],
            uncertainty=[{"question": "qual nome do usuario?"}],
            risk={"execution_risk": "low"},
        )

        workflow = runtime._materialize_runtime_workflow(  # pylint: disable=protected-access
            organization=organization,
            task=task,
            capability_resolution={"available": [], "missing": [], "degraded": []},
        )

        self.assertEqual(len(workflow), 1)
        self.assertEqual(workflow[0]["action"], "draft_artifact")
        self.assertIn("objective", workflow[0])
        self.assertIn("output_contract", workflow[0])
        self.assertEqual(workflow[0]["max_tokens"], 320)

    def test_graph_runtime_materializes_single_step_for_conversational_cli_turn(self) -> None:
        runtime = GraphRuntime(llm_client=AlwaysSuccessClient())
        organization = SimpleNamespace(
            topology="pipeline_with_critic",
            workflow=[],
            agents=[],
        )
        task = SimpleNamespace(
            goal={
                "statement": "responder de forma clara ao usuario",
                "type": "open_ended_execution",
            },
            context={
                "source": "cli",
                "raw_request": "me explica de forma simples como podemos seguir com isso agora",
            },
            capability_needs=[],
            uncertainty=[],
            risk={"execution_risk": "low"},
        )

        workflow = runtime._materialize_runtime_workflow(  # pylint: disable=protected-access
            organization=organization,
            task=task,
            capability_resolution={"available": [], "missing": [], "degraded": []},
        )

        self.assertEqual(len(workflow), 1)
        self.assertEqual(workflow[0]["action"], "draft_artifact")
        self.assertEqual(workflow[0]["tier_preference"], "fast")
        self.assertEqual(workflow[0]["max_retries"], 0)
        self.assertEqual(workflow[0]["retry_attempts"], 1)

    def test_graph_runtime_materializes_latency_sensitive_cli_turn_as_single_fast_step(self) -> None:
        runtime = GraphRuntime(llm_client=AlwaysSuccessClient())
        organization = SimpleNamespace(
            topology="minimal_pipeline",
            workflow=[],
            agents=[],
        )
        task = SimpleNamespace(
            goal={
                "statement": "analisar acao do bradesco de forma objetiva",
                "type": "analyze_or_evaluate",
            },
            context={
                "source": "cli",
                "original_request": "analise a acao bradesco",
            },
            capability_needs=[],
            uncertainty=[],
            risk={"execution_risk": "low"},
        )

        workflow = runtime._materialize_runtime_workflow(  # pylint: disable=protected-access
            organization=organization,
            task=task,
            capability_resolution={"available": [], "missing": [], "degraded": []},
        )

        self.assertEqual(len(workflow), 1)
        self.assertEqual(workflow[0]["action"], "draft_artifact")
        self.assertEqual(workflow[0]["tier_preference"], "fast")
        self.assertEqual(workflow[0]["max_tokens"], 700)
        self.assertEqual(workflow[0]["timeout"], 25.0)
        self.assertEqual(workflow[0]["max_retries"], 0)
        self.assertEqual(workflow[0]["retry_attempts"], 1)

    def test_session_reuses_and_grows_execution_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)

            first = kernel.run(
                "Planeje uma execução inicial",
                output_dir=base / "runs",
                session_id="sessao_graph",
            )
            second = kernel.run(
                "Aprimore o plano anterior com riscos",
                output_dir=base / "runs",
                session_id="sessao_graph",
            )

            self.assertIn("execution_graph", first.files)
            self.assertIn("execution_graph", second.files)

            g1 = CognitiveGraph.load(first.files["execution_graph"])
            g2 = CognitiveGraph.load(second.files["execution_graph"])
            self.assertGreater(g2.node_count, g1.node_count)
            syn1 = {node.id for node in g1.iter_nodes(kind=NodeKind.SYNAPSE)}
            syn2 = {node.id for node in g2.iter_nodes(kind=NodeKind.SYNAPSE)}
            self.assertTrue(syn1.issubset(syn2))

            session_state = json.loads(second.files["session_state"].read_text(encoding="utf-8"))
            self.assertEqual(
                session_state["learned_preferences"]["execution_graph_uri"],
                str(second.files["execution_graph"]),
            )

    def test_graph_runtime_bootstraps_context_from_previous_memories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            seed_kernel = self._build_kernel(base, runtime=GraphRuntime(llm_client=AlwaysSuccessClient()))
            first = seed_kernel.run(
                "Planeje execução inicial com alternativas e revisão",
                output_dir=base / "runs",
                session_id="sessao_bootstrap_context",
            )

            capture_client = CaptureMessagesClient()
            replay_kernel = self._build_kernel(base, runtime=GraphRuntime(llm_client=capture_client))
            second = replay_kernel.run(
                "Continue e refine o plano com base no histórico",
                output_dir=base / "runs",
                session_id=first.session_id,
            )

            self.assertGreaterEqual(len(capture_client.user_messages), 1)
            self.assertTrue(any("Contexto prévio" in msg for msg in capture_client.user_messages))

            trace_lines = [
                json.loads(line)
                for line in second.files["trace"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            bootstrap_events = [
                item for item in trace_lines if item.get("event_type") == "graph_context_bootstrapped"
            ]
            self.assertGreaterEqual(len(bootstrap_events), 1)
            payload = bootstrap_events[-1]["payload"]
            self.assertGreaterEqual(int(payload["loaded_synapses"]), 1)
            self.assertGreaterEqual(int(payload["context_version"]), int(payload["loaded_synapses"]))
            self.assertIn("loaded_tool_context", payload)

    def test_graph_native_agents_scope_toolsmith_by_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            task = SimpleNamespace(
                uncertainty=[],
                risk={"execution_risk": "low"},
            )
            capability_resolution = {
                "available": [
                    {
                        "id": "connector.runtime",
                        "module_path": "storage/tool_forge/generated/connector_runtime.py",
                    }
                ],
                "missing": [{"id": "connector.github"}, {"id": "connector.crm"}],
                "degraded": [{"id": "tool.dynamic.build"}],
            }

            agents = kernel._build_graph_native_agents(  # pylint: disable=protected-access
                "minimal_pipeline",
                task,
                capability_resolution,
            )
            agent_ids = {agent.id for agent in agents}

            self.assertIn("toolsmith_connector_github", agent_ids)
            self.assertIn("toolsmith_connector_crm", agent_ids)
            self.assertIn("toolsmith_tool_dynamic_build", agent_ids)
            self.assertIn("toolrunner_connector_runtime", agent_ids)
            self.assertIn("workflow_composer", agent_ids)

    def test_graph_runtime_plans_execution_mode_from_topology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            result = kernel.run(
                "Analise qualquer abordagem ideal para integrar qualquer API com dados de pagamento",
                autonomy="autonomo",
                output_dir=base / "runs",
            )

            organization = json.loads(result.files["organization_ir"].read_text(encoding="utf-8"))
            trace_lines = [
                json.loads(line)
                for line in result.files["trace"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            planned_events = [item for item in trace_lines if item.get("event_type") == "graph_execution_planned"]
            self.assertGreaterEqual(len(planned_events), 1)
            planned_mode = planned_events[-1]["payload"]["mode"]
            expected_mode = (
                "activates_parallel_levels"
                if organization["topology"] == "parallel_with_synthesis"
                else "activates_reachable"
            )
            self.assertEqual(planned_mode, expected_mode)

    def test_graph_runtime_records_retention_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            result = kernel.run(
                "Planeje uma execução com revisão crítica e sincronização de capacidades",
                output_dir=base / "runs",
            )

            trace_lines = [
                json.loads(line)
                for line in result.files["trace"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            retention_events = [
                item for item in trace_lines if item.get("event_type") == "graph_retention_applied"
            ]
            self.assertGreaterEqual(len(retention_events), 1)
            payload = retention_events[-1]["payload"]
            self.assertIn("decay", payload)
            self.assertIn("removed_memory_nodes", payload)

    def test_graph_runtime_persists_prompt_trace_for_synapses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            result = kernel.run(
                "Analise e sintetize um plano curto para validar prompt tracing",
                output_dir=base / "runs",
            )

            self.assertIn("prompts", result.files)
            prompt_lines = [
                json.loads(line)
                for line in result.files["prompts"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertGreaterEqual(len(prompt_lines), 1)
            first = prompt_lines[0]
            self.assertIn("node_id", first)
            self.assertIn("messages", first)
            self.assertIn("chat_kwargs", first)

            trace_lines = [
                json.loads(line)
                for line in result.files["trace"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            prompt_events = [item for item in trace_lines if item.get("event_type") == "prompt_prepared"]
            self.assertGreaterEqual(len(prompt_events), 1)

    def test_graph_runtime_ignores_legacy_seed_synapses_outside_current_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = GraphRuntime(llm_client=AlwaysSuccessClient())
            kernel = self._build_kernel(base, runtime=runtime)

            first = kernel.run(
                "Planeje integração inicial com revisão de riscos",
                output_dir=base / "runs",
                session_id="sessao_legacy_seed",
            )
            graph = CognitiveGraph.load(first.files["execution_graph"])
            root = next(iter(graph.iter_nodes(kind=NodeKind.SYNAPSE)))
            assert isinstance(root, SynapseNode)

            legacy = SynapseNode.specialist(
                label="legacy_orphan::seed",
                id="syn_legacy_seed_orphan",
                role="operator",
                objective="nó legado fora do workflow materializado",
                output_contract={"schema": "legacy"},
                action="legacy_orphan_action",
                agent_id="legacy_seed",
                output="legacy_output",
            )
            graph.add_node(legacy)
            graph.add_edge(GraphEdge.connect(root.id, legacy.id, EdgeKind.ACTIVATES, weight=0.99))
            graph.persist(first.files["execution_graph"])

            second = kernel.run(
                "Refaça o plano sem executar lixo legado",
                output_dir=base / "runs",
                session_id=first.session_id,
            )
            trace_lines = [
                json.loads(line)
                for line in second.files["trace"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            orphan_events = [item for item in trace_lines if item.get("event_type") == "orphan_synapse_skipped"]
            self.assertEqual(orphan_events, [])

    def test_sync_capabilities_ignores_null_module_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            graph = CognitiveGraph()
            graph.add_node(
                CapabilityNode.tool(
                    "connector.custom",
                    id="cap_connector_custom",
                    description="Connector custom para teste",
                    maturity="draft",
                    payload={"module_path": None},
                )
            )
            graph_path = base / "graph-sync.msgpack"
            graph.persist(graph_path)

            session = kernel.sessions.open(
                session_id="sessao_sync_modpath",
                autonomy_mode="assistido",
                terms_accepted=False,
            )
            store = RunStore(base / "runs", "run_sync_modpath").create()
            report, _ = kernel._sync_capabilities_from_graph(  # pylint: disable=protected-access
                graph_path,
                session=session,
                run_id="run_sync_modpath",
                task_id="task_sync_modpath",
                store=store,
            )

            self.assertEqual(report.get("error"), None)
            synced = {item["id"]: item for item in report["synced"]}
            self.assertIn("connector.custom", synced)
            self.assertNotIn("module_path", synced["connector.custom"])

            registry_payload = json.loads((base / "capability_registry.json").read_text(encoding="utf-8"))
            custom = next(item for item in registry_payload if item["id"] == "connector.custom")
            self.assertNotIn("module_path", custom["policies"])

    def test_sync_capabilities_persists_real_execution_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            graph = CognitiveGraph()
            graph.add_node(
                CapabilityNode.tool(
                    "connector.runtime",
                    id="cap_connector_runtime",
                    description="Connector runtime para teste",
                    maturity="trusted",
                    payload={
                        "real_execution_successes": 7,
                        "last_tool_execution_status": "executed",
                    },
                )
            )
            graph_path = base / "graph-sync-runtime-signals.msgpack"
            graph.persist(graph_path)

            session = kernel.sessions.open(
                session_id="sessao_sync_signals",
                autonomy_mode="assistido",
                terms_accepted=False,
            )
            store = RunStore(base / "runs", "run_sync_signals").create()
            report, _ = kernel._sync_capabilities_from_graph(  # pylint: disable=protected-access
                graph_path,
                session=session,
                run_id="run_sync_signals",
                task_id="task_sync_signals",
                store=store,
            )

            synced = {item["id"]: item for item in report["synced"]}
            self.assertIn("connector.runtime", synced)
            runtime_item = synced["connector.runtime"]
            self.assertEqual(runtime_item["real_execution_successes"], 7)
            self.assertEqual(runtime_item["last_tool_execution_status"], "executed")
            self.assertEqual(runtime_item["health"], "stable")

            registry_payload = json.loads((base / "capability_registry.json").read_text(encoding="utf-8"))
            runtime = next(item for item in registry_payload if item["id"] == "connector.runtime")
            self.assertEqual(runtime["policies"]["real_execution_successes"], 7)
            self.assertEqual(runtime["policies"]["last_tool_execution_status"], "executed")

    def test_kernel_graph_runtime_defers_workflow_to_runtime_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            result = kernel.run(
                "Planeje integração de API com síntese e revisão",
                autonomy="autonomo",
                output_dir=base / "runs",
            )

            organization = json.loads(result.files["organization_ir"].read_text(encoding="utf-8"))
            self.assertEqual(organization["workflow"], [])
            self.assertGreaterEqual(len(organization["agents"]), 1)
            self.assertIn("graph_workflow_materialized", result.files)
            materialized = json.loads(
                result.files["graph_workflow_materialized"].read_text(encoding="utf-8")
            )
            self.assertGreaterEqual(int(materialized["step_count"]), 3)
            actions = [str(item.get("action", "")) for item in materialized["steps"]]
            self.assertIn("frame_intent", actions)
            graph = CognitiveGraph.load(result.files["execution_graph"])
            synapses = list(graph.iter_nodes(kind=NodeKind.SYNAPSE))
            self.assertGreaterEqual(len(synapses), 3)

    def test_build_request_is_goal_capability_focused_without_policy_flags(self) -> None:
        task = SimpleNamespace(
            goal={"statement": "planejar execução", "type": "analyze_or_evaluate"},
            deliverables=[{"id": "primary_artifact"}],
            capability_needs=[{"id": "connector.http.generic"}, {"id": "tool.dynamic.build"}],
            uncertainty=[{"question": "qual conector vem primeiro?"}],
        )
        request = GraphRuntime._build_request(
            task,
            {
                "missing": [{"id": "connector.http.generic"}],
                "degraded": [{"id": "tool.dynamic.build"}],
            },
        )

        self.assertIn("Goal:", request)
        self.assertIn("CapabilityNeeds:", request)
        self.assertIn("MissingCapabilities:", request)
        self.assertNotIn("PolicyAllowed", request)
        self.assertNotIn("ApprovalRequired", request)

    def test_build_request_for_lightweight_conversation_uses_direct_chat_contract(self) -> None:
        task = SimpleNamespace(
            goal={"statement": "conversa inicial", "type": "open_ended_execution"},
            context={"raw_request": "quem sou eu?", "session_user_name": "Jonathan"},
            deliverables=[{"id": "primary_artifact"}],
            capability_needs=[{"id": "artifact.draft"}],
            uncertainty=[],
        )
        request = GraphRuntime._build_request(
            task,
            {"missing": [], "degraded": []},
        )

        self.assertIn("Mode: conversational_reply", request)
        self.assertIn("UserMessage: quem sou eu?", request)
        self.assertIn("SessionMemory.user_name: Jonathan", request)
        self.assertNotIn("Goal:", request)
        self.assertNotIn("CapabilityNeeds:", request)

    def test_build_request_for_conversational_cli_turn_uses_direct_chat_contract(self) -> None:
        task = SimpleNamespace(
            goal={"statement": "responder de forma clara", "type": "open_ended_execution"},
            context={"source": "cli", "raw_request": "legal e vc quem e", "session_user_name": "Jonathan"},
            deliverables=[{"id": "primary_artifact"}],
            capability_needs=[{"id": "artifact.draft"}],
            uncertainty=[],
        )
        request = GraphRuntime._build_request(
            task,
            {"available": [], "missing": [], "degraded": []},
        )

        self.assertIn("Mode: conversational_reply", request)
        self.assertIn("UserMessage: legal e vc quem e", request)
        self.assertIn("SessionMemory.user_name: Jonathan", request)
        self.assertNotIn("Goal:", request)
        self.assertNotIn("CapabilityNeeds:", request)

    def test_kernel_propagates_session_user_name_to_task_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)

            kernel.run(
                "meu nome e jonathan",
                output_dir=base / "runs",
                session_id="sessao_nome",
            )
            second = kernel.run(
                "quem sou eu?",
                output_dir=base / "runs",
                session_id="sessao_nome",
            )

            task_ir = json.loads(second.files["task_ir"].read_text(encoding="utf-8"))
            self.assertEqual(task_ir["context"]["raw_request"], "quem sou eu?")
            self.assertEqual(task_ir["context"]["session_user_name"], "Jonathan")

    def test_kernel_schedules_proactive_messages_after_non_lightweight_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            result = kernel.run(
                "analise as opções e proponha o próximo passo para validar hipóteses",
                output_dir=base / "runs",
                session_id="sessao_proativa",
            )

            self.assertEqual(result.session_id, "sessao_proativa")
            self.assertGreaterEqual(kernel.pending_proactive_count("sessao_proativa"), 1)

    def test_graph_runtime_promotes_degraded_capability_after_successful_stabilization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = GraphRuntime(llm_client=AlwaysSuccessClient())
            kernel = self._build_kernel(base, runtime=runtime)
            result = kernel.run(
                "Criar conector para API do GitHub e estabilizar o fluxo",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id="sessao_promocao",
            )

            graph = CognitiveGraph.load(result.files["execution_graph"])
            cap_node = graph.get_node("cap_connector_http_generic")
            self.assertIsInstance(cap_node, CapabilityNode)
            assert isinstance(cap_node, CapabilityNode)
            self.assertEqual(cap_node.maturity, "tested")

    def test_kernel_syncs_dynamic_capabilities_from_execution_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = GraphRuntime(llm_client=AlwaysSuccessClient())
            kernel = self._build_kernel(base, runtime=runtime)

            first = kernel.run(
                "Quero integrar a API do GitHub com um novo conector no fluxo",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id="sessao_cap_sync",
            )
            self.assertIn("graph_capability_sync", first.files)
            sync_report = json.loads(first.files["graph_capability_sync"].read_text(encoding="utf-8"))
            synced_ids = {item["id"] for item in sync_report["synced"]}
            self.assertIn("connector.github", synced_ids)

            registry_payload = json.loads((base / "capability_registry.json").read_text(encoding="utf-8"))
            registry_ids = {item["id"] for item in registry_payload}
            self.assertIn("connector.github", registry_ids)

            second = kernel.run(
                "Integrar novamente a API do GitHub com foco em estabilidade",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id=first.session_id,
            )
            resolution = json.loads(second.files["capability_resolution"].read_text(encoding="utf-8"))
            available_ids = {item["id"] for item in resolution["available"]}
            degraded_ids = {item["id"] for item in resolution["degraded"]}
            self.assertNotIn("connector.github", available_ids)
            self.assertIn("connector.github", degraded_ids)

    def test_kernel_auto_forges_graph_capabilities_and_persists_module_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = GraphRuntime(llm_client=AlwaysSuccessClient())
            kernel = self._build_kernel(base, runtime=runtime)

            first = kernel.run(
                "Quero integrar API do GitHub com conector dinâmico e estabilização",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id="sessao_graph_auto_forge",
            )
            self.assertIn("graph_tool_forge", first.files)
            forge_report = json.loads(first.files["graph_tool_forge"].read_text(encoding="utf-8"))
            created_ids = {item["capability_id"] for item in forge_report["created"]}
            self.assertGreaterEqual(len(created_ids), 1)

            graph = CognitiveGraph.load(first.files["execution_graph"])
            validated = False
            for capability_id in sorted(created_ids):
                node_id = "cap_%s" % capability_id.replace(".", "_")
                cap_node = graph.get_node(node_id)
                if not isinstance(cap_node, CapabilityNode):
                    continue
                module_path = str(cap_node.payload.get("module_path", "")).strip()
                if module_path:
                    validated = True
                    break
            self.assertTrue(validated)

            second = kernel.run(
                "Execute o conector GitHub novamente e refine a integração com continuidade",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id=first.session_id,
            )
            if "graph_tool_forge" in second.files:
                second_report = json.loads(second.files["graph_tool_forge"].read_text(encoding="utf-8"))
                self.assertEqual(len(second_report["created"]), 0)

            evidence_lines = [
                json.loads(line)
                for line in second.files["evidence"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            execute_events = [
                item
                for item in evidence_lines
                if item.get("record_type") == "step_completed"
                and item.get("payload", {}).get("action") == "execute_tooling"
            ]
            self.assertGreaterEqual(len(execute_events), 1)
            execute_payload = execute_events[-1]["payload"]["result"]
            self.assertIn(execute_payload.get("status"), {"completed", "not_implemented"})


if __name__ == "__main__":
    unittest.main()
