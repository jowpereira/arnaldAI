"""Testes para CapabilityResolver — resolução genérica need→concrete."""

from __future__ import annotations

from arnaldo.capabilities.catalog import CapabilityCatalog, CapabilityDescriptor
from arnaldo.capabilities.needs import CapabilityNeed, need_from_id
from arnaldo.capabilities.resolver import CapabilityResolution, CapabilityResolver


def _make_resolver() -> CapabilityResolver:
    return CapabilityResolver()


class TestResolveSingleNeed:
    """Resolução de um need individual."""

    def test_search_lookup_live_returns_web_search(self) -> None:
        resolver = _make_resolver()
        need = CapabilityNeed(
            family="search",
            intent="lookup",
            freshness="live",
            requires_network=True,
            read_only=True,
        )
        candidates = resolver.resolve(need)
        assert len(candidates) >= 1
        assert candidates[0].capability_id == "search.public_web"

    def test_preferred_capability_wins(self) -> None:
        resolver = _make_resolver()
        need = CapabilityNeed(
            family="search",
            intent="lookup",
            preferred_capabilities=("search.public_web",),
        )
        candidates = resolver.resolve(need)
        assert candidates[0].capability_id == "search.public_web"

    def test_filesystem_lookup_returns_filesystem_search(self) -> None:
        resolver = _make_resolver()
        need = CapabilityNeed(
            family="filesystem",
            intent="lookup",
            freshness="stable",
            read_only=True,
        )
        candidates = resolver.resolve(need)
        assert len(candidates) >= 1
        assert candidates[0].capability_id == "filesystem.local.search"

    def test_shell_execute_returns_local_shell(self) -> None:
        resolver = _make_resolver()
        need = CapabilityNeed(
            family="shell",
            intent="execute",
            read_only=True,
        )
        candidates = resolver.resolve(need)
        assert len(candidates) >= 1
        assert candidates[0].capability_id == "shell.local.readonly"

    def test_connector_returns_http_generic(self) -> None:
        resolver = _make_resolver()
        need = CapabilityNeed(
            family="connector",
            intent="retrieve",
            requires_network=True,
            read_only=False,
        )
        candidates = resolver.resolve(need)
        assert len(candidates) >= 1
        assert candidates[0].capability_id == "connector.http.generic"

    def test_unknown_family_returns_empty(self) -> None:
        resolver = _make_resolver()
        need = CapabilityNeed(family="quantum_computer")
        candidates = resolver.resolve(need)
        assert candidates == []

    def test_internal_capabilities_excluded(self) -> None:
        resolver = _make_resolver()
        need = CapabilityNeed(family="intent", intent="orchestrate")
        candidates = resolver.resolve(need)
        assert candidates == []


class TestResolveAll:
    """Resolução em batch."""

    def test_multiple_needs_resolved(self) -> None:
        resolver = _make_resolver()
        needs = [
            CapabilityNeed(
                family="search",
                intent="lookup",
                freshness="live",
                requires_network=True,
            ),
            CapabilityNeed(
                family="filesystem",
                intent="lookup",
                read_only=True,
            ),
        ]
        resolution = resolver.resolve_all(needs)
        ids = [d.capability_id for d in resolution.available]
        assert "search.public_web" in ids
        assert "filesystem.local.search" in ids
        assert len(resolution.missing) == 0

    def test_unresolvable_need_goes_to_missing(self) -> None:
        resolver = _make_resolver()
        needs = [CapabilityNeed(family="teleportation")]
        resolution = resolver.resolve_all(needs)
        assert len(resolution.missing) == 1
        assert resolution.missing[0].family == "teleportation"
        assert len(resolution.available) == 0

    def test_inline_capable_populated(self) -> None:
        resolver = _make_resolver()
        needs = [
            CapabilityNeed(
                family="search",
                intent="lookup",
                freshness="live",
                requires_network=True,
            ),
        ]
        resolution = resolver.resolve_all(needs)
        assert "search.public_web" in resolution.inline_capable

    def test_deduplication(self) -> None:
        resolver = _make_resolver()
        needs = [
            CapabilityNeed(
                family="search",
                preferred_capabilities=("search.public_web",),
            ),
            CapabilityNeed(
                family="search",
                preferred_capabilities=("search.public_web",),
            ),
        ]
        resolution = resolver.resolve_all(needs)
        ids = [d.capability_id for d in resolution.available]
        assert ids.count("search.public_web") == 1


class TestResolveFromIds:
    """Backward compat: list[str] → CapabilityResolution."""

    def test_resolves_concrete_ids(self) -> None:
        resolver = _make_resolver()
        resolution = resolver.resolve_from_ids(["search.public_web", "shell.local.readonly"])
        ids = [d.capability_id for d in resolution.available]
        assert "search.public_web" in ids
        assert "shell.local.readonly" in ids

    def test_resolves_generic_family(self) -> None:
        resolver = _make_resolver()
        resolution = resolver.resolve_from_ids(["search.*"])
        ids = [d.capability_id for d in resolution.available]
        assert "search.public_web" in ids

    def test_empty_ids(self) -> None:
        resolver = _make_resolver()
        resolution = resolver.resolve_from_ids([])
        assert len(resolution.available) == 0
        assert len(resolution.missing) == 0


class TestCapabilityResolutionProperties:
    """Properties derivadas do CapabilityResolution."""

    def test_has_inline(self) -> None:
        resolution = CapabilityResolution(
            available=(),
            missing=(),
            degraded=(),
            inline_capable=("search.public_web",),
        )
        assert resolution.has_inline is True

    def test_all_read_only(self) -> None:
        resolver = _make_resolver()
        resolution = resolver.resolve_from_ids(["search.public_web", "shell.local.readonly"])
        assert resolution.all_read_only is True

    def test_not_all_read_only_with_connector(self) -> None:
        resolver = _make_resolver()
        resolution = resolver.resolve_from_ids(
            ["search.public_web", "connector.http.generic"],
        )
        assert resolution.all_read_only is False

    def test_requires_network(self) -> None:
        resolver = _make_resolver()
        resolution = resolver.resolve_from_ids(["search.public_web"])
        assert resolution.requires_network is True

    def test_supports_live_lookup(self) -> None:
        resolver = _make_resolver()
        resolution = resolver.resolve_from_ids(["search.public_web"])
        assert resolution.supports_live_lookup is True

    def test_no_live_lookup_for_local(self) -> None:
        resolver = _make_resolver()
        resolution = resolver.resolve_from_ids(["filesystem.local.search"])
        assert resolution.supports_live_lookup is False
