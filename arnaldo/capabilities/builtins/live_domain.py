"""Capabilities de domínio live — wrappers sobre WebSearch com queries otimizadas.

Cada classe expõe um capability_id distinto e constrói queries específicas
para maximizar relevância nos resultados da busca web.
"""

from __future__ import annotations

from typing import Any

from arnaldo.capabilities.base import CapabilityResult, make_source, timed_execution
from arnaldo.capabilities.web_search import WebSearchCapability

_web = WebSearchCapability()


class FxRateCapability:
    """Cotação de câmbio via web search."""

    capability_id = "fx.rate"

    def describe(self) -> str:
        return "consultar cotação de câmbio entre moedas"

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        base = str(params.get("base", "USD")).strip().upper()
        target = str(params.get("target", "BRL")).strip().upper()
        query = f"cotação {base} {target} hoje câmbio"
        result = _web.execute({"query": query, "max_results": 3})
        return CapabilityResult(
            success=result.success,
            data=result.data,
            source=make_source(f"fx.rate:{base}/{target}"),
            error=result.error,
            metadata={"base": base, "target": target, "delegated_to": "search.public_web"},
        )


class WeatherCurrentCapability:
    """Clima atual via web search."""

    capability_id = "weather.current"

    def describe(self) -> str:
        return "consultar clima atual de uma localidade"

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        location = str(params.get("location", "")).strip()
        if not location:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("weather.current"),
                error="Parâmetro 'location' é obrigatório",
            )
        query = f"clima tempo agora {location}"
        result = _web.execute({"query": query, "max_results": 3})
        return CapabilityResult(
            success=result.success,
            data=result.data,
            source=make_source(f"weather.current:{location}"),
            error=result.error,
            metadata={"location": location, "delegated_to": "search.public_web"},
        )


class NewsLatestCapability:
    """Notícias recentes via web search."""

    capability_id = "news.latest"

    def describe(self) -> str:
        return "buscar notícias recentes sobre um tema"

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        topic = str(params.get("topic", "")).strip()
        if not topic:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("news.latest"),
                error="Parâmetro 'topic' é obrigatório",
            )
        query = f"{topic} notícias hoje"
        result = _web.execute({"query": query, "max_results": 5})
        return CapabilityResult(
            success=result.success,
            data=result.data,
            source=make_source(f"news.latest:{topic}"),
            error=result.error,
            metadata={"topic": topic, "delegated_to": "search.public_web"},
        )


class FinanceQuoteCapability:
    """Cotação financeira (ações, cripto) via web search."""

    capability_id = "finance.quote"

    def describe(self) -> str:
        return "consultar cotação de ação, ETF ou criptomoeda"

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        symbol = str(params.get("symbol", "")).strip().upper()
        if not symbol:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("finance.quote"),
                error="Parâmetro 'symbol' é obrigatório",
            )
        query = f"cotação {symbol} preço hoje"
        result = _web.execute({"query": query, "max_results": 3})
        return CapabilityResult(
            success=result.success,
            data=result.data,
            source=make_source(f"finance.quote:{symbol}"),
            error=result.error,
            metadata={"symbol": symbol, "delegated_to": "search.public_web"},
        )
