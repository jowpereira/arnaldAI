"""Testes para TaskCompiler — propagação de capability_needs."""

from __future__ import annotations

from arnaldo.components.task_compiler import TaskCompiler, build_capability_needs
from arnaldo.contracts import IntentIR, new_id, utc_now


def _make_intent(**overrides) -> IntentIR:
    """Cria IntentIR mínimo para testes."""
    defaults = dict(
        version="intent-ir/v0",
        id=new_id("intent"),
        created_at=utc_now(),
        original_request="teste",
        desired_state="testar",
        primary_goal="open_ended_execution",
        constraints={},
        autonomy={"level": "assistido"},
        signals={
            "ambiguity_score": 0,
            "external_impact_score": 0,
            "data_sensitivity_score": 0,
            "irreversibility_score": 0,
        },
        open_questions=[],
        inferred_requirements=[],
    )
    defaults.update(overrides)
    return IntentIR(**defaults)


# ── build_capability_needs ───────────────────────────────────────────


def test_build_capability_needs_returns_6_defaults() -> None:
    needs = build_capability_needs()
    assert len(needs) == 6
    ids = {n["id"] for n in needs}
    assert "intent.structure" in ids
    assert "artifact.draft" in ids


def test_build_capability_needs_adds_extras() -> None:
    needs = build_capability_needs(["filesystem.local.search", "shell.local.readonly"])
    ids = {n["id"] for n in needs}
    assert "filesystem.local.search" in ids
    assert "shell.local.readonly" in ids
    assert len(needs) == 8  # 6 default + 2 novos


def test_build_capability_needs_deduplicates() -> None:
    needs = build_capability_needs(["intent.structure", "artifact.draft"])
    ids = [n["id"] for n in needs]
    assert ids.count("intent.structure") == 1
    assert len(needs) == 6  # sem duplicação


def test_build_capability_needs_empty_extras() -> None:
    needs_none = build_capability_needs(None)
    needs_empty = build_capability_needs([])
    assert len(needs_none) == len(needs_empty) == 6


# ── TaskCompiler.compile ─────────────────────────────────────────────


def test_compile_propagates_extra_capabilities() -> None:
    compiler = TaskCompiler()
    intent = _make_intent()
    task = compiler.compile(intent, extra_capability_needs=["filesystem.local.search"])
    ids = {n["id"] for n in task.capability_needs}
    assert "filesystem.local.search" in ids


def test_compile_without_extras_has_default_capabilities() -> None:
    compiler = TaskCompiler()
    intent = _make_intent()
    task = compiler.compile(intent)
    ids = {n["id"] for n in task.capability_needs}
    assert len(ids) == 6
    assert "filesystem.local.search" not in ids
