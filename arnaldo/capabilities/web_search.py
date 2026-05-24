"""Capability search.public_web — busca web real via DuckDuckGo HTML."""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Any

from .base import CapabilityResult, make_source, timed_execution

logger = logging.getLogger("arnaldo.capabilities")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_DDG_URL = "https://html.duckduckgo.com/html/"
_TIMEOUT = 10


class WebSearchCapability:
    """Busca web via DuckDuckGo HTML — stdlib only, sem API key."""

    capability_id = "search.public_web"

    def describe(self) -> str:
        return (
            "Buscar informação atual na web — cotações, preços, câmbio, "
            "notícias, clima, dados em tempo real"
        )

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        """Executa busca web e retorna resultados estruturados."""
        query = str(params.get("query", "")).strip()
        if not query:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("search.public_web"),
                error="Parâmetro 'query' é obrigatório",
            )

        max_results = min(int(params.get("max_results", 5)), 10)

        try:
            results = _search_ddg(query, max_results=max_results)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("web search falhou: %s", exc)
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"search.public_web:{query}"),
                error=f"Busca falhou: {exc}",
            )

        if not results:
            return CapabilityResult(
                success=True,
                data={"query": query, "results": [], "count": 0},
                source=make_source(f"search.public_web:{query}"),
                metadata={"engine": "duckduckgo"},
            )

        return CapabilityResult(
            success=True,
            data={
                "query": query,
                "results": results,
                "count": len(results),
            },
            source=make_source(f"search.public_web:{query}"),
            metadata={"engine": "duckduckgo"},
        )


def _search_ddg(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Faz scraping do DuckDuckGo HTML — sem API key, stdlib only."""
    data = urllib.parse.urlencode({"q": query, "kl": "br-pt"}).encode()
    req = urllib.request.Request(
        _DDG_URL,
        data=data,
        headers={"User-Agent": _USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    return _parse_results(html, max_results)


def _parse_results(html: str, max_results: int) -> list[dict[str, str]]:
    """Extrai resultados do HTML do DuckDuckGo."""
    results: list[dict[str, str]] = []
    # Pattern para links de resultado
    link_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]*)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title) in enumerate(links[:max_results]):
        clean_title = _strip_html(unescape(title)).strip()
        clean_url = _extract_ddg_url(url)
        snippet = _strip_html(unescape(snippets[i])).strip() if i < len(snippets) else ""

        if clean_title and clean_url:
            results.append(
                {
                    "title": clean_title,
                    "url": clean_url,
                    "snippet": snippet,
                }
            )

    return results


def _extract_ddg_url(raw_url: str) -> str:
    """Extrai URL real do redirect do DuckDuckGo."""
    if "uddg=" in raw_url:
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
        urls = parsed.get("uddg", [])
        if urls:
            return urls[0]
    return raw_url


def _strip_html(text: str) -> str:
    """Remove tags HTML de um texto."""
    return re.sub(r"<[^>]+>", "", text)
