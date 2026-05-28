"""Catálogo unificado de capabilities — fonte única de verdade.

Unifica o registro de capabilities concretas, dinâmicas (forge) e
internas num único catálogo com metadata operacional completa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(slots=True, frozen=True)
class CapabilityDescriptor:
    """Metadata operacional unificada de uma capability concreta."""

    capability_id: str
    """Identificador canônico: ``search.public_web``, ``fx.rate``, etc."""

    family: str
    """Família semântica: search, connector, filesystem, shell, tool, …"""

    fqn: str
    """Fully-qualified name da classe executora (vazio se interna)."""

    name: str
    """Nome legível para exibição."""

    description: str
    """Descrição para TF-IDF indexing e prompt context."""

    # ── Metadata operacional ──

    requires_network: bool = False
    read_only: bool = True
    supports_live_lookup: bool = False
    supports_inline: bool = False
    supports_batch: bool = False
    supports_streaming: bool = False
    degrades_gracefully: bool = False

    preferred_intents: tuple[str, ...] = ()
    """Intenções que esta capability atende: lookup, retrieve, etc."""

    cost_profile: str = "free"
    """free, low, medium, high."""

    latency_profile: str = "fast"
    """instant, fast, slow."""

    # ── Traits derivados (substituem ``_BUILTIN_TRAITS``) ──

    locality: str = "local"
    """local, remote, internal."""

    access_mode: str = "lookup"
    """lookup, integration, command, discovery, tooling, orchestration."""

    effect: str = "read"
    """read, write, orchestrate, unknown."""

    freshness: str = "stable"
    """current, stable, unknown."""

    # ── Orquestração ──

    internal: bool = False
    """``True`` para capabilities cognitivas/orquestradoras sem executor."""


class CapabilityCatalog:
    """Fonte única de verdade para capabilities registradas.

    Absorve o antigo ``CapabilityRegistry``: registro, resolução,
    persistência de capabilities dinâmicas e lookup por ID.
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        self._descriptors: dict[str, CapabilityDescriptor] = {}
        self._dynamic: dict[str, dict[str, Any]] = {}
        self._builtin_ids: set[str] = set()
        self._registry_path = registry_path or Path("storage/capability_registry.json")
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        _register_builtins(self)
        self._builtin_ids = set(self._descriptors.keys())
        self._load_dynamic()

    def register(self, descriptor: CapabilityDescriptor) -> None:
        """Registra capability no catálogo."""
        self._descriptors[descriptor.capability_id] = descriptor

    def register_dynamic(
        self,
        capability_id: str,
        *,
        name: str = "",
        description: str = "",
        module_path: str = "",
        maturity: str = "draft",
        health: str = "degraded",
        real_execution_successes: int = 0,
        last_tool_execution_status: str = "",
        persist: bool = True,
    ) -> None:
        """Registra capability dinâmica (forge) no catálogo."""
        data: dict[str, Any] = {
            "id": capability_id,
            "name": name or f"Generated {capability_id}",
            "description": description or "Conector gerado pelo ToolForge.",
            "module_path": module_path,
            "maturity": maturity,
            "health": health,
        }
        if real_execution_successes > 0:
            data["real_execution_successes"] = real_execution_successes
        if last_tool_execution_status:
            data["last_tool_execution_status"] = last_tool_execution_status
        self._dynamic[capability_id] = data
        family = capability_id.split(".", 1)[0] if "." in capability_id else "tool"
        self._descriptors[capability_id] = CapabilityDescriptor(
            capability_id=capability_id,
            family=family,
            fqn=module_path,
            name=name or f"Generated {capability_id}",
            description=description or "Conector gerado pelo ToolForge.",
            requires_network=family in ("connector", "search"),
            read_only=False,
            supports_live_lookup=False,
            supports_inline=False,
            degrades_gracefully=False,
            locality="remote" if family in ("connector", "search") else "local",
            access_mode="integration" if family == "connector" else "tooling",
            effect="unknown",
            freshness="unknown",
        )
        if persist:
            self._persist_dynamic()

    def remove(self, capability_id: str, *, persist: bool = True) -> None:
        """Remove capability dinâmica do catálogo."""
        self._descriptors.pop(capability_id, None)
        self._dynamic.pop(capability_id, None)
        if persist:
            self._persist_dynamic()

    def get(self, capability_id: str) -> CapabilityDescriptor | None:
        """Retorna descriptor ou None."""
        return self._descriptors.get(capability_id)

    def get_dynamic_meta(self, capability_id: str) -> dict[str, Any] | None:
        """Retorna metadata dinâmica bruta (module_path, maturity, etc.)."""
        return self._dynamic.get(capability_id)

    def list_all(self) -> list[CapabilityDescriptor]:
        """Todas as capabilities registradas."""
        return list(self._descriptors.values())

    def list_by_family(self, family: str) -> list[CapabilityDescriptor]:
        """Capabilities de uma família específica."""
        return [d for d in self._descriptors.values() if d.family == family]

    def can_execute(self, capability_id: str) -> bool:
        """``True`` se a capability tem executor real (não-interna)."""
        desc = self._descriptors.get(capability_id)
        return desc is not None and bool(desc.fqn) and not desc.internal

    def supports_inline(self, capability_id: str) -> bool:
        """``True`` se a capability pode rodar fora do pipeline completo."""
        desc = self._descriptors.get(capability_id)
        return desc is not None and desc.supports_inline

    def executable_ids(self) -> list[str]:
        """IDs de capabilities com executor real."""
        return [d.capability_id for d in self._descriptors.values() if d.fqn and not d.internal]

    def fqn_map(self) -> dict[str, str]:
        """Mapa capability_id → FQN para lazy-loading de executores."""
        return {
            d.capability_id: d.fqn for d in self._descriptors.values() if d.fqn and not d.internal
        }

    def is_builtin(self, capability_id: str) -> bool:
        """``True`` se a capability é nativa (registrada no bootstrap)."""
        return capability_id in self._builtin_ids

    def resolve(self, capability_needs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Resolve needs em available/missing/degraded — formato do runtime."""
        available: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []
        degraded: List[Dict[str, Any]] = []
        for need in capability_needs:
            capability_id = str(need.get("id", "")).strip()
            if not capability_id:
                continue
            desc = self._descriptors.get(capability_id)
            if desc is not None:
                entry = _descriptor_to_resolution_entry(desc, self._dynamic.get(capability_id))
                health = entry.get("risk", {}).get("health", "stable")
                bucket = degraded if health != "stable" else available
                bucket.append(entry)
            elif need.get("required", False):
                missing.append(
                    {
                        "id": capability_id,
                        "reason": "capability_not_registered",
                        "severity": "high",
                    }
                )
            else:
                degraded.append(
                    {
                        "id": capability_id,
                        "reason": "optional_capability_not_registered",
                        "severity": "low",
                        "risk": {
                            "level": "low",
                            "health": "degraded",
                            "reasons": ["optional_missing"],
                        },
                        "policies": {"requires_approval": False, "maturity": "scaffolded"},
                    }
                )
        return {"available": available, "missing": missing, "degraded": degraded}

    # ── Persistência de capabilities dinâmicas ──

    def _load_dynamic(self) -> None:
        if not self._registry_path.exists():
            return
        try:
            items = json.loads(self._registry_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for item in items:
            cap_id = str(item.get("id", "")).strip()
            if not cap_id:
                continue
            # Flat format (novo) tem campos no top-level;
            # nested format (legado) usa policies/risk.
            policies = item.get("policies") or {}
            risk = item.get("risk") or {}
            module_path = str(item.get("module_path", "") or policies.get("module_path", ""))
            maturity = str(item.get("maturity", "") or policies.get("maturity", "draft")) or "draft"
            health = str(item.get("health", "") or risk.get("health", "degraded")) or "degraded"
            self.register_dynamic(
                cap_id,
                name=item.get("name", ""),
                description=item.get("description", ""),
                module_path=module_path,
                maturity=maturity,
                health=health,
                real_execution_successes=int(item.get("real_execution_successes", 0) or 0),
                last_tool_execution_status=str(item.get("last_tool_execution_status", "")),
                persist=False,
            )

    def _persist_dynamic(self) -> None:
        items = list(self._dynamic.values())
        self._registry_path.write_text(
            json.dumps(items, indent=2, ensure_ascii=True), encoding="utf-8"
        )


# ── Instância global (singleton de módulo) ──────────────────────────────

_global_catalog: CapabilityCatalog | None = None


def get_catalog() -> CapabilityCatalog:
    """Retorna instância global do catálogo. Thread-safe por GIL."""
    global _global_catalog
    if _global_catalog is None:
        _global_catalog = CapabilityCatalog()
    return _global_catalog


# ── Helpers de resolução ─────────────────────────────────────────────────


def _descriptor_to_resolution_entry(
    desc: CapabilityDescriptor,
    dynamic_meta: dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Converte CapabilityDescriptor p/ entry compatível com runtime."""
    health = "stable"
    policies: Dict[str, Any] = {
        "requires_approval": False,
        "module_path": desc.fqn or "",
    }
    if dynamic_meta:
        maturity = dynamic_meta.get("maturity", "draft")
        health = dynamic_meta.get("health", "degraded")
        policies["maturity"] = maturity
    return {
        "id": desc.capability_id,
        "name": desc.name,
        "description": desc.description,
        "inputs": {},
        "outputs": {},
        "risk": {
            "level": "low" if health == "stable" else "medium",
            "health": health,
            "reasons": [] if health == "stable" else [f"maturity_{policies.get('maturity', '')}"],
        },
        "policies": policies,
    }


# ── Registro de builtins ─────────────────────────────────────────────────


def _register_builtins(catalog: CapabilityCatalog) -> None:
    """Registra capabilities nativas do substrate."""
    from .catalog_builtins import BUILTIN_DESCRIPTORS

    for descriptor in BUILTIN_DESCRIPTORS:
        catalog.register(descriptor)
