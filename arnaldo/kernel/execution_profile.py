"""Seleção genérica de perfil de execução a partir de capabilities e nível."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arnaldo.capabilities.semantics import summarize_capability_ids


@dataclass(slots=True, frozen=True)
class ExecutionProfile:
    """Perfil de execução escolhido para um turno."""

    name: str
    reason: str
    skip_full_pipeline: bool
    inline_capability_ids: tuple[str, ...] = ()


def _local_inline_capability_ids(capability_ids: Sequence[str]) -> tuple[str, ...]:
    summary = summarize_capability_ids(capability_ids)
    local_ids: list[str] = []
    seen: set[str] = set()
    for item in summary.items:
        executor_id = str(item.inline_lookup_executor_id or "").strip()
        if item.locality != "local" or not executor_id or executor_id in seen:
            continue
        seen.add(executor_id)
        local_ids.append(executor_id)
    return tuple(local_ids)


def select_execution_profile(
    *,
    level: str,
    needs_external_data: bool,
    capability_ids: Sequence[str],
) -> ExecutionProfile:
    """Escolhe o perfil mais simples que ainda preserva corretude."""
    normalized_level = str(level or "").strip().lower()
    summary = summarize_capability_ids(capability_ids)
    local_inline_capability_ids = _local_inline_capability_ids(capability_ids)

    if normalized_level == "complex":
        return ExecutionProfile(
            name="full_pipeline",
            reason="complex_request",
            skip_full_pipeline=False,
        )

    if summary.requires_full_pipeline:
        return ExecutionProfile(
            name="full_pipeline",
            reason="capabilities_require_orchestration",
            skip_full_pipeline=False,
        )

    if needs_external_data and not summary.supports_inline_lookup and not summary.has_any:
        return ExecutionProfile(
            name="full_pipeline",
            reason="external_data_without_lookup_capability",
            skip_full_pipeline=False,
        )

    if needs_external_data and summary.supports_inline_lookup:
        return ExecutionProfile(
            name="inline_capability",
            reason="read_only_lookup_capabilities",
            skip_full_pipeline=True,
            inline_capability_ids=summary.inline_lookup_executor_ids,
        )

    if normalized_level == "intermediate" and local_inline_capability_ids:
        return ExecutionProfile(
            name="inline_capability",
            reason="read_only_local_capabilities",
            skip_full_pipeline=True,
            inline_capability_ids=local_inline_capability_ids,
        )

    if normalized_level == "conversational":
        return ExecutionProfile(
            name="fast_response",
            reason="conversational_turn",
            skip_full_pipeline=True,
        )

    if normalized_level == "intermediate":
        return ExecutionProfile(
            name="medium_response",
            reason="single_shot_reasoning",
            skip_full_pipeline=True,
        )

    return ExecutionProfile(
        name="full_pipeline",
        reason="unknown_level",
        skip_full_pipeline=False,
    )
