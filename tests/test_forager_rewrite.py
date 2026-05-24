"""Testes para query rewriting e sort by preference no forager."""

from __future__ import annotations

from unittest.mock import patch

from arnaldo.capabilities.base import CapabilityResult
from arnaldo.episteme.forager import ForagerPolicy, WebForager
from arnaldo.episteme.signals import CuriositySignal, GapType
from arnaldo.graph.provenance import SourceRecord


_BOOT = SourceRecord.from_bootstrap("test")


class TestRewriteQueryTechContext:
    def test_azure_keyword_adds_prefix(self) -> None:
        forager = WebForager()
        signal = CuriositySignal(
            query="azure functions cold start",
            gap_type=GapType.GENUINE,
            confidence=0.3,
            source_request="como reduzir cold start",
        )
        result = forager._rewrite_query(signal)
        assert "site:learn.microsoft.com" in result
        assert "site:devblogs.microsoft.com" in result
        assert "azure functions cold start" in result

    def test_python_keyword_adds_prefix(self) -> None:
        forager = WebForager()
        signal = CuriositySignal(
            query="python asyncio patterns",
            gap_type=GapType.GENUINE,
            confidence=0.3,
            source_request="patterns",
        )
        result = forager._rewrite_query(signal)
        assert "site:learn.microsoft.com" in result


class TestRewriteQueryNonTech:
    def test_non_tech_query_no_prefix(self) -> None:
        forager = WebForager()
        signal = CuriositySignal(
            query="receita de bolo de chocolate",
            gap_type=GapType.GENUINE,
            confidence=0.3,
            source_request="bolo",
        )
        result = forager._rewrite_query(signal)
        assert "site:learn.microsoft.com" not in result
        assert result == "receita de bolo de chocolate"


class TestRewriteQueryUsesHints:
    def test_hints_with_api_triggers_prefix(self) -> None:
        forager = WebForager()
        signal = CuriositySignal(
            query="como configurar autenticação",
            gap_type=GapType.GENUINE,
            confidence=0.3,
            source_request="auth",
            search_hints=("api", "rest"),
        )
        result = forager._rewrite_query(signal)
        assert "site:learn.microsoft.com" in result

    def test_hints_without_tech_no_prefix(self) -> None:
        forager = WebForager()
        signal = CuriositySignal(
            query="como configurar",
            gap_type=GapType.GENUINE,
            confidence=0.3,
            source_request="config",
            search_hints=("receita", "culinária"),
        )
        result = forager._rewrite_query(signal)
        assert "site:learn.microsoft.com" not in result


class TestSortByPreference:
    def test_learn_microsoft_comes_first(self) -> None:
        forager = WebForager()
        items = [
            {"url": "https://stackoverflow.com/q/123", "snippet": "a"},
            {"url": "https://learn.microsoft.com/azure/functions", "snippet": "b"},
            {"url": "https://devblogs.microsoft.com/article", "snippet": "c"},
            {"url": "https://github.com/repo", "snippet": "d"},
        ]
        sorted_items = forager._sort_by_preference(items)
        assert sorted_items[0]["url"] == "https://learn.microsoft.com/azure/functions"
        assert sorted_items[1]["url"] == "https://devblogs.microsoft.com/article"
        # Os demais ficam depois
        assert sorted_items[2]["url"] == "https://stackoverflow.com/q/123"

    def test_no_preferred_domains_returns_original(self) -> None:
        policy = ForagerPolicy(preferred_domains=frozenset())
        forager = WebForager(policy=policy)
        items = [{"url": "https://x.com", "snippet": "x"}]
        assert forager._sort_by_preference(items) == items

    def test_handles_malformed_urls(self) -> None:
        forager = WebForager()
        items = [
            {"url": "not a url", "snippet": "bad"},
            {"url": "https://learn.microsoft.com/docs", "snippet": "good"},
        ]
        sorted_items = forager._sort_by_preference(items)
        assert sorted_items[0]["url"] == "https://learn.microsoft.com/docs"


class TestForageUsesRewrittenQuery:
    def setup_method(self) -> None:
        WebForager.reset_counter()

    def test_forage_passes_rewritten_query(self) -> None:
        captured_params: list[dict] = []

        def fake_execute(self_cap: object, params: dict) -> CapabilityResult:
            captured_params.append(params)
            return CapabilityResult(
                success=True,
                data={
                    "results": [
                        {"title": "T", "snippet": "S", "url": "https://learn.microsoft.com/x"}
                    ]
                },
                source=_BOOT,
            )

        with patch(
            "arnaldo.episteme.forager.WebSearchCapability.execute",
            fake_execute,
        ):
            forager = WebForager()
            signal = CuriositySignal(
                query="azure cognitive services",
                gap_type=GapType.GENUINE,
                confidence=0.3,
                source_request="cognitive",
            )
            results = forager.forage(signal)

        assert len(captured_params) == 1
        assert "site:learn.microsoft.com" in captured_params[0]["query"]
        assert "azure cognitive services" in captured_params[0]["query"]
        assert len(results) == 1
