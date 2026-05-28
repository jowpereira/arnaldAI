"""Capability search.public_web — busca web real via DuckDuckGo HTML."""

from __future__ import annotations

import base64
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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
            engine, results = _search_web(query, max_results=max_results)
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
                metadata={"engine": engine},
            )

        return CapabilityResult(
            success=True,
            data={
                "query": query,
                "results": results,
                "count": len(results),
            },
            source=make_source(f"search.public_web:{query}"),
            metadata={"engine": engine},
        )


def _search_web(query: str, *, max_results: int = 5) -> tuple[str, list[dict[str, str]]]:
    last_error: Exception | None = None
    last_engine = "duckduckgo"
    providers: tuple[tuple[str, Any], ...] = (
        ("duckduckgo", _search_ddg),
        ("bing", _search_bing),
    )
    for engine, search_fn in providers:
        last_engine = engine
        for attempt in range(2):
            try:
                results = search_fn(query, max_results=max_results)
                if results:
                    return engine, results
                logger.warning(
                    "web search provider %s retornou 0 resultados na tentativa %d",
                    engine,
                    attempt + 1,
                )
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "web search provider %s falhou na tentativa %d: %s",
                    engine,
                    attempt + 1,
                    exc,
                )
    if last_error is None:
        return last_engine, []
    raise OSError(f"todos os providers de busca falharam: {last_error}")


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


def _search_bing(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Faz busca web via Bing RSS/HTML como alternativa."""
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        content = resp.read().decode("utf-8", errors="replace")
    results = _parse_bing_rss(content, max_results)
    if results:
        return results
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    return _parse_bing_results(html, max_results)


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

        if clean_title and clean_url and not _is_search_ad_url(clean_url):
            results.append(
                {
                    "title": clean_title,
                    "url": clean_url,
                    "snippet": snippet,
                }
            )

    return results


def _parse_bing_results(html: str, max_results: int) -> list[dict[str, str]]:
    """Extrai resultados do HTML do Bing."""
    results: list[dict[str, str]] = []
    block_pattern = re.compile(
        r'<li class="b_algo"[^>]*>(.*?)</li>',
        re.DOTALL,
    )
    link_pattern = re.compile(
        r"<h2[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>\s*</h2>",
        re.DOTALL,
    )
    snippet_pattern = re.compile(
        r"<p[^>]*>(.*?)</p>",
        re.DOTALL,
    )
    for block in block_pattern.findall(html):
        match = link_pattern.search(block)
        if not match:
            continue
        raw_url, title = match.groups()
        snippet_match = snippet_pattern.search(block)
        snippet = snippet_match.group(1) if snippet_match else ""
        clean_title = _strip_html(unescape(title)).strip()
        clean_url = _extract_bing_url(raw_url)
        clean_snippet = _strip_html(unescape(snippet)).strip()
        if clean_title and clean_url and not _is_search_ad_url(clean_url):
            results.append(
                {
                    "title": clean_title,
                    "url": clean_url,
                    "snippet": clean_snippet,
                }
            )
        if len(results) >= max_results:
            break
    return results


def _parse_bing_rss(xml_text: str, max_results: int) -> list[dict[str, str]]:
    """Extrai resultados do feed RSS do Bing."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    results: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = _strip_html(unescape(item.findtext("title", ""))).strip()
        url = str(item.findtext("link", "") or "").strip()
        snippet = _strip_html(unescape(item.findtext("description", ""))).strip()
        if title and url and not _is_search_ad_url(url):
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                }
            )
        if len(results) >= max_results:
            break
    return results


def _extract_ddg_url(raw_url: str) -> str:
    """Extrai URL real do redirect do DuckDuckGo."""
    if "uddg=" in raw_url:
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
        urls = parsed.get("uddg", [])
        if urls:
            return urls[0]
    return raw_url


def _extract_bing_url(raw_url: str) -> str:
    """Extrai URL real do redirect do Bing quando possível."""
    normalized_url = unescape(str(raw_url or "").strip())
    parsed = urllib.parse.urlparse(normalized_url)
    query = urllib.parse.parse_qs(parsed.query)
    values = query.get("u", [])
    if values:
        decoded = _decode_bing_target(values[0])
        if decoded:
            return decoded
    return normalized_url


def _decode_bing_target(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("a1"):
        normalized = normalized[2:]
    try:
        padding = "=" * (-len(normalized) % 4)
        decoded = base64.b64decode(normalized + padding).decode("utf-8").strip()
    except Exception:
        return ""
    if decoded.startswith(("http://", "https://")):
        return decoded
    return ""


def _is_search_ad_url(url: str) -> bool:
    normalized = str(url or "").strip().lower()
    if not normalized:
        return False
    return "duckduckgo.com/y.js?ad_domain=" in normalized


def _strip_html(text: str) -> str:
    """Remove tags HTML de um texto."""
    return re.sub(r"<[^>]+>", "", text)
