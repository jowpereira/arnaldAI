"""Modelo tipado para necessidade de capability — substitui dict/str avulsos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class CapabilityNeed:
    """Necessidade tipada de capability produzida pelo classificador.

    Desacopla *o que* o request precisa de *qual* capability concreta
    resolve essa necessidade.  O resolvedor é quem faz o match.
    """

    family: str
    """Família semântica: search, connector, filesystem, shell, tool, …"""

    intent: str = "lookup"
    """Intenção: lookup, retrieve, transform, mutate, synthesize, execute."""

    freshness: str = "unknown"
    """Frescor exigido: static, recent, live, unknown."""

    side_effects: str = "none"
    """Efeitos colaterais: none, local, remote."""

    execution_mode: str = "single_step"
    """Modo de execução: single_step, multi_step, streaming, batch."""

    requires_network: bool = False

    read_only: bool = True

    requires_llm: bool = False

    preferred_capabilities: tuple[str, ...] = ()
    """IDs concretos que o classificador já sabe serem candidatos."""

    constraints: dict[str, Any] = field(default_factory=dict)

    reason: str = ""
    """Justificativa — útil para debug e auditabilidade."""

    required: bool = True


# ── Factories e conversores ──────────────────────────────────────────────


_FAMILY_DEFAULTS: dict[str, dict[str, Any]] = {
    "search": {
        "intent": "lookup",
        "freshness": "live",
        "requires_network": True,
        "read_only": True,
        "preferred_capabilities": ("search.public_web",),
    },
    "connector": {
        "intent": "retrieve",
        "freshness": "live",
        "requires_network": True,
        "read_only": False,
        "side_effects": "remote",
    },
    "filesystem": {
        "intent": "lookup",
        "freshness": "stable",
        "requires_network": False,
        "read_only": True,
        "preferred_capabilities": ("filesystem.local.search",),
    },
    "shell": {
        "intent": "execute",
        "freshness": "stable",
        "requires_network": False,
        "read_only": True,
        "preferred_capabilities": ("shell.local.readonly",),
    },
    "tool": {
        "intent": "execute",
        "freshness": "unknown",
        "requires_network": False,
        "read_only": False,
    },
}


def need_from_id(
    capability_id: str,
    *,
    required: bool = True,
    reason: str = "",
) -> CapabilityNeed:
    """Cria ``CapabilityNeed`` a partir de um capability_id (backward compat).

    Extrai a família do ID e aplica defaults semânticos.
    """
    normalized = str(capability_id or "").strip().lower()
    if not normalized:
        return CapabilityNeed(family="unknown", reason=reason, required=required)

    family = normalized.split(".", 1)[0]
    defaults = _FAMILY_DEFAULTS.get(family, {})

    preferred = defaults.get("preferred_capabilities", ())
    if normalized not in {"", family} and not normalized.endswith(".*"):
        preferred = (normalized, *[p for p in preferred if p != normalized])

    return CapabilityNeed(
        family=family,
        intent=defaults.get("intent", "lookup"),
        freshness=defaults.get("freshness", "unknown"),
        side_effects=defaults.get("side_effects", "none"),
        requires_network=defaults.get("requires_network", False),
        read_only=defaults.get("read_only", True),
        preferred_capabilities=tuple(preferred),
        reason=reason,
        required=required,
    )


def need_to_dict(need: CapabilityNeed) -> dict[str, Any]:
    """Serializa ``CapabilityNeed`` para dict (backward compat com IR)."""
    base: dict[str, Any] = {
        "id": need.preferred_capabilities[0] if need.preferred_capabilities else need.family,
        "family": need.family,
        "intent": need.intent,
        "freshness": need.freshness,
        "side_effects": need.side_effects,
        "execution_mode": need.execution_mode,
        "requires_network": need.requires_network,
        "read_only": need.read_only,
        "requires_llm": need.requires_llm,
        "required": need.required,
    }
    if need.preferred_capabilities:
        base["preferred_capabilities"] = list(need.preferred_capabilities)
    if need.constraints:
        base["constraints"] = need.constraints
    if need.reason:
        base["reason"] = need.reason
    return base


def needs_from_ids(
    capability_ids: list[str],
    *,
    required: bool = True,
) -> list[CapabilityNeed]:
    """Converte lista de IDs (formato antigo) em lista de ``CapabilityNeed``."""
    seen: set[str] = set()
    result: list[CapabilityNeed] = []
    for cap_id in capability_ids:
        normalized = str(cap_id or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(need_from_id(normalized, required=required))
    return result
