from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
from types import SimpleNamespace

from arnaldo.components import (
    CapabilityRegistry,
    CognitiveControlPlane,
    IntentCompiler,
    OrganizationGenerator,
    TaskCompiler,
    ToolForge,
)
from arnaldo.graph import CapabilityNode, CognitiveGraph, EdgeKind, NodeKind, SynapseNode
from arnaldo.kernel import ArnaldoKernel
from arnaldo.memory import MemoryStore
from arnaldo.runtime import GraphRuntime, SandboxManager
from arnaldo.session import SessionManager
from tests.support_llm import AlwaysSuccessTypedClient


class DynamicFeatureTest(unittest.TestCase):
    def _build_kernel(self, base: Path) -> ArnaldoKernel:
        llm = AlwaysSuccessTypedClient()
        runtime = GraphRuntime(llm_client=llm)
        kernel = ArnaldoKernel(
            runtime=runtime,
            memory=MemoryStore(base / "memory"),
            session_manager=SessionManager(base / "sessions"),
            tool_forge=ToolForge(base / "tool_forge"),
            capabilities=CapabilityRegistry(registry_path=base / "capability_registry.json"),
            sandbox_manager=SandboxManager(base / "sandboxes"),
        )
        kernel.intent_compiler._llm_client = llm  # type: ignore[attr-defined]
        return kernel

    def test_organization_generator_creates_dynamic_agents_and_steps(self) -> None:
        intent = IntentCompiler(llm_client=False, strict_real=False).compile(
            "Analise profundamente integrações de CRM e API; preciso clarear dúvidas e riscos",
            autonomy="autonomo",
        )
        task = TaskCompiler().compile(intent)
        task.goal["type"] = "analyze_or_evaluate"
        task.uncertainty.extend(
            [
                {"question": "qual conector é prioritário?", "blocking": False},
                {"question": "quais riscos de execução existem?", "blocking": False},
            ]
        )
        task.risk["execution_risk"] = "high"
        task.capability_needs.append({"id": "connector.crm", "required": True})

        decision = CognitiveControlPlane().decide(task)
        capability_resolution = {
            "available": [],
            "missing": [
                {"id": "connector.crm", "reason": "capability_not_registered"},
                {"id": "connector.github", "reason": "capability_not_registered"},
            ],
            "degraded": [],
        }

        org = OrganizationGenerator().generate(task, decision, capability_resolution)
        agent_ids = {agent.id for agent in org.agents}
        actions = [item["action"] for item in org.workflow]
        tooling_steps = [item for item in org.workflow if item["action"] == "design_tooling"]

        self.assertIn("clarifier", agent_ids)
        self.assertIn("risk_auditor", agent_ids)
        self.assertIn("toolsmith", agent_ids)
        self.assertIn("clarify_uncertainties", actions)
        self.assertIn("design_tooling", actions)
        self.assertGreaterEqual(len(tooling_steps), 2)
        self.assertIn("risk_review", actions)
        self.assertIn("decision_synthesis", actions)

    def test_capability_registry_marks_optional_missing_as_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            registry = CapabilityRegistry(registry_path=base / "capability_registry.json")
            resolution = registry.resolve(
                [
                    {"id": "connector.github", "required": False},
                ]
            )

            self.assertEqual(resolution["missing"], [])
            degraded_ids = {item["id"] for item in resolution["degraded"]}
            self.assertIn("connector.github", degraded_ids)
            degraded_item = next(item for item in resolution["degraded"] if item["id"] == "connector.github")
            self.assertEqual(degraded_item["reason"], "optional_capability_not_registered")

    def test_kernel_collects_forge_targets_from_missing_and_optional_degraded(self) -> None:
        targets = ArnaldoKernel._collect_forge_targets(  # pylint: disable=protected-access
            {
                "available": [],
                "missing": [{"id": "connector.http.generic", "reason": "capability_not_registered"}],
                "degraded": [
                    {"id": "connector.github", "reason": "optional_capability_not_registered"},
                    {"id": "tool.dynamic.build", "reason": "health_degraded"},
                ],
            }
        )
        target_ids = {item["id"] for item in targets}
        self.assertIn("connector.http.generic", target_ids)
        self.assertIn("connector.github", target_ids)
        self.assertNotIn("tool.dynamic.build", target_ids)

    def test_graph_runtime_builds_distinct_synapses_for_repeated_design_tooling_steps(self) -> None:
        intent = IntentCompiler(llm_client=False, strict_real=False).compile(
            "Planeje integrações para CRM e GitHub com análise de riscos",
            autonomy="autonomo",
        )
        task = TaskCompiler().compile(intent)
        task.goal["type"] = "analyze_or_evaluate"
        task.uncertainty.extend(
            [
                {"question": "qual conector vem primeiro?", "blocking": False},
                {"question": "como validar riscos críticos?", "blocking": False},
            ]
        )
        task.risk["execution_risk"] = "high"
        capability_resolution = {
            "available": [],
            "missing": [
                {"id": "connector.crm", "reason": "capability_not_registered"},
                {"id": "connector.github", "reason": "capability_not_registered"},
                {"id": "tool.dynamic.build", "reason": "capability_not_registered"},
            ],
            "degraded": [],
        }

        decision = CognitiveControlPlane().decide(task)
        organization = OrganizationGenerator().generate(task, decision, capability_resolution)
        runtime = GraphRuntime()
        graph, step_by_node, path = runtime._build_execution_graph(  # pylint: disable=protected-access
            organization,
            task=task,
            capability_resolution=capability_resolution,
        )

        tooling_nodes = [
            node_id
            for node_id in path
            if step_by_node[node_id]["action"] == "design_tooling"
        ]
        tooling_agent_ids = {
            step_by_node[node_id]["agent_id"]
            for node_id in tooling_nodes
        }
        self.assertGreaterEqual(len(tooling_nodes), 2)
        self.assertEqual(len(tooling_nodes), len(set(tooling_nodes)))
        self.assertIn("toolsmith_connector_crm", tooling_agent_ids)
        self.assertIn("toolsmith_connector_github", tooling_agent_ids)
        synapses = list(graph.iter_nodes(kind=NodeKind.SYNAPSE))
        tooling_synapses = [node for node in synapses if node.payload.get("action") == "design_tooling"]
        self.assertEqual(len(tooling_synapses), len(tooling_nodes))

    def test_graph_runtime_injects_stabilize_tooling_steps_from_degraded_capabilities(self) -> None:
        intent = IntentCompiler(llm_client=False, strict_real=False).compile(
            "Preciso estabilizar conectores degradados e revisar riscos",
            autonomy="autonomo",
        )
        task = TaskCompiler().compile(intent)
        task.risk["execution_risk"] = "high"
        decision = CognitiveControlPlane().decide(task)
        capability_resolution = {
            "available": [],
            "missing": [],
            "degraded": [
                {
                    "id": "connector.github",
                    "policies": {"maturity": "draft"},
                    "risk": {"health": "degraded"},
                }
            ],
        }
        organization = OrganizationGenerator().generate(task, decision, capability_resolution)
        runtime = GraphRuntime()
        _, step_by_node, path = runtime._build_execution_graph(  # pylint: disable=protected-access
            organization,
            task=task,
            capability_resolution=capability_resolution,
        )
        stabilized_steps = [
            step_by_node[node_id]
            for node_id in path
            if step_by_node[node_id]["action"] == "stabilize_tooling"
        ]
        self.assertGreaterEqual(len(stabilized_steps), 1)
        self.assertEqual(stabilized_steps[0]["capability_id"], "connector.github")

    def test_graph_runtime_injects_execute_tooling_for_available_modules(self) -> None:
        intent = IntentCompiler(llm_client=False, strict_real=False).compile(
            "Executar conector disponível e validar saída",
            autonomy="autonomo",
        )
        task = TaskCompiler().compile(intent)
        decision = CognitiveControlPlane().decide(task)
        capability_resolution = {
            "available": [
                {
                    "id": "connector.github",
                    "module_path": "storage/tool_forge/generated/connector_github.py",
                }
            ],
            "missing": [],
            "degraded": [],
        }
        organization = OrganizationGenerator().generate(task, decision, capability_resolution)
        runtime = GraphRuntime()
        _, step_by_node, path = runtime._build_execution_graph(  # pylint: disable=protected-access
            organization,
            task=task,
            capability_resolution=capability_resolution,
        )

        execute_steps = [
            step_by_node[node_id]
            for node_id in path
            if step_by_node[node_id]["action"] == "execute_tooling"
        ]
        self.assertGreaterEqual(len(execute_steps), 1)
        self.assertEqual(execute_steps[0]["capability_id"], "connector.github")
        self.assertEqual(execute_steps[0]["agent_id"], "toolrunner_connector_github")
        self.assertEqual(
            execute_steps[0]["module_path"],
            "storage/tool_forge/generated/connector_github.py",
        )

    def test_graph_runtime_injects_compose_tooling_for_multiple_tooling_capabilities(self) -> None:
        intent = IntentCompiler(llm_client=False, strict_real=False).compile(
            "Executar conectores disponíveis e compor resultado integrado",
            autonomy="autonomo",
        )
        task = TaskCompiler().compile(intent)
        decision = CognitiveControlPlane().decide(task)
        capability_resolution = {
            "available": [
                {
                    "id": "connector.github",
                    "module_path": "storage/tool_forge/generated/connector_github.py",
                },
                {
                    "id": "connector.crm",
                    "module_path": "storage/tool_forge/generated/connector_crm.py",
                },
            ],
            "missing": [],
            "degraded": [],
        }
        organization = OrganizationGenerator().generate(task, decision, capability_resolution)
        runtime = GraphRuntime()
        _, step_by_node, path = runtime._build_execution_graph(  # pylint: disable=protected-access
            organization,
            task=task,
            capability_resolution=capability_resolution,
        )

        actions = [step_by_node[node_id]["action"] for node_id in path]
        compose_steps = [
            step_by_node[node_id]
            for node_id in path
            if step_by_node[node_id]["action"] == "compose_tooling"
        ]
        self.assertIn("compose_tooling", actions)
        self.assertGreaterEqual(len(compose_steps), 1)
        self.assertEqual(compose_steps[0]["agent_id"], "workflow_composer")

    def test_graph_runtime_pairs_dynamic_branches_by_capability(self) -> None:
        runtime = GraphRuntime()
        organization = SimpleNamespace(
            agents=[],
            workflow=[
                {"id": "step_frame", "agent_id": "framer", "action": "frame_intent", "output": "intent_frame"},
                {
                    "id": "step_design_a",
                    "agent_id": "toolsmith_connector_a",
                    "action": "design_tooling",
                    "output": "tool_specs_connector_a",
                    "capability_id": "connector.a",
                },
                {
                    "id": "step_design_b",
                    "agent_id": "toolsmith_connector_b",
                    "action": "design_tooling",
                    "output": "tool_specs_connector_b",
                    "capability_id": "connector.b",
                },
                {
                    "id": "step_stabilize_a",
                    "agent_id": "toolsmith_connector_a",
                    "action": "stabilize_tooling",
                    "output": "tool_stability_connector_a",
                    "capability_id": "connector.a",
                },
                {
                    "id": "step_stabilize_b",
                    "agent_id": "toolsmith_connector_b",
                    "action": "stabilize_tooling",
                    "output": "tool_stability_connector_b",
                    "capability_id": "connector.b",
                },
                {
                    "id": "step_execute_a",
                    "agent_id": "toolrunner_connector_a",
                    "action": "execute_tooling",
                    "output": "tool_exec_connector_a",
                    "capability_id": "connector.a",
                    "module_path": "storage/tool_forge/generated/connector_a.py",
                },
                {
                    "id": "step_execute_b",
                    "agent_id": "toolrunner_connector_b",
                    "action": "execute_tooling",
                    "output": "tool_exec_connector_b",
                    "capability_id": "connector.b",
                    "module_path": "storage/tool_forge/generated/connector_b.py",
                },
            ],
            topology="minimal_pipeline",
            required_capabilities=[],
        )
        task = SimpleNamespace(
            goal={"statement": "validar branches dinamicos", "type": "build_or_deliver"},
            deliverables=[],
            capability_needs=[],
            uncertainty=[],
            risk={"execution_risk": "low"},
        )
        capability_resolution = {
            "available": [
                {"id": "connector.a", "module_path": "storage/tool_forge/generated/connector_a.py"},
                {"id": "connector.b", "module_path": "storage/tool_forge/generated/connector_b.py"},
            ],
            "missing": [],
            "degraded": [],
        }

        graph, step_by_node, _ = runtime._build_execution_graph(  # pylint: disable=protected-access
            organization,
            task=task,
            capability_resolution=capability_resolution,
        )

        def node_for(action: str, capability_id: str) -> str:
            for node_id, item in step_by_node.items():
                if item.get("action") == action and item.get("capability_id") == capability_id:
                    return node_id
            raise AssertionError("node nao encontrado: %s %s" % (action, capability_id))

        def target_caps(source_node_id: str, target_action: str) -> set[str]:
            caps: set[str] = set()
            for edge in graph.iter_edges_from(source_node_id, kinds=[EdgeKind.ACTIVATES]):
                step = step_by_node.get(edge.target_id)
                if not step:
                    continue
                if step.get("action") != target_action:
                    continue
                cap_id = str(step.get("capability_id", "")).strip()
                if cap_id:
                    caps.add(cap_id)
            return caps

        def target_actions(source_node_id: str) -> set[str]:
            actions: set[str] = set()
            for edge in graph.iter_edges_from(source_node_id, kinds=[EdgeKind.ACTIVATES]):
                step = step_by_node.get(edge.target_id)
                if not step:
                    continue
                actions.add(str(step.get("action", "")).strip())
            return actions

        design_a = node_for("design_tooling", "connector.a")
        design_b = node_for("design_tooling", "connector.b")
        stabilize_a = node_for("stabilize_tooling", "connector.a")
        stabilize_b = node_for("stabilize_tooling", "connector.b")

        self.assertEqual(target_caps(design_a, "stabilize_tooling"), {"connector.a"})
        self.assertEqual(target_caps(design_b, "stabilize_tooling"), {"connector.b"})
        self.assertEqual(target_caps(design_a, "execute_tooling"), {"connector.a"})
        self.assertEqual(target_caps(design_b, "execute_tooling"), {"connector.b"})
        self.assertEqual(target_caps(stabilize_a, "execute_tooling"), {"connector.a"})
        self.assertEqual(target_caps(stabilize_b, "execute_tooling"), {"connector.b"})
        self.assertIn("compose_tooling", target_actions(design_a))
        self.assertIn("compose_tooling", target_actions(design_b))
        self.assertIn("compose_tooling", target_actions(stabilize_a))
        self.assertIn("compose_tooling", target_actions(stabilize_b))

    def test_execute_tooling_promotes_capability_after_repeated_real_success(self) -> None:
        runtime = GraphRuntime()
        graph = CognitiveGraph()
        capability = graph.add_node(
            CapabilityNode.tool(
                "connector.runtime",
                id="cap_connector_runtime",
                description="conector runtime",
                maturity="draft",
                payload={"state": "available"},
            )
        )
        synapse = graph.add_node(
            SynapseNode.specialist(
                "Tool Runner",
                id="syn_tool_runner_runtime",
                role="operator",
                objective="executar conector runtime",
                action="execute_tooling",
                capability_id="connector.runtime",
            )
        )
        exec_result = SimpleNamespace(success=True, fallback_used=False, output={"status": "executed"})

        runtime._evolve_capability_nodes(  # pylint: disable=protected-access
            graph=graph,
            node_id=synapse.id,
            step_item={"action": "execute_tooling", "capability_id": "connector.runtime"},
            exec_result=exec_result,
        )
        updated_1 = graph.get_node(capability.id)
        assert isinstance(updated_1, CapabilityNode)
        self.assertEqual(updated_1.maturity, "draft")
        self.assertEqual(updated_1.payload.get("real_execution_successes"), 1)

        runtime._evolve_capability_nodes(  # pylint: disable=protected-access
            graph=graph,
            node_id=synapse.id,
            step_item={"action": "execute_tooling", "capability_id": "connector.runtime"},
            exec_result=exec_result,
        )
        updated_2 = graph.get_node(capability.id)
        assert isinstance(updated_2, CapabilityNode)
        self.assertEqual(updated_2.maturity, "tested")
        self.assertEqual(updated_2.payload.get("real_execution_successes"), 2)

        runtime._evolve_capability_nodes(  # pylint: disable=protected-access
            graph=graph,
            node_id=synapse.id,
            step_item={"action": "execute_tooling", "capability_id": "connector.runtime"},
            exec_result=exec_result,
        )
        runtime._evolve_capability_nodes(  # pylint: disable=protected-access
            graph=graph,
            node_id=synapse.id,
            step_item={"action": "execute_tooling", "capability_id": "connector.runtime"},
            exec_result=exec_result,
        )
        updated_4 = graph.get_node(capability.id)
        assert isinstance(updated_4, CapabilityNode)
        self.assertEqual(updated_4.maturity, "trusted")
        self.assertEqual(updated_4.payload.get("real_execution_successes"), 4)

    def test_execute_tooling_demotes_capability_on_non_real_status(self) -> None:
        runtime = GraphRuntime()
        graph = CognitiveGraph()
        capability = graph.add_node(
            CapabilityNode.tool(
                "connector.runtime",
                id="cap_connector_runtime",
                description="conector runtime",
                maturity="tested",
                payload={"state": "available", "real_execution_successes": 3},
            )
        )
        synapse = graph.add_node(
            SynapseNode.specialist(
                "Tool Runner",
                id="syn_tool_runner_runtime_demote",
                role="operator",
                objective="executar conector runtime",
                action="execute_tooling",
                capability_id="connector.runtime",
            )
        )
        exec_result = SimpleNamespace(success=True, fallback_used=False, output={"status": "not_implemented"})

        runtime._evolve_capability_nodes(  # pylint: disable=protected-access
            graph=graph,
            node_id=synapse.id,
            step_item={"action": "execute_tooling", "capability_id": "connector.runtime"},
            exec_result=exec_result,
        )
        updated = graph.get_node(capability.id)
        assert isinstance(updated, CapabilityNode)
        self.assertEqual(updated.maturity, "draft")
        self.assertEqual(updated.payload.get("state"), "degraded")
        self.assertEqual(updated.payload.get("last_tool_execution_status"), "not_implemented")
        self.assertEqual(updated.payload.get("real_execution_successes"), 2)

    def test_execute_tooling_demotes_capability_on_failed_execution(self) -> None:
        runtime = GraphRuntime()
        graph = CognitiveGraph()
        capability = graph.add_node(
            CapabilityNode.tool(
                "connector.runtime",
                id="cap_connector_runtime",
                description="conector runtime",
                maturity="trusted",
                payload={"state": "available", "real_execution_successes": 5},
            )
        )
        synapse = graph.add_node(
            SynapseNode.specialist(
                "Tool Runner",
                id="syn_tool_runner_runtime_failed",
                role="operator",
                objective="executar conector runtime",
                action="execute_tooling",
                capability_id="connector.runtime",
            )
        )
        exec_result = SimpleNamespace(success=False, fallback_used=False, output={"status": "error"})

        runtime._evolve_capability_nodes(  # pylint: disable=protected-access
            graph=graph,
            node_id=synapse.id,
            step_item={"action": "execute_tooling", "capability_id": "connector.runtime"},
            exec_result=exec_result,
        )
        updated = graph.get_node(capability.id)
        assert isinstance(updated, CapabilityNode)
        self.assertEqual(updated.maturity, "tested")
        self.assertEqual(updated.payload.get("state"), "degraded")
        self.assertEqual(updated.payload.get("risk_level"), "high")
        self.assertEqual(updated.payload.get("last_tool_execution_status"), "error")
        self.assertEqual(updated.payload.get("real_execution_successes"), 4)

    def test_graph_runtime_seeds_workflow_when_organization_is_empty(self) -> None:
        intent = IntentCompiler(llm_client=False, strict_real=False).compile(
            "quero um plano simples com revisão crítica",
            autonomy="autonomo",
        )
        task = TaskCompiler().compile(intent)
        runtime = GraphRuntime()
        empty_org = SimpleNamespace(
            agents=[],
            workflow=[],
            topology="minimal_pipeline",
            required_capabilities=[],
        )
        _, step_by_node, path = runtime._build_execution_graph(  # pylint: disable=protected-access
            empty_org,
            task=task,
            capability_resolution={"available": [], "missing": [], "degraded": []},
        )
        actions = [step_by_node[node_id]["action"] for node_id in path]
        self.assertIn("frame_intent", actions)
        self.assertIn("decompose_work", actions)
        self.assertIn("draft_artifact", actions)
        self.assertIn("critic_review", actions)

    def test_tool_forge_executes_without_terms_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            result = kernel.run(
                "Criar conector para API do GitHub e integrar no workflow",
                autonomy="assistido",
                output_dir=base / "runs",
                session_id="sessao_sem_termos",
                terms_accepted=False,
            )
            self.assertIn("tool_forge_report", result.files)
            report = json.loads(result.files["tool_forge_report"].read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(report["created"]), 1)

    def test_graph_runtime_populates_synapses_capabilities_and_memories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            result = kernel.run(
                "Planeje um sistema com integração de API e análise de risco",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id="sessao_graph_dynamic",
            )

            graph_path = result.files["execution_graph"]
            graph = CognitiveGraph.load(graph_path)

            synapses = list(graph.iter_nodes(kind=NodeKind.SYNAPSE))
            capabilities = list(graph.iter_nodes(kind=NodeKind.CAPABILITY))
            memories = list(graph.iter_nodes(kind=NodeKind.MEMORY))

            self.assertGreaterEqual(len(synapses), 3)
            self.assertGreaterEqual(len(capabilities), 3)
            self.assertGreaterEqual(len(memories), 3)
            self.assertTrue(any(node.id.startswith("syn_") for node in synapses))
            self.assertTrue(any(node.id.startswith("cap_") for node in capabilities))
            self.assertTrue(any(node.id.startswith("mem_") for node in memories))

    def test_parallel_topology_creates_branching_activates_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)
            result = kernel.run(
                "Analise qualquer abordagem ideal para integrar qualquer API com dados de pagamento",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id="sessao_branching",
            )

            graph = CognitiveGraph.load(result.files["execution_graph"])
            max_out_degree = 0
            for node in graph.iter_nodes(kind=NodeKind.SYNAPSE):
                degree = len(list(graph.iter_edges_from(node.id, kinds=[EdgeKind.ACTIVATES])))
                max_out_degree = max(max_out_degree, degree)
            self.assertGreaterEqual(max_out_degree, 2)


if __name__ == "__main__":
    unittest.main()
