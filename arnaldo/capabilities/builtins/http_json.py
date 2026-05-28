"""Capability http.readonly.fetch_json — GET-only JSON fetch."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from arnaldo.capabilities.base import CapabilityResult, make_source, timed_execution

logger = logging.getLogger("arnaldo.capabilities")

_TIMEOUT = 10
_MAX_RESPONSE_SIZE = 50_000
_BLOCKED_PATTERNS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168."}
_USER_AGENT = "ArnaldAI/0.2 (stdlib-only; read-only)"


class HttpJsonCapability:
    """GET-only JSON fetch — read-only, sem side-effects."""

    capability_id = "http.readonly.fetch_json"

    def describe(self) -> str:
        return "buscar dados JSON de API pública via GET — read-only"

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        url = str(params.get("url", "")).strip()
        if not url:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("http.readonly.fetch_json"),
                error="Parâmetro 'url' é obrigatório",
            )
        if not url.startswith(("http://", "https://")):
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"http.json:{url}"),
                error="URL deve começar com http:// ou https://",
            )
        host = urllib.parse.urlparse(url).hostname or ""
        if any(p in host for p in _BLOCKED_PATTERNS):
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"http.json:{url}"),
                error="IPs internos bloqueados por segurança",
            )

        headers = params.get("headers", {})
        if not isinstance(headers, dict):
            headers = {}
        headers.setdefault("User-Agent", _USER_AGENT)
        headers.setdefault("Accept", "application/json")

        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = resp.read(_MAX_RESPONSE_SIZE)
                data = json.loads(body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("http.readonly.fetch_json falhou: %s", exc)
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"http.json:{url}"),
                error=f"Fetch falhou: {exc}",
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"http.json:{url}"),
                error=f"Resposta não é JSON válido: {exc}",
            )

        return CapabilityResult(
            success=True,
            data=data,
            source=make_source(f"http.json:{url}"),
            metadata={"url": url},
        )
