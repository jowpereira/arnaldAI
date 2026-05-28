"""Semântica centralizada de capabilities — traits, enriquecimento e resumo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(slots=True, frozen=True)
class CapabilityTraits:
    """Traits operacionais derivados de um capability_id."""

    capability_id: str
    family: str
    locality: str
    access_mode: str
    effect: str
    freshness: str
    abstract: bool = False
    inline_lookup_executor_id: str = ""


@dataclass(slots=True, frozen=True)
class CapabilitySummary:
    """Resumo agregado para roteamento genérico de execução."""

    items: tuple[CapabilityTraits, ...]
    inline_lookup_executor_ids: tuple[str, ...]
    has_local_access: bool
    has_remote_access: bool
    has_tooling: bool
    has_orchestration: bool
    requires_full_pipeline: bool

    @property
    def has_any(self) -> bool:
        return bool(self.items)

    @property
    def supports_inline_lookup(self) -> bool:
        return bool(self.inline_lookup_executor_ids)


_INTERNAL_FAMILIES = {"intent", "work", "organization", "artifact", "validation", "evidence"}


def _traits_from_catalog(capability_id: str) -> CapabilityTraits | None:
    """Tenta derivar traits do catálogo unificado."""
    from arnaldo.capabilities.catalog import get_catalog

    desc = get_catalog().get(capability_id)
    if desc is None:
        return None
    return CapabilityTraits(
        capability_id=desc.capability_id,
        family=desc.family,
        locality=desc.locality,
        access_mode=desc.access_mode,
        effect=desc.effect,
        freshness=desc.freshness,
        abstract=False,
        inline_lookup_executor_id=(desc.capability_id if desc.supports_inline else ""),
    )


def describe_capability_id(capability_id: str) -> CapabilityTraits:
    """Normaliza um capability_id e devolve seus traits operacionais."""
    normalized = str(capability_id or "").strip().lower()
    if not normalized:
        return CapabilityTraits(
            capability_id="",
            family="unknown",
            locality="unknown",
            access_mode="unknown",
            effect="unknown",
            freshness="unknown",
        )
    # 1) Consulta catálogo unificado (fonte primária)
    catalog_traits = _traits_from_catalog(normalized)
    if catalog_traits is not None:
        return catalog_traits

    family = normalized.split(".", 1)[0]
    abstract = normalized.endswith(".*") or "." not in normalized

    if family == "search":
        # Resolução via catálogo: se concreto, busca executor real
        inline_executor = ""
        if not abstract:
            from .catalog import get_catalog

            desc = get_catalog().get(normalized)
            if desc is not None and desc.supports_inline:
                inline_executor = normalized
        return CapabilityTraits(
            capability_id=normalized,
            family="search",
            locality="remote",
            access_mode="lookup",
            effect="read",
            freshness="current",
            abstract=abstract,
            inline_lookup_executor_id=inline_executor,
        )
    if family == "connector":
        return CapabilityTraits(
            capability_id=normalized,
            family="connector",
            locality="remote",
            access_mode="integration",
            effect="unknown",
            freshness="unknown",
            abstract=abstract,
        )
    if family == "filesystem":
        return CapabilityTraits(
            capability_id=normalized,
            family="filesystem",
            locality="local",
            access_mode="discovery",
            effect="read",
            freshness="stable",
            abstract=abstract,
            inline_lookup_executor_id="" if abstract else normalized,
        )
    if family == "shell":
        return CapabilityTraits(
            capability_id=normalized,
            family="shell",
            locality="local",
            access_mode="command",
            effect="read",
            freshness="stable",
            abstract=abstract,
            inline_lookup_executor_id="" if abstract else normalized,
        )
    if family == "tool":
        return CapabilityTraits(
            capability_id=normalized,
            family="tool",
            locality="internal",
            access_mode="tooling",
            effect="unknown",
            freshness="unknown",
            abstract=abstract,
        )
    if family in _INTERNAL_FAMILIES:
        return CapabilityTraits(
            capability_id=normalized,
            family=family,
            locality="internal",
            access_mode="orchestration",
            effect="orchestrate",
            freshness="stable",
            abstract=abstract,
        )
    return CapabilityTraits(
        capability_id=normalized,
        family=family or "unknown",
        locality="unknown",
        access_mode="unknown",
        effect="unknown",
        freshness="unknown",
        abstract=abstract,
    )


def summarize_capability_ids(capability_ids: Sequence[str]) -> CapabilitySummary:
    """Resume um conjunto de capabilities para roteamento genérico."""
    items: list[CapabilityTraits] = []
    inline_lookup_executor_ids: list[str] = []
    seen_inline: set[str] = set()
    has_local_access = False
    has_remote_access = False
    has_tooling = False
    has_orchestration = False
    requires_full_pipeline = False
    has_abstract_remote_family = False

    for raw_id in capability_ids:
        traits = describe_capability_id(str(raw_id))
        if not traits.capability_id:
            continue
        items.append(traits)
        has_local_access = has_local_access or traits.locality == "local"
        has_remote_access = has_remote_access or traits.locality == "remote"
        has_tooling = has_tooling or traits.access_mode == "tooling"
        has_orchestration = has_orchestration or traits.access_mode == "orchestration"
        has_abstract_remote_family = has_abstract_remote_family or (
            traits.abstract and traits.locality == "remote"
        )
        requires_full_pipeline = requires_full_pipeline or _traits_require_full_pipeline(traits)
        executor_id = str(traits.inline_lookup_executor_id or "").strip()
        if executor_id and executor_id not in seen_inline:
            seen_inline.add(executor_id)
            inline_lookup_executor_ids.append(executor_id)

    if not inline_lookup_executor_ids and has_abstract_remote_family and not requires_full_pipeline:
        # Consulta catálogo para capabilities inline de busca
        from .catalog import get_catalog

        catalog = get_catalog()
        for desc in catalog.list_by_family("search"):
            if desc.supports_inline and desc.fqn and not desc.internal:
                inline_lookup_executor_ids.append(desc.capability_id)
                break

    return CapabilitySummary(
        items=tuple(items),
        inline_lookup_executor_ids=tuple(inline_lookup_executor_ids),
        has_local_access=has_local_access,
        has_remote_access=has_remote_access,
        has_tooling=has_tooling,
        has_orchestration=has_orchestration,
        requires_full_pipeline=requires_full_pipeline,
    )


def build_capability_need(
    capability_id: str,
    *,
    required: bool = True,
    reason: str = "",
) -> dict[str, Any]:
    """Constroi um need enriquecido com metadata semântica."""
    traits = describe_capability_id(capability_id)
    payload: dict[str, Any] = {
        "id": traits.capability_id or str(capability_id).strip(),
        "required": bool(required),
        "family": traits.family,
        "locality": traits.locality,
        "access_mode": traits.access_mode,
        "effect": traits.effect,
        "freshness": traits.freshness,
    }
    if traits.abstract:
        payload["abstract"] = True
    if traits.inline_lookup_executor_id:
        payload["inline_lookup_executor_id"] = traits.inline_lookup_executor_id
    if reason:
        payload["reason"] = reason
    return payload


def _traits_require_full_pipeline(traits: CapabilityTraits) -> bool:
    if traits.locality == "local":
        return not bool(traits.effect == "read" and traits.inline_lookup_executor_id)
    if traits.effect == "write":
        return True
    if traits.access_mode == "orchestration":
        return True
    if traits.family == "connector" and not traits.abstract:
        return True
    if traits.access_mode == "tooling" and not traits.abstract:
        return True
    return False
