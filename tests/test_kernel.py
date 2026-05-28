from pathlib import Path
import json
import tempfile
import unittest

from arnaldo.capabilities.catalog import CapabilityCatalog
from arnaldo.components import ToolForge
from arnaldo.graph import CognitiveGraph, NodeKind
from arnaldo.kernel import ArnaldoKernel
from arnaldo.memory import MemoryStore
from arnaldo.runtime import GraphRuntime, SandboxManager
from arnaldo.session import SessionManager
from tests.support_llm import AlwaysSuccessTypedClient


class KernelTest(unittest.TestCase):
    def test_run_generates_generic_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            llm = AlwaysSuccessTypedClient()
            runtime = GraphRuntime(llm_client=llm)
            kernel = ArnaldoKernel(
                runtime=runtime,
                memory=MemoryStore(base / "memory"),
                session_manager=SessionManager(base / "sessions"),
                tool_forge=ToolForge(base / "tool_forge"),
                capabilities=CapabilityCatalog(registry_path=base / "capability_registry.json"),
                sandbox_manager=SandboxManager(base / "sandboxes"),
            )
            kernel.intent_compiler._llm_client = llm  # type: ignore[attr-defined]
            result = kernel.run(
                "Crie um plano inicial para uma ferramenta B2B de automacao",
                output_dir=base / "runs",
            )

            self.assertTrue(result.files["intent_ir"].exists())
            self.assertTrue(result.files["task_ir"].exists())
            self.assertTrue(result.files["organization_ir"].exists())
            self.assertTrue(result.files["artifact"].exists())
            self.assertTrue(result.files["evidence"].exists())
            self.assertTrue(result.files["trace"].exists())
            self.assertTrue(result.files["sandbox_state"].exists())
            self.assertTrue(result.files["execution_graph"].exists())
            sandbox = json.loads(result.files["sandbox_state"].read_text(encoding="utf-8"))
            self.assertTrue(Path(sandbox["workspace_path"]).exists())
            self.assertTrue((Path(sandbox["workspace_path"]) / "runtime-session.txt").exists())
            self.assertTrue((Path(sandbox["artifacts_path"]) / "artifact.md").exists())
            self.assertGreaterEqual(len(list(Path(sandbox["artifacts_path"]).glob("step-*.json"))), 1)

            task_ir = json.loads(result.files["task_ir"].read_text(encoding="utf-8"))
            self.assertEqual(task_ir["context"]["scope"], "generic")
            self.assertEqual(task_ir["goal"]["type"], "create_or_generate")
            self.assertNotIn("business" + "_research", json.dumps(task_ir))

            memory_graph = base / "memory" / "memory-graph.msgpack"
            self.assertTrue(memory_graph.exists())
            graph = CognitiveGraph.load(memory_graph)
            memories = list(graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False))
            self.assertGreaterEqual(len(memories), 1)
            self.assertIn("memory_hints", result.files)
            memory_hints = json.loads(result.files["memory_hints"].read_text(encoding="utf-8"))
            self.assertIn("preferred_actions", memory_hints)
            self.assertIn("transitions", memory_hints)


if __name__ == "__main__":
    unittest.main()
