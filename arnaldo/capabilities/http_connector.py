"""Capability connector.http.generic — requisições HTTP a APIs externas."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base import CapabilityResult, make_source, timed_execution

logger = logging.getLogger("arnaldo.capabilities")

_TIMEOUT = 15
_MAX_RESPONSE_SIZE = 50_000  # 50KB max response body
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}

# Domínios bloqueados por segurança
_BLOCKED_PATTERNS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168."}


class HttpConnectorCapability:
    """Requisições HTTP genéricas — stdlib only, com segurança básica."""

    capability_id = "connector.http.generic"

    def describe(self) -> str:
        return (
            "Fazer requisições HTTP a APIs externas — GET, POST, "
            "REST, JSON, webhook, integração com serviços terceiros"
        )

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        """Executa requisição HTTP."""
        url = str(params.get("url", "")).strip()
        if not url:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("connector.http.generic"),
                error="Parâmetro 'url' é obrigatório",
            )

        if not url.startswith(("http://", "https://")):
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"connector.http:{url}"),
                error="URL deve começar com http:// ou https://",
            )

        # Segurança: bloquear IPs internos
        host = urllib.parse.urlparse(url).hostname or ""
        if any(p in host for p in _BLOCKED_PATTERNS):
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"connector.http:{url}"),
                error="Acesso a endereços internos/privados bloqueado",
            )

        method = str(params.get("method", "GET")).upper()
        if method not in _ALLOWED_METHODS:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"connector.http:{url}"),
                error=f"Método '{method}' não permitido. Use: {_ALLOWED_METHODS}",
            )

        headers = params.get("headers", {})
        if not isinstance(headers, dict):
            headers = {}
        body = params.get("body")
        timeout = min(float(params.get("timeout", _TIMEOUT)), 30.0)

        try:
            result = _http_request(url, method, headers, body, timeout)
        except Exception as exc:
            logger.warning("HTTP request falhou: %s %s → %s", method, url, exc)
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source(f"connector.http:{url}"),
                error=f"{method} {url} falhou: {exc}",
            )

        return CapabilityResult(
            success=True,
            data=result,
            source=make_source(f"connector.http:{url}"),
            metadata={"method": method, "url": url},
        )


def _http_request(
    url: str,
    method: str,
    headers: dict[str, str],
    body: Any,
    timeout: float,
) -> dict[str, Any]:
    """Executa HTTP request com urllib — stdlib only."""
    req_data = None
    if body is not None:
        if isinstance(body, dict):
            req_data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            req_data = body.encode("utf-8")
        else:
            req_data = str(body).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=req_data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.status
        resp_headers = dict(resp.headers)
        raw_body = resp.read(_MAX_RESPONSE_SIZE).decode("utf-8", errors="replace")

    # Tentar parsear como JSON
    parsed_body: Any = raw_body
    content_type = resp_headers.get("Content-Type", "")
    if "json" in content_type:
        try:
            parsed_body = json.loads(raw_body)
        except json.JSONDecodeError:
            pass

    return {
        "status": status,
        "headers": resp_headers,
        "body": parsed_body,
    }
