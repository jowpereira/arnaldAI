from __future__ import annotations

from pathlib import Path
import tempfile

from arnaldo.components import ToolForge


def test_tool_forge_smoke_executes_generated_scaffold() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        forge = ToolForge(base_dir=base / "tool_forge")

        report = forge.forge_missing(
            [{"id": "connector.runtime.sample", "reason": "missing_capability"}],
            session_id="sessao_smoke",
        )

        assert len(report["failed"]) == 0
        assert len(report["created"]) == 1
        created = report["created"][0]
        assert created["status"] == "draft"
        assert created["test"] == "py_compile_and_run_ok"
        assert created["smoke_status"] == "not_implemented"

        module_path = Path(created["module_path"])
        assert module_path.exists()
        metadata_path = module_path.with_suffix(".json")
        assert metadata_path.exists()


def test_tool_forge_generated_capability_keeps_module_path_policy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        forge = ToolForge(base_dir=base / "tool_forge")

        report = forge.forge_missing(
            [{"id": "connector.crm.sync", "reason": "optional_capability_not_registered"}],
            session_id="sessao_policy",
        )
        assert len(report["capabilities"]) == 1
        capability = report["capabilities"][0]
        assert capability.id == "connector.crm.sync"
        assert capability.policies.get("module_path")
        assert capability.policies.get("maturity") == "draft"
