"""Resolvedor genérico: CapabilityNeed → CapabilityDescriptor.

Sem ``if`` por domínio.  A resolução usa metadata do catálogo
para escolher a capability concreta mais adequada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .catalog import CapabilityCatalog, CapabilityDescriptor, get_catalog
from .needs import CapabilityNeed, need_from_id


@dataclass(slots=True, frozen=True)
class CapabilityResolution:
    """Resultado da resolução de um conjunto de needs."""

    available: tuple[CapabilityDescriptor, ...]
    """Capabilities concretas disponíveis e saudáveis."""

    missing: tuple[CapabilityNeed, ...]
    """Needs que não encontraram candidato no catálogo."""

    degraded: tuple[CapabilityDescriptor, ...]
    """Candidatos encontrados mas com alguma limitação."""

    inline_capable: tuple[str, ...]
    """IDs de capabilities que podem rodar inline (fora do pipeline)."""

    @property
    def has_inline(self) -> bool:
        return bool(self.inline_capable)

    @property
    def has_executable(self) -> bool:
        return bool(self.available) or bool(self.degraded)

    @property
    def all_read_only(self) -> bool:
        return all(d.read_only for d in self.available + self.degraded)

    @property
    def requires_network(self) -> bool:
        return any(d.requires_network for d in self.available + self.degraded)

    @property
    def supports_live_lookup(self) -> bool:
        return any(d.supports_live_lookup for d in self.available + self.degraded)

    @property
    def has_orchestration_only(self) -> bool:
        return all(d.internal for d in self.available + self.degraded) and not self.missing


class CapabilityResolver:
    """Resolve necessidades semânticas em capabilities concretas.

    Sem ``if`` por domínio. Usa metadata do catálogo para matching
    genérico por family, intent, freshness, etc.
    """

    def __init__(self, catalog: CapabilityCatalog | None = None) -> None:
        self._catalog = catalog or get_catalog()

    def resolve(self, need: CapabilityNeed) -> list[CapabilityDescriptor]:
        """Retorna candidatos ordenados por adequação para um need."""
        candidates: list[tuple[float, CapabilityDescriptor]] = []

        for desc in self._catalog.list_all():
            if desc.internal:
                continue
            score = self._score(need, desc)
            if score > 0:
                candidates.append((score, desc))

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return [desc for _, desc in candidates]

    def resolve_all(
        self,
        needs: Sequence[CapabilityNeed],
    ) -> CapabilityResolution:
        """Resolve múltiplas needs, retorna available/missing/degraded."""
        available: list[CapabilityDescriptor] = []
        missing: list[CapabilityNeed] = []
        degraded: list[CapabilityDescriptor] = []
        inline_capable: list[str] = []
        seen_ids: set[str] = set()
        seen_inline: set[str] = set()

        for need in needs:
            candidates = self.resolve(need)
            if not candidates:
                missing.append(need)
                continue
            for desc in candidates:
                if desc.capability_id in seen_ids:
                    continue
                seen_ids.add(desc.capability_id)
                available.append(desc)
                if desc.supports_inline and desc.capability_id not in seen_inline:
                    seen_inline.add(desc.capability_id)
                    inline_capable.append(desc.capability_id)

        return CapabilityResolution(
            available=tuple(available),
            missing=tuple(missing),
            degraded=tuple(degraded),
            inline_capable=tuple(inline_capable),
        )

    def resolve_from_ids(
        self,
        capability_ids: Sequence[str],
    ) -> CapabilityResolution:
        """Resolve a partir de IDs legados (backward compat)."""
        needs = [need_from_id(cap_id) for cap_id in capability_ids if cap_id]
        return self.resolve_all(needs)

    def _score(self, need: CapabilityNeed, desc: CapabilityDescriptor) -> float:
        """Score de adequação need↔descriptor. 0 = não-candidato."""
        score = 0.0

        # 1) Preferred capability — match direto = score máximo
        if desc.capability_id in need.preferred_capabilities:
            return 10.0

        # 2) Family match — obrigatório (sem isso, não é candidato)
        if desc.family != need.family:
            return 0.0
        score += 3.0

        # 3) Intent match
        if need.intent in desc.preferred_intents:
            score += 2.0

        # 4) Freshness match
        if need.freshness != "unknown" and desc.freshness != "unknown":
            if need.freshness == "live" and desc.supports_live_lookup:
                score += 2.0
            elif need.freshness == desc.freshness:
                score += 1.0

        # 5) read_only compatibility
        if need.read_only and desc.read_only:
            score += 1.0
        elif need.read_only and not desc.read_only:
            score -= 0.5  # penaliza write capability para need read-only
        elif not need.read_only and desc.read_only:
            score -= 1.5  # need quer write, cap é read-only — forte penalidade

        # 6) network compatibility
        if need.requires_network == desc.requires_network:
            score += 0.5

        # 7) inline preference para single_step
        if need.execution_mode == "single_step" and desc.supports_inline:
            score += 1.0

        # 8) degrades_gracefully — bônus para resiliência
        if desc.degrades_gracefully:
            score += 0.5

        return score


# ── Instância global ─────────────────────────────────────────────────────

_global_resolver: CapabilityResolver | None = None


def get_resolver() -> CapabilityResolver:
    """Retorna instância global do resolvedor."""
    global _global_resolver
    if _global_resolver is None:
        _global_resolver = CapabilityResolver()
    return _global_resolver
