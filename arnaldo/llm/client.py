"""Azure OpenAI client using stdlib only — zero external dependencies.

Suporta dois estilos de API:
- deployments: URL inclui /openai/deployments/<name>/chat/completions
- v1: URL base inclui /openai/v1/, model vai no body, suporta reasoning_effort
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypeVar

from .config import (
    AzureOpenAIConfig,
    TierConfig,
    load_config,
)
from .request_builder import build_url, build_body, parse_response
from . import operations as _hl
from .response_parser import (
    is_transient_llm_error as _is_transient_llm_error,
)
from .structured import (
    TypedResponse,
)


T = TypeVar("T")


class LLMError(RuntimeError):
    """Erro genérico de chamada LLM. Carrega status code e body quando aplicável."""

    def __init__(self, message: str, *, status: Optional[int] = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class LLMResponse:
    """Envelope tipado da resposta do LLM."""

    content: str
    tier: str
    deployment: str
    model: str
    finish_reason: str
    usage: Dict[str, int] = field(default_factory=dict)
    reasoning_summary: Optional[str] = None  # populado quando tier tem reasoning
    refusal: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class AzureOpenAIClient:
    """Cliente HTTPS para Azure OpenAI Chat Completions.

    Suporta os dois estilos de API Azure:

    1. **deployments** (clássico):
       URL: {endpoint}/openai/deployments/{deployment}/chat/completions
       Body: {"messages": [...], "max_tokens": ..., "temperature": ...}

    2. **v1** (Responses-style com reasoning effort):
       URL: {base_url}/chat/completions
       Body: {"model": "...", "messages": [...], "reasoning_effort": "xhigh", ...}

    Exemplo:
        client = AzureOpenAIClient()

        # Tier clássico
        r = client.chat(tier="expert", messages=[{"role": "user", "content": "Olá"}])

        # Tier Codex com reasoning
        r = client.chat(
            tier="codex",
            messages=[{"role": "user", "content": "Implemente um connector HTTP"}],
            reasoning_effort="xhigh",
        )
    """

    def __init__(self, config: Optional[AzureOpenAIConfig] = None) -> None:
        self.config = config or load_config()

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    def chat(
        self,
        tier: str,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        reasoning_effort: Optional[str] = None,
        reasoning_summary: Optional[str] = None,
        timeout: Optional[float] = None,
        retry_attempts: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """Chamada síncrona ao Azure OpenAI.

        Args:
            tier: "god", "expert", "fast" ou "codex"
            messages: lista de {"role": ..., "content": ...}
            temperature: override (senão usa default do tier)
            max_tokens: override (senão usa default do tier)
            response_format: {"type": "json_object"} para JSON mode
            reasoning_effort: "low" | "medium" | "high" | "xhigh"
                              (apenas tiers com supports_reasoning=True)
            reasoning_summary: "auto" | "concise" | "detailed"
            timeout: override de timeout em segundos
            retry_attempts: total de tentativas para falhas transitórias (default=3)
            extra: campos adicionais a passar para a API

        Raises:
            LLMError: se a chamada falhar (HTTP, rede, JSON inválido)
            RuntimeError: se cliente não está configurado
        """
        if not self.is_configured:
            raise RuntimeError(
                "AzureOpenAIClient não configurado. "
                "Verifique .env (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY)."
            )

        tier_cfg: TierConfig = self.config.tier(tier)
        url = build_url(
            tier_cfg, endpoint=self.config.endpoint, api_version=self.config.api_version
        )
        body = build_body(
            tier_cfg=tier_cfg,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
            extra=extra,
        )

        effective_timeout = timeout if timeout is not None else self.config.timeout_seconds
        # api_key do tier > api_key global
        effective_api_key = tier_cfg.api_key or self.config.api_key
        attempts = max(1, int(retry_attempts or 1))
        payload: Dict[str, Any] | None = None
        last_error: LLMError | None = None
        for attempt in range(1, attempts + 1):
            try:
                payload = self._send_request(
                    url, body, effective_timeout, api_key=effective_api_key
                )
                last_error = None
                break
            except LLMError as exc:
                last_error = exc
                if attempt >= attempts or not _is_transient_llm_error(exc):
                    raise
                backoff_seconds = min(3.0, 0.4 * float(attempt))
                time.sleep(backoff_seconds)
                continue
        if payload is None:
            if last_error is not None:
                raise last_error
            raise LLMError("Falha inesperada ao enviar requisição para Azure OpenAI.")
        parsed = parse_response(payload, tier, tier_cfg)
        return LLMResponse(**parsed)

    def chat_json(self, tier: str, messages: list, **kwargs: Any) -> Dict[str, Any]:
        return _hl.chat_json(self, tier, messages, **kwargs)

    def chat_typed(self, tier: str, messages: list, **kwargs: Any) -> "TypedResponse":
        return _hl.chat_typed(self, tier, messages, **kwargs)

    def chat_stream(self, tier: str, messages: list, **kwargs: Any):
        """Streaming interface — yields content chunks via SSE.

        Usa stream=true na Azure OpenAI e parseia Server-Sent Events.
        Fallback: yield completo se streaming falhar.
        """
        tier_cfg = self.config.tiers.get(tier)
        if tier_cfg is None:
            raise LLMError(f"Tier '{tier}' não configurado.")
        url = self._build_url(tier_cfg)
        body = self._build_body(
            messages=messages,
            temperature=kwargs.get("temperature", tier_cfg.default_temperature),
            max_tokens=kwargs.get("max_tokens", tier_cfg.default_max_tokens),
        )
        body["stream"] = True
        effective_api_key = tier_cfg.api_key or self.config.api_key

        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "api-key": effective_api_key,
                "User-Agent": "arnaldo-kernel/0.1",
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.config.timeout_seconds)
            yield from self._parse_sse_stream(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            # Fallback: chamada não-streaming
            resp = self.chat(tier=tier, messages=messages, **kwargs)
            yield resp.content

    @staticmethod
    def _parse_sse_stream(response: Any):
        """Parseia SSE stream e yield content deltas."""
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

    def generate_code(self, prompt: str, **kwargs: Any) -> LLMResponse:
        return _hl.generate_code(self, prompt, **kwargs)

    def ping(self) -> bool:
        return _hl.ping(self)

    def _build_url(self, tier_cfg: Any) -> str:
        try:
            return build_url(
                tier_cfg, endpoint=self.config.endpoint, api_version=self.config.api_version
            )
        except ValueError as exc:
            raise LLMError(str(exc)) from exc

    def _build_body(self, **kw: Any) -> Dict[str, Any]:
        return build_body(**kw)

    def _parse_response(self, payload: Dict[str, Any], tier: str, tier_cfg: Any) -> "LLMResponse":
        return LLMResponse(**parse_response(payload, tier, tier_cfg))

    def _send_request(
        self,
        url: str,
        body: Dict[str, Any],
        timeout: float,
        *,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "api-key": api_key or self.config.api_key,
                "User-Agent": "arnaldo-kernel/0.1",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload_bytes = response.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise LLMError(
                f"Azure OpenAI HTTP {exc.code}: {exc.reason}",
                status=exc.code,
                body=body_text,
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Azure OpenAI network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(f"Azure OpenAI timeout após {timeout}s") from exc

        try:
            return json.loads(payload_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LLMError(f"Resposta inválida do Azure OpenAI: {exc}") from exc
