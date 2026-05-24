"""Tests for WebForager governance, KnowledgeIngester."""

from __future__ import annotations

from arnaldo.capabilities.base import CapabilityResult
from arnaldo.episteme.forager import ForagerPolicy, WebForager
from arnaldo.episteme.ingester import KnowledgeIngester
from arnaldo.episteme.signals import CuriositySignal, GapType
from arnaldo.graph import CognitiveGraph
from arnaldo.graph.provenance import SourceRecord


_BOOT = SourceRecord.from_bootstrap("test")


# ── ForagerPolicy ────────────────────────────────────────────────────


class TestForagerPolicy:
    def test_default_policy_blocks_localhost(self) -> None:
        policy = ForagerPolicy()
        assert "localhost" in policy.blocked_domains
        assert "127.0.0.1" in policy.blocked_domains
        assert "169.254.169.254" in policy.blocked_domains

    def test_custom_allowed_domains(self) -> None:
        policy = ForagerPolicy(allowed_domains=frozenset({"example.com"}))
        assert "example.com" in policy.allowed_domains

    def test_default_empty_allowed(self) -> None:
        policy = ForagerPolicy()
        assert len(policy.allowed_domains) == 0


# ── WebForager ───────────────────────────────────────────────────────


class TestWebForager:
    def setup_method(self) -> None:
        WebForager.reset_counter()

    def test_forage_with_mock(self, monkeypatch: object) -> None:
        fake_result = CapabilityResult(
            success=True,
            data={"results": [{"title": "Test", "snippet": "Desc", "url": "http://a.com"}]},
            source=_BOOT,
        )
        forager = WebForager()
        monkeypatch.setattr(forager._search, "execute", lambda _: fake_result)  # type: ignore[attr-defined]

        signal = CuriositySignal(query="test", gap_type=GapType.GENUINE, confidence=0.0)
        results = forager.forage(signal)
        assert len(results) == 1
        assert results[0]["title"] == "Test"

    def test_rate_limit_blocks(self) -> None:
        policy = ForagerPolicy(rate_limit=0)
        forager = WebForager(policy=policy)
        signal = CuriositySignal(query="test", gap_type=GapType.GENUINE, confidence=0.0)
        results = forager.forage(signal)
        assert results == []

    def test_blocked_domain_filtered(self, monkeypatch: object) -> None:
        fake = CapabilityResult(
            success=True,
            data={
                "results": [
                    {"title": "A", "snippet": "S", "url": "http://localhost/evil"},
                    {"title": "B", "snippet": "S", "url": "http://example.com/ok"},
                ]
            },
            source=_BOOT,
        )
        forager = WebForager()
        monkeypatch.setattr(forager._search, "execute", lambda _: fake)  # type: ignore[attr-defined]
        signal = CuriositySignal(query="test", gap_type=GapType.GENUINE, confidence=0.0)
        results = forager.forage(signal)
        assert len(results) == 1
        assert "example.com" in results[0]["url"]

    def test_token_limit_blocks(self) -> None:
        WebForager._tokens_this_run = 50_001
        forager = WebForager()
        signal = CuriositySignal(query="test", gap_type=GapType.GENUINE, confidence=0.0)
        results = forager.forage(signal)
        assert results == []

    def test_allowed_domain_filter(self, monkeypatch: object) -> None:
        fake = CapabilityResult(
            success=True,
            data={
                "results": [
                    {"title": "A", "snippet": "S", "url": "http://allowed.com/ok"},
                    {"title": "B", "snippet": "S", "url": "http://blocked.com/no"},
                ]
            },
            source=_BOOT,
        )
        policy = ForagerPolicy(allowed_domains=frozenset({"allowed.com"}))
        forager = WebForager(policy=policy)
        monkeypatch.setattr(forager._search, "execute", lambda _: fake)  # type: ignore[attr-defined]
        signal = CuriositySignal(query="test", gap_type=GapType.GENUINE, confidence=0.0)
        results = forager.forage(signal)
        assert len(results) == 1
        assert "allowed.com" in results[0]["url"]


# ── KnowledgeIngester ────────────────────────────────────────────────


class TestKnowledgeIngester:
    def test_ingest_creates_nodes(self) -> None:
        graph = CognitiveGraph()
        ingester = KnowledgeIngester()
        results = [
            {"title": "Page A", "snippet": "Content A", "url": "http://a.com"},
            {"title": "Page B", "snippet": "Content B", "url": "http://b.com"},
        ]
        created = ingester.ingest_search_results(graph, results, query="test")
        assert len(created) == 2
        for nid in created:
            assert graph.has_node(nid)

    def test_ingest_skips_empty_title(self) -> None:
        graph = CognitiveGraph()
        ingester = KnowledgeIngester()
        results = [
            {"title": "", "snippet": "Content", "url": "http://a.com"},
        ]
        created = ingester.ingest_search_results(graph, results, query="test")
        assert len(created) == 0

    def test_ingest_deduplicates_by_url(self) -> None:
        graph = CognitiveGraph()
        ingester = KnowledgeIngester()
        results = [
            {"title": "P", "snippet": "C", "url": "http://same.com"},
        ]
        ingester.ingest_search_results(graph, results, query="test")
        created = ingester.ingest_search_results(graph, results, query="test")
        assert len(created) == 0

    def test_ingest_creates_semantic_edges(self) -> None:
        graph = CognitiveGraph()
        ingester = KnowledgeIngester()
        results = [
            {"title": "A", "snippet": "CA", "url": "http://a.com"},
            {"title": "B", "snippet": "CB", "url": "http://b.com"},
        ]
        created = ingester.ingest_search_results(graph, results, query="test")
        assert len(created) == 2
        from arnaldo.graph.edges import EdgeKind

        edges = list(graph.iter_edges_from(created[0], kinds=[EdgeKind.SEMANTIC]))
        assert any(e.target_id == created[1] for e in edges)
