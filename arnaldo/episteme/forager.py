"""Web Forager — busca externa governada."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from arnaldo.capabilities.web_search import WebSearchCapability

from .signals import CuriositySignal

logger = logging.getLogger("arnaldo.episteme")


@dataclass(frozen=True, slots=True)
class ForagerPolicy:
    """Governança de foraging web — domains permitidos, rate limits."""

    allowed_domains: frozenset[str] = frozenset()
    blocked_domains: frozenset[str] = frozenset(
        {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"}
    )
    preferred_domains: frozenset[str] = frozenset({"learn.microsoft.com", "devblogs.microsoft.com"})
    tech_query_prefix: str = "site:learn.microsoft.com OR site:devblogs.microsoft.com"
    max_tokens_per_run: int = 50_000
    max_pages_per_signal: int = 3
    rate_limit: int = 5


DEFAULT_POLICY = ForagerPolicy()


class WebForager:
    """Executa buscas web governadas por policy."""

    _requests_this_run: int = 0
    _tokens_this_run: int = 0

    def __init__(self, *, policy: ForagerPolicy | None = None) -> None:
        self.policy = policy or DEFAULT_POLICY
        self._search = WebSearchCapability()

    def _estimate_tokens(self, results: list[dict[str, Any]]) -> int:
        return sum(len(str(r.get("snippet", ""))) // 4 for r in results)

    def _rewrite_query(self, signal: CuriositySignal) -> str:
        """Reescreve query para priorizar fontes preferidas quando contexto é técnico."""
        query = signal.query
        tech_indicators = {
            "api",
            "sdk",
            "azure",
            "microsoft",
            "dotnet",
            ".net",
            "python",
            "typescript",
            "react",
            "docker",
            "kubernetes",
            "openai",
            "cognitive",
            "service",
            "endpoint",
            "deploy",
        }
        words = set(query.lower().split())
        hints = set(h.lower() for h in signal.search_hints)
        is_tech = bool((words | hints) & tech_indicators)
        if is_tech and self.policy.preferred_domains:
            return f"{self.policy.tech_query_prefix} {query}"
        return query

    def _sort_by_preference(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ordena resultados priorizando preferred_domains."""
        if not self.policy.preferred_domains:
            return items
        preferred: list[dict[str, Any]] = []
        others: list[dict[str, Any]] = []
        for item in items:
            try:
                host = urlparse(item.get("url", "")).hostname or ""
                if any(host.endswith(d) for d in self.policy.preferred_domains):
                    preferred.append(item)
                else:
                    others.append(item)
            except Exception:
                others.append(item)
        return preferred + others

    def forage(self, signal: CuriositySignal) -> list[dict[str, Any]]:
        """Executa busca web para um sinal de curiosidade."""
        if WebForager._requests_this_run >= self.policy.rate_limit:
            logger.warning(
                "Rate limit atingido (%d/%d)",
                self._requests_this_run,
                self.policy.rate_limit,
            )
            return []
        if WebForager._tokens_this_run >= self.policy.max_tokens_per_run:
            logger.warning("Token limit atingido (%d)", self._tokens_this_run)
            return []

        rewritten = self._rewrite_query(signal)
        result = self._search.execute(
            {"query": rewritten, "max_results": self.policy.max_pages_per_signal}
        )
        WebForager._requests_this_run += 1

        if not result.success:
            logger.warning("Busca falhou: %s", result.error)
            return []

        items: list[dict[str, Any]] = (result.data or {}).get("results", [])
        if self.policy.blocked_domains:
            items = [r for r in items if not self._is_blocked(r.get("url", ""))]
        if self.policy.allowed_domains:
            items = [r for r in items if self._is_allowed(r.get("url", ""))]
        items = self._sort_by_preference(items)

        WebForager._tokens_this_run += self._estimate_tokens(items)
        return items

    def _is_blocked(self, url: str) -> bool:
        try:
            host = urlparse(url).hostname or ""
            return host in self.policy.blocked_domains
        except Exception:
            return True

    def _is_allowed(self, url: str) -> bool:
        if not self.policy.allowed_domains:
            return True
        try:
            host = urlparse(url).hostname or ""
            return any(host.endswith(d) for d in self.policy.allowed_domains)
        except Exception:
            return False

    @classmethod
    def reset_counter(cls) -> None:
        """Reseta contadores por run."""
        cls._requests_this_run = 0
        cls._tokens_this_run = 0
