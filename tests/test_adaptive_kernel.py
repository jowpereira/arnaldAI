from pathlib import Path
import json
import tempfile
import unittest

from arnaldo.capabilities.catalog import CapabilityCatalog
from arnaldo.components import ToolForge
from arnaldo.kernel import ArnaldoKernel
from arnaldo.memory import MemoryStore
from arnaldo.runtime import GraphRuntime, SandboxManager
from arnaldo.session import SessionManager
from tests.support_llm import AlwaysSuccessTypedClient


class AdaptiveKernelTest(unittest.TestCase):
    def _build_kernel(self, base: Path) -> ArnaldoKernel:
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
        return kernel

    def test_graph_mode_disables_governance_policy_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)

            result = kernel.run(
                "Deletar fluxo antigo e reorganizar operacao com risco controlado",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id="sessao_livre",
                terms_accepted=True,
            )

            policy = json.loads(result.files["policy_decision"].read_text(encoding="utf-8"))
            self.assertFalse(policy["approval_required"])
            self.assertIn("graph_runtime_governance_disabled", policy["reasons"])
            self.assertFalse(policy["telemetry"]["governance_enabled"])

    def test_tool_forge_scaffolds_missing_connector_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)

            result = kernel.run(
                "Quero criar um conector para API do GitHub e integrar no fluxo",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id="sessao_tools",
                terms_accepted=True,
            )

            self.assertIn("tool_forge_report", result.files)
            report = json.loads(result.files["tool_forge_report"].read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(report["created"]), 1)

            resolution = json.loads(result.files["capability_resolution"].read_text(encoding="utf-8"))
            missing_ids = {item["id"] for item in resolution["missing"]}
            self.assertNotIn("connector.http.generic", missing_ids)

    def test_session_persists_across_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            kernel = self._build_kernel(base)

            first = kernel.run(
                "Quero iniciar o agente com foco em integracoes",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id="sessao_continua",
                terms_accepted=True,
            )
            second = kernel.run(
                "Agora adiciona novas ferramentas e conectores",
                autonomy="autonomo",
                output_dir=base / "runs",
                session_id=first.session_id,
                terms_accepted=True,
            )

            self.assertEqual(first.session_id, second.session_id)
            state = json.loads(second.files["session_state"].read_text(encoding="utf-8"))
            self.assertEqual(state["id"], first.session_id)
            self.assertEqual(state["turns"], 2)

            history = base / "sessions" / f"{first.session_id}.history.jsonl"
            lines = [line for line in history.read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
