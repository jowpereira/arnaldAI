"""Seleção genérica de perfil de execução a partir de capabilities e nível.

7 perfis canônicos:
- conversational_fast    — saudação, trivial, sem retrieval
- retrieval_augmented    — pergunta conceitual, 1 LLM call + grafo
- live_lookup            — dado externo read-only, inline
- tool_execution_local   — shell/filesystem local read-only
- structured_multistep   — multi-step com orquestração
- artifact_pipeline      — geração de artefato complexo
- connector_workflow     — integração com side-effects remotos
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arnaldo.capabilities.resolver import CapabilityResolution, get_resolver
from arnaldo.capabilities.semantics import summarize_capability_ids


@dataclass(slots=True, frozen=True)
class ExecutionProfile:
    """Perfil de execução escolhido para um turno."""

    name: str
    reason: str
    skip_full_pipeline: bool
    inline_capability_ids: tuple[str, ...] = ()
    strict_on_llm_failure: bool = True


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
    """Escolhe perfil via resolução genérica — sem ``if`` por domínio."""
    normalized_level = str(level or "").strip().lower()
    resolution = get_resolver().resolve_from_ids(list(capability_ids))
    summary = summarize_capability_ids(capability_ids)
    local_inline = _local_inline_capability_ids(capability_ids)

    # 1) Complexo explícito → full pipeline
    if normalized_level == "complex":
        return _complex_profile(resolution)

    # 2) Capabilities exigem pipeline completo (orchestration, write, etc.)
    if summary.requires_full_pipeline:
        return ExecutionProfile(
            name="structured_multistep",
            reason="capabilities_require_orchestration",
            skip_full_pipeline=False,
            strict_on_llm_failure=True,
        )

    # 3) Dado externo + inline disponível → live_lookup
    if needs_external_data and resolution.has_inline:
        return ExecutionProfile(
            name="live_lookup",
            reason="read_only_lookup_capabilities",
            skip_full_pipeline=True,
            inline_capability_ids=resolution.inline_capable,
            strict_on_llm_failure=False,
        )

    # 3b) Dado externo + famílias abstratas remotas sem inline explícito
    #     → summary resolve para search.public_web
    if needs_external_data and summary.supports_inline_lookup:
        return ExecutionProfile(
            name="live_lookup",
            reason="abstract_remote_family_resolved",
            skip_full_pipeline=True,
            inline_capability_ids=summary.inline_lookup_executor_ids,
            strict_on_llm_failure=False,
        )

    # 4) Dado externo sem capability inline → full pipeline
    if needs_external_data and not resolution.has_inline and not summary.has_any:
        return ExecutionProfile(
            name="structured_multistep",
            reason="external_data_without_lookup_capability",
            skip_full_pipeline=False,
            strict_on_llm_failure=True,
        )

    # 5) Intermediário com local inline → tool_execution_local
    if normalized_level == "intermediate" and local_inline:
        return ExecutionProfile(
            name="tool_execution_local",
            reason="read_only_local_capabilities",
            skip_full_pipeline=True,
            inline_capability_ids=local_inline,
            strict_on_llm_failure=False,
        )

    # 6) Conversacional → fast
    if normalized_level == "conversational":
        return ExecutionProfile(
            name="conversational_fast",
            reason="conversational_turn",
            skip_full_pipeline=True,
        )

    # 7) Intermediário sem tooling → retrieval augmented
    if normalized_level == "intermediate":
        return ExecutionProfile(
            name="retrieval_augmented",
            reason="single_shot_reasoning",
            skip_full_pipeline=True,
        )

    # 8) Desconhecido → conservador
    return ExecutionProfile(
        name="structured_multistep",
        reason="unknown_level",
        skip_full_pipeline=False,
        strict_on_llm_failure=True,
    )


def _complex_profile(resolution: CapabilityResolution) -> ExecutionProfile:
    """Seleciona sub-perfil para requests complexos."""
    # Connector com side-effects → connector_workflow
    if not resolution.all_read_only and resolution.requires_network:
        return ExecutionProfile(
            name="connector_workflow",
            reason="complex_with_remote_side_effects",
            skip_full_pipeline=False,
            strict_on_llm_failure=True,
        )
    return ExecutionProfile(
        name="artifact_pipeline",
        reason="complex_request",
        skip_full_pipeline=False,
        strict_on_llm_failure=True,
    )
