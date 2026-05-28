"""Testes para CapabilityNeed — modelagem tipada de necessidades."""

from __future__ import annotations

from arnaldo.capabilities.needs import (
    CapabilityNeed,
    need_from_id,
    need_to_dict,
    needs_from_ids,
)


class TestCapabilityNeedCreation:
    """Construção e frozen check."""

    def test_default_values(self) -> None:
        need = CapabilityNeed(family="search")
        assert need.family == "search"
        assert need.intent == "lookup"
        assert need.freshness == "unknown"
        assert need.read_only is True
        assert need.required is True
        assert need.preferred_capabilities == ()
        assert need.constraints == {}

    def test_frozen(self) -> None:
        need = CapabilityNeed(family="search")
        try:
            need.family = "connector"  # type: ignore[misc]
            assert False, "deveria ser frozen"
        except AttributeError:
            pass


class TestNeedFromId:
    """Factory backward-compat: capability_id → CapabilityNeed."""

    def test_search_public_web(self) -> None:
        need = need_from_id("search.public_web")
        assert need.family == "search"
        assert need.intent == "lookup"
        assert need.freshness == "live"
        assert need.requires_network is True
        assert need.read_only is True
        assert "search.public_web" in need.preferred_capabilities

    def test_connector_http_generic(self) -> None:
        need = need_from_id("connector.http.generic")
        assert need.family == "connector"
        assert need.requires_network is True
        assert need.read_only is False
        assert need.side_effects == "remote"
        assert "connector.http.generic" in need.preferred_capabilities

    def test_filesystem_local(self) -> None:
        need = need_from_id("filesystem.local.search")
        assert need.family == "filesystem"
        assert need.requires_network is False
        assert need.read_only is True
        assert "filesystem.local.search" in need.preferred_capabilities

    def test_shell_local(self) -> None:
        need = need_from_id("shell.local.readonly")
        assert need.family == "shell"
        assert need.read_only is True
        assert "shell.local.readonly" in need.preferred_capabilities

    def test_generic_family_search_wildcard(self) -> None:
        need = need_from_id("search.*")
        assert need.family == "search"
        assert need.freshness == "live"
        assert "search.public_web" in need.preferred_capabilities

    def test_unknown_family(self) -> None:
        need = need_from_id("exotic.capability.unknown")
        assert need.family == "exotic"
        assert need.intent == "lookup"

    def test_empty_id(self) -> None:
        need = need_from_id("")
        assert need.family == "unknown"

    def test_reason_propagated(self) -> None:
        need = need_from_id("search.public_web", reason="precisa cotação")
        assert need.reason == "precisa cotação"


class TestNeedToDict:
    """Serialização para backward compat com IR."""

    def test_roundtrip_has_id(self) -> None:
        need = need_from_id("search.public_web")
        payload = need_to_dict(need)
        assert payload["id"] == "search.public_web"
        assert payload["family"] == "search"
        assert payload["read_only"] is True
        assert payload["requires_network"] is True

    def test_family_only_need(self) -> None:
        need = CapabilityNeed(family="tool")
        payload = need_to_dict(need)
        assert payload["id"] == "tool"

    def test_reason_included(self) -> None:
        need = need_from_id("search.public_web", reason="cotação")
        payload = need_to_dict(need)
        assert payload["reason"] == "cotação"


class TestNeedsFromIds:
    """Conversão em batch: list[str] → list[CapabilityNeed]."""

    def test_multiple_ids(self) -> None:
        needs = needs_from_ids(["search.public_web", "filesystem.local.search"])
        assert len(needs) == 2
        assert needs[0].family == "search"
        assert needs[1].family == "filesystem"

    def test_deduplication(self) -> None:
        needs = needs_from_ids(["search.public_web", "search.public_web"])
        assert len(needs) == 1

    def test_empty_and_whitespace_filtered(self) -> None:
        needs = needs_from_ids(["", "  ", "search.public_web"])
        assert len(needs) == 1
        assert needs[0].family == "search"
