"""Testes para pós-processamento do pipeline — gap detection bloqueia gravação."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from arnaldo.reality.gap import RealityGapDetector


# ── RealityGapDetector ───────────────────────────────────────────────


def test_gap_detector_reports_missing_deliverables() -> None:
    task = SimpleNamespace(
        deliverables=[
            {"id": "primary_artifact"},
            {"id": "execution_evidence"},
            {"id": "next_actions"},
        ]
    )
    step_results = [{"output": "primary_artifact", "success": True}]
    report = RealityGapDetector().analyze(task, step_results)
    assert report.status == "gap_detected"
    assert "deliverables_missing" in report.warnings


def test_gap_detector_ok_when_all_present() -> None:
    task = SimpleNamespace(
        deliverables=[
            {"id": "primary_artifact"},
            {"id": "execution_evidence"},
        ]
    )
    step_results = [
        {"output": "primary_artifact", "success": True, "result": {"summary": "ok"}},
        {"output": "execution_evidence", "success": True, "result": {"summary": "ok"}},
    ]
    report = RealityGapDetector().analyze(task, step_results)
    assert report.status == "ok"


def test_gap_detector_reports_failed_steps() -> None:
    task = SimpleNamespace(deliverables=[{"id": "x"}])
    step_results = [{"output": "x", "success": False}]
    report = RealityGapDetector().analyze(task, step_results)
    assert report.status == "gap_detected"
    assert any("steps_failed" in w for w in report.warnings)


# ── Pipeline gap → sessão/memória ────────────────────────────────────


class MockMemory:
    """Mock mínimo de MemoryStore."""

    def __init__(self) -> None:
        self.records: list[Any] = []

    def append(self, record: Any) -> None:
        self.records.append(record)


class MockSessions:
    """Mock mínimo de SessionManager."""

    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []

    def record_turn(
        self, session: Any, user_message: str, system_summary: str, **kwargs: Any
    ) -> Any:
        self.turns.append(
            {
                "user_message": user_message,
                "system_summary": system_summary,
                "metadata": kwargs.get("metadata", {}),
            }
        )
        return session


def test_gap_report_quality_score_below_1_on_failures() -> None:
    task = SimpleNamespace(deliverables=[{"id": "a"}])
    steps = [
        {"output": "a", "success": False},
        {"output": "a", "success": True},
    ]
    report = RealityGapDetector().analyze(task, steps)
    assert report.quality_score < 1.0


def test_gap_report_detects_shallow_outputs() -> None:
    task = SimpleNamespace(deliverables=[{"id": "a"}, {"id": "b"}])
    steps = [
        {"output": "a", "success": True, "content": ""},
        {"output": "b", "success": True, "content": "   "},
    ]
    report = RealityGapDetector().analyze(task, steps)
    assert "outputs_shallow" in report.warnings
