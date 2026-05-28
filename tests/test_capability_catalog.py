"""Testes para CapabilityCatalog — fonte única de verdade."""

from __future__ import annotations

from arnaldo.capabilities.catalog import (
    CapabilityCatalog,
    CapabilityDescriptor,
    get_catalog,
)


class TestCapabilityDescriptor:
    """Construção e frozen check."""

    def test_executable_descriptor(self) -> None:
        desc = CapabilityDescriptor(
            capability_id="test.cap",
            family="test",
            fqn="arnaldo.capabilities.test.TestCapability",
            name="Test",
            description="test capability",
        )
        assert desc.capability_id == "test.cap"
        assert desc.fqn == "arnaldo.capabilities.test.TestCapability"
        assert desc.internal is False

    def test_internal_descriptor(self) -> None:
        desc = CapabilityDescriptor(
            capability_id="intent.structure",
            family="intent",
            fqn="",
            name="Structure Intent",
            description="test",
            internal=True,
        )
        assert desc.internal is True
        assert desc.fqn == ""


class TestCapabilityCatalog:
    """Registry unificado."""

    def test_builtins_registered(self) -> None:
        catalog = CapabilityCatalog()
        assert catalog.get("search.public_web") is not None
        assert catalog.get("connector.http.generic") is not None
        assert catalog.get("filesystem.local.search") is not None
        assert catalog.get("shell.local.readonly") is not None

    def test_internal_capabilities_registered(self) -> None:
        catalog = CapabilityCatalog()
        assert catalog.get("intent.structure") is not None
        assert catalog.get("work.decompose") is not None
        assert catalog.get("artifact.draft") is not None

    def test_can_execute_real_capabilities(self) -> None:
        catalog = CapabilityCatalog()
        assert catalog.can_execute("search.public_web") is True
        assert catalog.can_execute("shell.local.readonly") is True

    def test_cannot_execute_internal(self) -> None:
        catalog = CapabilityCatalog()
        assert catalog.can_execute("intent.structure") is False
        assert catalog.can_execute("work.decompose") is False

    def test_cannot_execute_unknown(self) -> None:
        catalog = CapabilityCatalog()
        assert catalog.can_execute("nonexistent.cap") is False

    def test_list_by_family(self) -> None:
        catalog = CapabilityCatalog()
        search_caps = catalog.list_by_family("search")
        assert len(search_caps) >= 1
        assert all(d.family == "search" for d in search_caps)

    def test_supports_inline(self) -> None:
        catalog = CapabilityCatalog()
        assert catalog.supports_inline("search.public_web") is True
        assert catalog.supports_inline("connector.http.generic") is False

    def test_register_custom(self) -> None:
        catalog = CapabilityCatalog()
        custom = CapabilityDescriptor(
            capability_id="custom.test",
            family="custom",
            fqn="some.module.CustomCapability",
            name="Custom",
            description="custom capability",
        )
        catalog.register(custom)
        assert catalog.get("custom.test") is custom
        assert catalog.can_execute("custom.test") is True

    def test_executable_ids(self) -> None:
        catalog = CapabilityCatalog()
        ids = catalog.executable_ids()
        assert "search.public_web" in ids
        assert "intent.structure" not in ids

    def test_fqn_map(self) -> None:
        catalog = CapabilityCatalog()
        fqn_map = catalog.fqn_map()
        assert "search.public_web" in fqn_map
        assert fqn_map["search.public_web"] == "arnaldo.capabilities.web_search.WebSearchCapability"
        assert "intent.structure" not in fqn_map


class TestGetCatalog:
    """Singleton global."""

    def test_returns_same_instance(self) -> None:
        c1 = get_catalog()
        c2 = get_catalog()
        assert c1 is c2

    def test_has_builtins(self) -> None:
        catalog = get_catalog()
        assert catalog.get("search.public_web") is not None


class TestNewBuiltinCapabilities:
    """Capabilities de domínio adicionadas na Fase 6."""

    def test_time_current_registered(self) -> None:
        catalog = CapabilityCatalog()
        desc = catalog.get("time.current")
        assert desc is not None
        assert desc.requires_network is False
        assert desc.supports_live_lookup is True
        assert desc.supports_inline is True

    def test_http_readonly_fetch_json_registered(self) -> None:
        catalog = CapabilityCatalog()
        desc = catalog.get("http.readonly.fetch_json")
        assert desc is not None
        assert desc.read_only is True
        assert desc.supports_live_lookup is True

    def test_fx_rate_registered(self) -> None:
        catalog = CapabilityCatalog()
        desc = catalog.get("fx.rate")
        assert desc is not None
        assert desc.family == "search"
        assert desc.supports_live_lookup is True

    def test_weather_current_registered(self) -> None:
        catalog = CapabilityCatalog()
        desc = catalog.get("weather.current")
        assert desc is not None

    def test_news_latest_registered(self) -> None:
        catalog = CapabilityCatalog()
        desc = catalog.get("news.latest")
        assert desc is not None

    def test_finance_quote_registered(self) -> None:
        catalog = CapabilityCatalog()
        desc = catalog.get("finance.quote")
        assert desc is not None

    def test_all_new_caps_are_executable(self) -> None:
        catalog = CapabilityCatalog()
        new_ids = [
            "time.current",
            "http.readonly.fetch_json",
            "fx.rate",
            "weather.current",
            "news.latest",
            "finance.quote",
        ]
        for cap_id in new_ids:
            assert catalog.can_execute(cap_id), f"{cap_id} deveria ser executável"

    def test_all_new_caps_support_inline(self) -> None:
        catalog = CapabilityCatalog()
        new_ids = [
            "time.current",
            "http.readonly.fetch_json",
            "fx.rate",
            "weather.current",
            "news.latest",
            "finance.quote",
        ]
        for cap_id in new_ids:
            assert catalog.supports_inline(cap_id), f"{cap_id} deveria suportar inline"


class TestCatalogSyncWithSemantics:
    """Verifica que o catálogo é consultado pela camada semântica."""

    def test_describe_uses_catalog(self) -> None:
        from arnaldo.capabilities.semantics import describe_capability_id

        traits = describe_capability_id("search.public_web")
        assert traits.family == "search"
        assert traits.locality == "remote"
        assert traits.inline_lookup_executor_id == "search.public_web"

    def test_describe_uses_catalog_for_shell(self) -> None:
        from arnaldo.capabilities.semantics import describe_capability_id

        traits = describe_capability_id("shell.local.readonly")
        assert traits.family == "shell"
        assert traits.locality == "local"
        assert traits.inline_lookup_executor_id == "shell.local.readonly"


class TestCatalogSyncWithExecutor:
    """Verifica que o executor usa o catálogo."""

    def test_executor_can_execute_from_catalog(self) -> None:
        from arnaldo.capabilities.registry import CapabilityExecutor

        executor = CapabilityExecutor()
        assert executor.can_execute("search.public_web") is True
        assert executor.can_execute("nonexistent.cap") is False
        assert executor.can_execute("intent.structure") is False
