from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from arnaldo import cli


class _DummyResult:
    def __init__(self, artifact: Path | None, evidence: Path | None = None) -> None:
        self.files = {}
        if artifact is not None:
            self.files["artifact"] = artifact
        if evidence is not None:
            self.files["evidence"] = evidence


class CliResponsePreviewTest(unittest.TestCase):
    def test_build_agent_response_preview_reads_goal_outputs_and_actions(self) -> None:
        artifact = """# Artifact

## Goal
Responder o usuario em tom objetivo.

## Step Outputs
- `draft_artifact`: primary_artifact

## Next Actions
- seguir com a execucao
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.md"
            path.write_text(artifact, encoding="utf-8")
            result = _DummyResult(path)
            preview = cli._build_agent_response_preview(result)

        self.assertIn("Goal:", preview)
        self.assertIn("Responder o usuario", preview)
        self.assertIn("Step Outputs:", preview)
        self.assertIn("Next Actions:", preview)

    def test_build_agent_response_preview_prefers_resposta_section(self) -> None:
        artifact = """# Artifact

## Resposta
Ola! Tudo certo por aqui.
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.md"
            path.write_text(artifact, encoding="utf-8")
            result = _DummyResult(path)
            preview = cli._build_agent_response_preview(result)

        self.assertIn("Resposta:", preview)
        self.assertIn("Ola! Tudo certo por aqui.", preview)

    def test_build_agent_response_preview_includes_latest_step_output(self) -> None:
        artifact = """# Artifact

## Goal
Responder no terminal.
"""
        evidence = (
            '{"record_type":"step_completed","payload":{"result":{"sections":'
            '["status: resposta pronta","evidence: contexto lido"],'
            '"evidence":["fonte_a"],"uncertainties":["nenhuma"]}}}\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / "artifact.md"
            evidence_path = Path(tmp) / "evidence.jsonl"
            artifact_path.write_text(artifact, encoding="utf-8")
            evidence_path.write_text(evidence, encoding="utf-8")
            result = _DummyResult(artifact_path, evidence_path)
            preview = cli._build_agent_response_preview(result)

        self.assertIn("Output do Synapse:", preview)
        self.assertIn("status: resposta pronta", preview)
        self.assertIn("Goal:", preview)

    def test_build_agent_response_preview_returns_empty_when_missing_artifact(self) -> None:
        result = _DummyResult(None)
        preview = cli._build_agent_response_preview(result)
        self.assertEqual(preview, "")


class CliStreamingTest(unittest.TestCase):
    def test_discover_new_run_dir_returns_only_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_run = base / "run_old"
            new_run = base / "run_new"
            old_run.mkdir()
            new_run.mkdir()
            known = {"run_old"}

            selected = cli._discover_new_run_dir(base, known)

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.name, "run_new")
        self.assertIn("run_new", known)

    def test_run_streamer_prints_trace_and_evidence_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_dir = base / "run_stream"
            run_dir.mkdir(parents=True)
            (run_dir / "trace.jsonl").write_text(
                '{"created_at":"2026-05-18T10:00:00+00:00","event_type":"step_completed","payload":{"action":"draft_artifact","agent_id":"operator"}}\n',
                encoding="utf-8",
            )
            (run_dir / "evidence.jsonl").write_text(
                '{"created_at":"2026-05-18T10:00:01+00:00","record_type":"step_completed","summary":"ok","payload":{"action":"draft_artifact"}}\n',
                encoding="utf-8",
            )
            (run_dir / "agent_bus.jsonl").write_text(
                '{"ts":"2026-05-18T10:00:02+00:00","event":"agent_step_completed","agent_id":"operator","action":"draft_artifact"}\n',
                encoding="utf-8",
            )
            (run_dir / "prompts.jsonl").write_text(
                '{"created_at":"2026-05-18T10:00:03+00:00","node_id":"syn_operator_draft_artifact_primary_artifact","action":"draft_artifact","tier":"fast","response_model":"ArtifactDraftOutput","messages":[{"role":"system","content":"sys prompt"},{"role":"user","content":"user prompt"}],"chat_kwargs":{"max_tokens":320,"timeout":20.0}}\n',
                encoding="utf-8",
            )

            streamer = cli._RunStreamer(output_dir=base, known_run_dirs=set())
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                streamer.poll()
            output = buffer.getvalue()

        self.assertIn("STREAMING", output)
        self.assertIn("[trace] step_completed", output)
        self.assertIn("[evidence] step_completed", output)
        self.assertIn("[agent] agent_step_completed", output)
        self.assertIn("[prompt] syn_operator_draft_artifact_primary_artifact", output)
        self.assertIn("[system] sys prompt", output)


if __name__ == "__main__":
    unittest.main()
