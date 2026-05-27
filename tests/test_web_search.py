from __future__ import annotations

from collections import deque
import urllib.error

from arnaldo.capabilities.web_search import (
    WebSearchCapability,
    _extract_bing_url,
    _parse_bing_rss,
    _parse_bing_results,
)


def test_extract_bing_url_decodes_redirect_target() -> None:
    raw = (
        "https://www.bing.com/ck/a?!&u="
        "a1aHR0cHM6Ly9kb2xhcmhvamUuY29tLw"
    )

    assert _extract_bing_url(raw) == "https://dolarhoje.com/"


def test_parse_bing_results_extracts_title_snippet_and_url() -> None:
    html = """
    <li class="b_algo">
      <h2 class=""><a target="_blank"
      href="https://www.bing.com/ck/a?!&amp;u=a1aHR0cHM6Ly9kb2xhcmhvamUuY29tLw">
      <strong>D&#243;lar Hoje</strong>: Cotacao Comercial</a></h2>
      <div class="b_caption"><p class="b_lineclamp2">
      Cotacao em torno de R$ 5,01 no fechamento recente.
      </p></div>
    </li>
    """

    results = _parse_bing_results(html, 5)

    assert len(results) == 1
    assert results[0]["title"] == "Dólar Hoje: Cotacao Comercial"
    assert results[0]["url"] == "https://dolarhoje.com/"
    assert "R$ 5,01" in results[0]["snippet"]


def test_parse_bing_rss_extracts_title_snippet_and_url() -> None:
    xml_text = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Dólar hoje - Wise</title>
          <link>https://wise.com/br/currency-converter/dolar-hoje</link>
          <description>A taxa de câmbio comercial do dólar hoje é 5,04 reais.</description>
        </item>
      </channel>
    </rss>
    """

    results = _parse_bing_rss(xml_text, 5)

    assert len(results) == 1
    assert results[0]["title"] == "Dólar hoje - Wise"
    assert results[0]["url"] == "https://wise.com/br/currency-converter/dolar-hoje"
    assert "5,04" in results[0]["snippet"]


def test_web_search_capability_uses_bing_when_duckduckgo_times_out(monkeypatch) -> None:
    capability = WebSearchCapability()

    def _timeout(*args, **kwargs):
        raise urllib.error.URLError(TimeoutError("timed out"))

    def _bing(*args, **kwargs):
        return [
            {
                "title": "Dolar Hoje",
                "url": "https://dolarhoje.com/",
                "snippet": "Cotacao em torno de R$ 5,01.",
            }
        ]

    monkeypatch.setattr("arnaldo.capabilities.web_search._search_ddg", _timeout)
    monkeypatch.setattr("arnaldo.capabilities.web_search._search_bing", _bing)

    result = capability.execute({"query": "qual o valor do dolar hoje", "max_results": 5})

    assert result.success is True
    assert result.metadata == {"engine": "bing"}
    assert result.data["results"][0]["url"] == "https://dolarhoje.com/"


def test_web_search_capability_uses_bing_when_duckduckgo_returns_no_results(monkeypatch) -> None:
    capability = WebSearchCapability()

    def _empty(*args, **kwargs):
        return []

    def _bing(*args, **kwargs):
        return [
            {
                "title": "Dolar Hoje",
                "url": "https://dolarhoje.com/",
                "snippet": "Cotacao em torno de R$ 5,01.",
            }
        ]

    monkeypatch.setattr("arnaldo.capabilities.web_search._search_ddg", _empty)
    monkeypatch.setattr("arnaldo.capabilities.web_search._search_bing", _bing)

    result = capability.execute({"query": "qual o valor do dolar hoje", "max_results": 5})

    assert result.success is True
    assert result.metadata == {"engine": "bing"}
    assert result.data["count"] == 1


def test_web_search_capability_retries_same_provider_before_falling_back(monkeypatch) -> None:
    capability = WebSearchCapability()
    attempts = deque(
        [
            [],
            [
                {
                    "title": "Dolar Hoje",
                    "url": "https://dolarhoje.com/",
                    "snippet": "Cotacao em torno de R$ 5,01.",
                }
            ],
        ]
    )

    def _flaky_ddg(*args, **kwargs):
        return attempts.popleft()

    def _bing(*args, **kwargs):
        raise AssertionError("bing nao deveria ser chamado se o retry do provider original resolver")

    monkeypatch.setattr("arnaldo.capabilities.web_search._search_ddg", _flaky_ddg)
    monkeypatch.setattr("arnaldo.capabilities.web_search._search_bing", _bing)

    result = capability.execute({"query": "qual o valor do dolar hoje", "max_results": 5})

    assert result.success is True
    assert result.metadata == {"engine": "duckduckgo"}
    assert result.data["count"] == 1
