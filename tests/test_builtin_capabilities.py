"""Testes para capabilities builtin de domínio — Fase 6."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from arnaldo.capabilities.builtins.time_current import TimeCurrentCapability
from arnaldo.capabilities.builtins.http_json import HttpJsonCapability
from arnaldo.capabilities.builtins.live_domain import (
    FxRateCapability,
    FinanceQuoteCapability,
    NewsLatestCapability,
    WeatherCurrentCapability,
)

_HAS_TZDATA = True
try:
    from zoneinfo import ZoneInfo

    ZoneInfo("America/Sao_Paulo")
except Exception:
    _HAS_TZDATA = False


class TestTimeCurrentCapability:
    """time.current — stdlib only, sem rede."""

    def test_capability_id(self) -> None:
        cap = TimeCurrentCapability()
        assert cap.capability_id == "time.current"

    def test_execute_default_utc(self) -> None:
        cap = TimeCurrentCapability()
        result = cap.execute({})
        assert result.success is True
        assert result.data["timezone"] == "UTC"
        assert "datetime_iso" in result.data

    @pytest.mark.skipif(not _HAS_TZDATA, reason="tzdata não instalado")
    def test_execute_with_timezone(self) -> None:
        cap = TimeCurrentCapability()
        result = cap.execute({"timezone": "America/Sao_Paulo"})
        assert result.success is True
        assert result.data["timezone"] == "America/Sao_Paulo"
        assert "-03:00" in result.data["datetime_iso"] or "-02:00" in result.data["datetime_iso"]

    def test_execute_invalid_timezone(self) -> None:
        cap = TimeCurrentCapability()
        result = cap.execute({"timezone": "Narnia/Nowhere"})
        assert result.success is False
        assert "não encontrado" in result.error

    def test_describe(self) -> None:
        cap = TimeCurrentCapability()
        assert "hora" in cap.describe()


class TestHttpJsonCapability:
    """http.readonly.fetch_json — GET-only JSON fetch."""

    def test_capability_id(self) -> None:
        cap = HttpJsonCapability()
        assert cap.capability_id == "http.readonly.fetch_json"

    def test_execute_missing_url(self) -> None:
        cap = HttpJsonCapability()
        result = cap.execute({})
        assert result.success is False
        assert "obrigatório" in result.error

    def test_execute_invalid_scheme(self) -> None:
        cap = HttpJsonCapability()
        result = cap.execute({"url": "ftp://example.com"})
        assert result.success is False
        assert "http://" in result.error

    def test_execute_blocked_localhost(self) -> None:
        cap = HttpJsonCapability()
        result = cap.execute({"url": "http://localhost/api"})
        assert result.success is False
        assert "bloqueados" in result.error

    def test_execute_blocked_internal_ip(self) -> None:
        cap = HttpJsonCapability()
        result = cap.execute({"url": "http://192.168.1.1/api"})
        assert result.success is False

    def test_execute_network_error(self) -> None:
        cap = HttpJsonCapability()
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            result = cap.execute({"url": "https://api.example.com/data"})
        assert result.success is False
        assert "timeout" in result.error.lower()

    def test_execute_success(self) -> None:
        cap = HttpJsonCapability()
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b'{"rate": 5.25}'
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = cap.execute({"url": "https://api.example.com/fx"})
        assert result.success is True
        assert result.data == {"rate": 5.25}


class TestFxRateCapability:
    """fx.rate — delega ao WebSearch."""

    def test_capability_id(self) -> None:
        cap = FxRateCapability()
        assert cap.capability_id == "fx.rate"

    def test_execute_delegates_to_web_search(self) -> None:
        mock_result = MagicMock(success=True, data={"results": []}, error="")
        cap = FxRateCapability()
        with patch(
            "arnaldo.capabilities.builtins.live_domain._web.execute",
            return_value=mock_result,
        ):
            result = cap.execute({"base": "USD", "target": "BRL"})
        assert result.success is True
        assert result.metadata["delegated_to"] == "search.public_web"

    def test_default_currencies(self) -> None:
        cap = FxRateCapability()
        mock_result = MagicMock(success=True, data={}, error="")
        with patch(
            "arnaldo.capabilities.builtins.live_domain._web.execute",
            return_value=mock_result,
        ) as mock_exec:
            cap.execute({})
        call_args = mock_exec.call_args[0][0]
        assert "USD" in call_args["query"]
        assert "BRL" in call_args["query"]


class TestWeatherCurrentCapability:
    """weather.current — delega ao WebSearch."""

    def test_capability_id(self) -> None:
        cap = WeatherCurrentCapability()
        assert cap.capability_id == "weather.current"

    def test_execute_missing_location(self) -> None:
        cap = WeatherCurrentCapability()
        result = cap.execute({})
        assert result.success is False
        assert "obrigatório" in result.error

    def test_execute_with_location(self) -> None:
        cap = WeatherCurrentCapability()
        mock_result = MagicMock(success=True, data={}, error="")
        with patch(
            "arnaldo.capabilities.builtins.live_domain._web.execute",
            return_value=mock_result,
        ):
            result = cap.execute({"location": "São Paulo"})
        assert result.success is True


class TestNewsLatestCapability:
    """news.latest — delega ao WebSearch."""

    def test_capability_id(self) -> None:
        cap = NewsLatestCapability()
        assert cap.capability_id == "news.latest"

    def test_execute_missing_topic(self) -> None:
        cap = NewsLatestCapability()
        result = cap.execute({})
        assert result.success is False
        assert "obrigatório" in result.error

    def test_execute_with_topic(self) -> None:
        cap = NewsLatestCapability()
        mock_result = MagicMock(success=True, data={}, error="")
        with patch(
            "arnaldo.capabilities.builtins.live_domain._web.execute",
            return_value=mock_result,
        ):
            result = cap.execute({"topic": "inteligência artificial"})
        assert result.success is True


class TestFinanceQuoteCapability:
    """finance.quote — delega ao WebSearch."""

    def test_capability_id(self) -> None:
        cap = FinanceQuoteCapability()
        assert cap.capability_id == "finance.quote"

    def test_execute_missing_symbol(self) -> None:
        cap = FinanceQuoteCapability()
        result = cap.execute({})
        assert result.success is False
        assert "obrigatório" in result.error

    def test_execute_with_symbol(self) -> None:
        cap = FinanceQuoteCapability()
        mock_result = MagicMock(success=True, data={}, error="")
        with patch(
            "arnaldo.capabilities.builtins.live_domain._web.execute",
            return_value=mock_result,
        ):
            result = cap.execute({"symbol": "PETR4"})
        assert result.success is True
        assert result.metadata["symbol"] == "PETR4"
