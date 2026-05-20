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
    API_STYLE_RESPONSES,
    API_STYLE_V1,
    AzureOpenAIConfig,
    TierConfig,
    load_config,
)
from .structured import (
    TypedResponse,
    build_response_format_for_style,
    dataclass_to_schema,
    instantiate_dataclass,
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
        url = self._build_url(tier_cfg)
        body = self._build_body(
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
                payload = self._send_request(url, body, effective_timeout, api_key=effective_api_key)
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
        return self._parse_response(payload, tier, tier_cfg)

    def chat_json(
        self,
        tier: str,
        messages: List[Dict[str, str]],
        *,
        schema_hint: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Helper para chamadas que esperam JSON estruturado."""
        kwargs.setdefault("response_format", {"type": "json_object"})

        effective_messages = list(messages)
        if schema_hint:
            effective_messages.append(
                {
                    "role": "system",
                    "content": (
                        "Responda APENAS com um objeto JSON válido seguindo este schema. "
                        f"Schema: {schema_hint}"
                    ),
                }
            )

        response = self.chat(tier, effective_messages, **kwargs)
        try:
            return json.loads(response.content)
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"LLM não retornou JSON válido: {response.content[:300]}"
            ) from exc

    def chat_typed(
        self,
        tier: str,
        messages: List[Dict[str, str]],
        *,
        response_model: type[T],
        max_retries: int = 2,
        **kwargs: Any,
    ) -> TypedResponse[T]:
        """Chamada tipada com `response_format=json_schema` + parse em dataclass.

        `refusal` é tratado como evento legítimo (não dispara exceção).
        Em falha de parse/coerção, tenta novamente até `max_retries`.
        """
        if max_retries < 0:
            raise ValueError("max_retries deve ser >= 0")

        schema = dataclass_to_schema(response_model)
        tier_cfg = self.config.tier(tier)
        response_format = build_response_format_for_style(
            schema,
            name=response_model.__name__,
            api_style=tier_cfg.api_style,
        )

        call_kwargs = dict(kwargs)
        call_kwargs["response_format"] = response_format
        call_kwargs.setdefault("temperature", 0.0)
        # Em respostas estruturadas, resumo de reasoning detalhado pode consumir
        # o orçamento de saída e impedir emissão do JSON final.
        call_kwargs.setdefault("reasoning_summary", "concise")

        attempts = max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            response = self.chat(tier=tier, messages=messages, **call_kwargs)
            if response.refusal is not None:
                return TypedResponse(
                    parsed=None,
                    refusal=response.refusal,
                    raw=response,
                    schema_used=schema,
                    retries=attempt,
                )

            try:
                payload = _decode_json_object(response.content)
                if not isinstance(payload, dict):
                    raise TypeError("payload JSON retornado não é objeto")
                parsed = instantiate_dataclass(response_model, payload)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                repaired_payload = self._attempt_typed_payload_repair(
                    tier=tier,
                    response_content=response.content,
                    response_format=response_format,
                    response_model=response_model,
                    error=exc,
                    call_kwargs=call_kwargs,
                )
                if repaired_payload is not None:
                    try:
                        parsed = instantiate_dataclass(response_model, repaired_payload)
                        return TypedResponse(
                            parsed=parsed,
                            refusal=None,
                            raw=response,
                            schema_used=schema,
                            retries=attempt,
                        )
                    except (TypeError, ValueError) as repaired_exc:
                        last_error = repaired_exc
                last_error = exc
                if isinstance(exc, json.JSONDecodeError) and _is_length_finish_reason(
                    response.finish_reason
                ):
                    call_kwargs["max_tokens"] = _next_max_tokens(
                        _coerce_positive_int(call_kwargs.get("max_tokens")),
                        tier_default=tier_cfg.default_max_tokens,
                        hard_cap=8192,
                    )
                call_kwargs["temperature"] = 0.0
                continue

            return TypedResponse(
                parsed=parsed,
                refusal=None,
                raw=response,
                schema_used=schema,
                retries=attempt,
            )

        raise LLMError(
            f"chat_typed: validação falhou após {attempts} tentativas: {last_error}"
        ) from last_error

    def _attempt_typed_payload_repair(
        self,
        *,
        tier: str,
        response_content: str,
        response_format: Dict[str, Any],
        response_model: type[T],
        error: Exception,
        call_kwargs: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        if not isinstance(error, json.JSONDecodeError):
            return None
        content = str(response_content or "").strip()
        if "{" not in content:
            return None
        tier_cfg = self.config.tier(tier)
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "Repare o JSON inválido e retorne APENAS um objeto JSON válido. "
                    "Não adicione explicações, markdown ou texto extra."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Contrato alvo: %s\nErro de parse: %s\nJSON inválido:\n%s"
                    % (response_model.__name__, str(error), content)
                ),
            },
        ]
        repair_kwargs = dict(call_kwargs)
        repair_kwargs["temperature"] = 0.0
        repair_kwargs["response_format"] = response_format
        repair_kwargs["max_tokens"] = _next_max_tokens(
            _coerce_positive_int(repair_kwargs.get("max_tokens")),
            tier_default=tier_cfg.default_max_tokens,
            hard_cap=8192,
        )
        try:
            repaired = self.chat(tier=tier, messages=repair_messages, **repair_kwargs)
        except (LLMError, RuntimeError):
            return None
        if repaired.refusal is not None:
            return None
        try:
            payload = _decode_json_object(repaired.content)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            return payload
        return None

    def generate_code(
        self,
        prompt: str,
        *,
        language: str = "python",
        context: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """Helper de alto nível para geração de código.

        Usa o tier CODEX se disponível, EXPERT como fallback.
        Sempre passa instruções claras de "código puro, sem prosa".
        """
        from .config import CODEX, EXPERT

        target_tier = CODEX if CODEX in self.config.tiers else EXPERT

        system_msg = (
            f"Você é um especialista em geração de código {language}. "
            "Retorne APENAS o código solicitado. "
            "Não inclua explicações, markdown fences ou comentários narrativos. "
            "Use docstrings e comentários técnicos onde apropriado."
        )

        messages = [
            {"role": "system", "content": system_msg},
        ]
        if context:
            messages.append({"role": "user", "content": f"Contexto:\n{context}"})
        messages.append({"role": "user", "content": prompt})

        return self.chat(
            tier=target_tier,
            messages=messages,
            reasoning_effort=reasoning_effort,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    def ping(self) -> bool:
        """Health check — chamada mínima para verificar conectividade.

        Tenta na ordem: fast → expert → god → codex.
        Retorna True no primeiro sucesso. Não lança.
        """
        if not self.is_configured:
            return False
        from .config import EXPERT, FAST, GOD, CODEX

        for tier in (FAST, EXPERT, GOD, CODEX):
            if tier not in self.config.tiers:
                continue
            try:
                self.chat(
                    tier=tier,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=16,
                    temperature=0.0,
                    timeout=15.0,
                )
                return True
            except (LLMError, RuntimeError, ValueError):
                continue
        return False

    # ─── helpers privados ─────────────────────────────────────────

    def _build_url(self, tier_cfg: TierConfig) -> str:
        """Constrói a URL apropriada por estilo de API."""
        api_version = tier_cfg.api_version or self.config.api_version

        if tier_cfg.api_style == API_STYLE_RESPONSES:
            # Responses API: <base_url>/responses (sem chat/completions, sem api-version)
            base = (tier_cfg.base_url or "").rstrip("/")
            if not base:
                raise LLMError(
                    f"Tier '{tier_cfg.name}' (api_style=responses) precisa de base_url"
                )
            if tier_cfg.api_version:
                return f"{base}/responses?api-version={tier_cfg.api_version}"
            return f"{base}/responses"

        if tier_cfg.api_style == API_STYLE_V1:
            base = (tier_cfg.base_url or "").rstrip("/")
            if not base:
                raise LLMError(
                    f"Tier '{tier_cfg.name}' (api_style=v1) precisa de base_url"
                )
            if tier_cfg.api_version:
                return f"{base}/chat/completions?api-version={tier_cfg.api_version}"
            return f"{base}/chat/completions"

        # API style: deployments (clássico)
        endpoint = (tier_cfg.base_url or self.config.endpoint).rstrip("/")
        return (
            f"{endpoint}/openai/deployments/{tier_cfg.model}/chat/completions"
            f"?api-version={api_version}"
        )

    def _build_body(
        self,
        *,
        tier_cfg: TierConfig,
        messages: List[Dict[str, str]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        response_format: Optional[Dict[str, Any]],
        reasoning_effort: Optional[str],
        reasoning_summary: Optional[str],
        extra: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        effective_max_tokens = (
            max_tokens if max_tokens is not None else tier_cfg.default_max_tokens
        )

        # ─── Responses API (Codex) ────────────────────────────────
        if tier_cfg.api_style == API_STYLE_RESPONSES:
            body: Dict[str, Any] = {
                "model": tier_cfg.model,
                "input": self._messages_to_responses_input(messages),
                "max_output_tokens": effective_max_tokens,
            }
            if tier_cfg.supports_reasoning:
                reasoning_block: Dict[str, str] = {}
                effort = reasoning_effort or tier_cfg.default_reasoning_effort
                if effort:
                    reasoning_block["effort"] = effort
                summary = reasoning_summary or tier_cfg.default_reasoning_summary
                if summary:
                    reasoning_block["summary"] = summary
                if reasoning_block:
                    body["reasoning"] = reasoning_block
            if response_format is not None:
                # Responses API: response_format → text.format
                body["text"] = {"format": response_format}
            if extra:
                body.update(extra)
            return body

        # ─── Chat Completions (deployments ou v1) ─────────────────
        body = {"messages": messages}

        # gpt-5 series usa max_completion_tokens em vez de max_tokens
        if tier_cfg.uses_max_completion_tokens:
            body["max_completion_tokens"] = effective_max_tokens
            if not tier_cfg.supports_reasoning:
                body["temperature"] = (
                    temperature if temperature is not None else tier_cfg.default_temperature
                )
        else:
            body["max_tokens"] = effective_max_tokens
            body["temperature"] = (
                temperature if temperature is not None else tier_cfg.default_temperature
            )

        if tier_cfg.api_style == API_STYLE_V1:
            body["model"] = tier_cfg.model

        if tier_cfg.supports_reasoning:
            effort = reasoning_effort or tier_cfg.default_reasoning_effort
            if effort:
                body["reasoning_effort"] = effort
            summary = reasoning_summary or tier_cfg.default_reasoning_summary
            if summary:
                body["reasoning_summary"] = summary

        if response_format is not None:
            body["response_format"] = response_format
        if extra:
            body.update(extra)

        return body

    @staticmethod
    def _messages_to_responses_input(messages: List[Dict[str, str]]) -> Any:
        """Converte messages do formato Chat Completions para input da Responses API.

        - Lista vazia → string vazia
        - 1 mensagem de user → string (formato mais simples)
        - Múltiplas mensagens → itens tipados `{"type":"message",...}`
        """
        if not messages:
            return ""

        # Caso simples: 1 user message → string
        if len(messages) == 1 and messages[0].get("role") == "user":
            return messages[0].get("content", "")

        # Caso geral: converte para input items tipados.
        # Azure Responses API em /openai/v1 exige `type` explícito.
        items = []
        for msg in messages:
            role = str(msg.get("role", "user")).strip() or "user"
            if role not in {"system", "developer", "user", "assistant"}:
                role = "user"
            content = msg.get("content", "")
            if isinstance(content, list):
                text = "\n".join(str(part) for part in content if str(part).strip())
            else:
                text = str(content)
            items.append(
                {
                    "type": "message",
                    "role": role,
                    "content": [
                        {
                            "type": "input_text",
                            "text": text,
                        }
                    ],
                }
            )
        return items

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

    def _parse_response(
        self,
        payload: Dict[str, Any],
        tier: str,
        tier_cfg: TierConfig,
    ) -> LLMResponse:
        # ─── Responses API ────────────────────────────────────────
        if tier_cfg.api_style == API_STYLE_RESPONSES:
            return self._parse_responses_api(payload, tier, tier_cfg)

        # ─── Chat Completions (clássico + v1) ────────────────────
        choices = payload.get("choices") or []
        if not choices:
            raise LLMError(f"Azure OpenAI retornou sem choices: {payload}")

        choice = choices[0]
        message = choice.get("message", {})
        content = _extract_message_content_text(message.get("content", ""))
        refusal = _extract_chat_refusal(message)
        if not content:
            parsed_payload = message.get("parsed")
            if isinstance(parsed_payload, dict):
                content = json.dumps(parsed_payload, ensure_ascii=False)
            elif isinstance(parsed_payload, list):
                content = json.dumps(parsed_payload, ensure_ascii=False)
        if not content:
            content = _extract_tool_call_arguments(message.get("tool_calls"))

        reasoning_summary = None
        if tier_cfg.supports_reasoning:
            reasoning_summary = (
                message.get("reasoning_summary")
                or choice.get("reasoning_summary")
                or (choice.get("reasoning", {}) or {}).get("summary")
            )

        return LLMResponse(
            content=content,
            tier=tier,
            deployment=tier_cfg.model,
            model=payload.get("model", tier_cfg.model),
            finish_reason=choice.get("finish_reason", "stop"),
            usage=payload.get("usage", {}),
            reasoning_summary=reasoning_summary,
            refusal=refusal,
            raw=payload,
        )

    @staticmethod
    def _parse_responses_api(
        payload: Dict[str, Any],
        tier: str,
        tier_cfg: TierConfig,
    ) -> LLMResponse:
        """Parser para formato da Responses API.

        Estrutura:
        {
          "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "..."}], ...}
          ],
          "usage": {"input_tokens": ..., "output_tokens": ..., "total_tokens": ...},
          "reasoning": {"effort": "...", "summary": "..."},
          "status": "completed" | ...,
          ...
        }
        """
        status = payload.get("status", "")
        output_items = payload.get("output", []) or []
        if not output_items:
            raise LLMError(
                f"Responses API retornou sem output (status={status}): {payload}"
            )

        # Encontra a primeira mensagem com texto
        content_chunks: list[str] = []
        refusal: str | None = None
        for item in output_items:
            if item.get("type") == "refusal":
                refusal = str(item.get("refusal", "")).strip() or refusal
                continue
            if item.get("type") != "message":
                continue
            for chunk in item.get("content", []) or []:
                chunk_type = chunk.get("type")
                if chunk_type in ("output_text", "text"):
                    text = str(chunk.get("text", ""))
                    if text:
                        content_chunks.append(text)
                elif chunk_type == "refusal":
                    refusal = str(chunk.get("refusal", "")).strip() or refusal

        content_text = "\n".join(content_chunks).strip()

        # Normaliza usage para o mesmo schema do chat completions
        raw_usage = payload.get("usage", {}) or {}
        normalized_usage = {
            "prompt_tokens": raw_usage.get("input_tokens", 0),
            "completion_tokens": raw_usage.get("output_tokens", 0),
            "total_tokens": raw_usage.get("total_tokens", 0),
        }
        # Preserva reasoning_tokens se presente
        out_details = raw_usage.get("output_tokens_details", {}) or {}
        if out_details.get("reasoning_tokens"):
            normalized_usage["reasoning_tokens"] = out_details["reasoning_tokens"]

        reasoning_block = payload.get("reasoning", {}) or {}
        reasoning_summary = reasoning_block.get("summary")

        return LLMResponse(
            content=content_text,
            tier=tier,
            deployment=tier_cfg.model,
            model=payload.get("model", tier_cfg.model),
            finish_reason=status or "completed",
            usage=normalized_usage,
            reasoning_summary=reasoning_summary,
            refusal=refusal,
            raw=payload,
        )


def _extract_message_content_text(content: Any) -> str:
    """Normaliza `message.content` em string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "output_text"}:
                    text = item.get("text", "")
                    if isinstance(text, dict):
                        value = text.get("value", "")
                        if value:
                            chunks.append(str(value))
                    elif text:
                        chunks.append(str(text))
                    continue
                nested = item.get("text")
                if isinstance(nested, dict):
                    value = nested.get("value", "")
                    if value:
                        chunks.append(str(value))
        return "\n".join(chunks).strip()
    return str(content or "")


def _decode_json_object(content: str) -> Any:
    """Decodifica JSON com tolerância a ruído comum de modelos.

    Estratégia:
    1. tenta parse direto;
    2. remove code fences markdown;
    3. extrai o primeiro objeto JSON balanceado;
    4. corrige newlines/tabs crus dentro de strings.
    """
    cleaned = str(content or "").strip()
    if not cleaned:
        raise json.JSONDecodeError("empty JSON content", cleaned, 0)

    candidates = _json_decode_candidates(cleaned)
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            normalized = _escape_control_chars_in_json_strings(candidate)
            if normalized == candidate:
                continue
            try:
                return json.loads(normalized)
            except json.JSONDecodeError as normalized_exc:
                last_error = normalized_exc
                continue
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("unable to decode JSON object", cleaned, 0)


def _json_decode_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def _push(value: str) -> None:
        normalized = value.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    _push(text)
    without_fence = _strip_markdown_code_fence(text)
    _push(without_fence)

    for base in (text, without_fence):
        extracted = _extract_first_balanced_json_object(base)
        if extracted:
            _push(extracted)

    return candidates


def _strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 3:
        return stripped
    if not lines[-1].strip().startswith("```"):
        return stripped
    body = "\n".join(lines[1:-1]).strip()
    return body or stripped


def _extract_first_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    in_string = False
    escaped = False
    depth = 0
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _escape_control_chars_in_json_strings(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    changed = False

    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if ch == "\n":
                out.append("\\n")
                changed = True
                continue
            if ch == "\r":
                out.append("\\r")
                changed = True
                continue
            if ch == "\t":
                out.append("\\t")
                changed = True
                continue
            out.append(ch)
            continue

        out.append(ch)
        if ch == '"':
            in_string = True
            escaped = False

    if not changed:
        return text
    return "".join(out)


def _is_transient_llm_error(error: LLMError) -> bool:
    if error.status in {408, 409, 429, 500, 502, 503, 504}:
        return True
    message = str(error).lower()
    transient_markers = (
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connection closed",
        "remote end closed connection",
        "network error",
    )
    return any(marker in message for marker in transient_markers)


def _looks_like_json_object(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return "{" in stripped and "}" in stripped and stripped.find("{") < stripped.rfind("}")


def _extract_chat_refusal(message: Dict[str, Any]) -> str | None:
    refusal = message.get("refusal")
    if isinstance(refusal, str):
        stripped = refusal.strip()
        if stripped:
            return stripped
    content = message.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "refusal":
            continue
        raw = item.get("refusal")
        if not raw:
            continue
        stripped = str(raw).strip()
        if stripped:
            return stripped
    return None


def _extract_tool_call_arguments(tool_calls: Any) -> str:
    if not isinstance(tool_calls, list):
        return ""
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        arguments = function.get("arguments")
        if arguments is None:
            continue
        text = str(arguments).strip()
        if text:
            return text
    return ""


def _is_length_finish_reason(finish_reason: str) -> bool:
    normalized = str(finish_reason or "").strip().lower()
    return normalized in {"length", "max_tokens", "max_output_tokens", "incomplete"}


def _coerce_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _next_max_tokens(
    current: int | None,
    *,
    tier_default: int,
    hard_cap: int,
) -> int:
    seed = current if current is not None else max(256, int(tier_default))
    grown = int(seed * 1.6)
    floor = max(seed + 256, tier_default)
    return min(hard_cap, max(grown, floor))
