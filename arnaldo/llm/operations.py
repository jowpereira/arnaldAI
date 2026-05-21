"""Operações de alto nível do AzureOpenAIClient — chat_typed, generate_code, ping."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypeVar

from .json_repair import decode_json_object
from .response_parser import coerce_positive_int, is_length_finish_reason, next_max_tokens
from .structured import (
    TypedResponse,
    build_response_format_for_style,
    dataclass_to_schema,
    instantiate_dataclass,
)

if TYPE_CHECKING:
    from .client import AzureOpenAIClient, LLMError, LLMResponse

T = TypeVar("T")


def chat_json(
    client: AzureOpenAIClient,
    tier: str,
    messages: List[Dict[str, str]],
    *,
    schema_hint: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Helper para chamadas que esperam JSON estruturado."""
    from .client import LLMError

    kwargs.setdefault("response_format", {"type": "json_object"})
    effective_messages = list(messages)
    if schema_hint:
        effective_messages.append(
            {
                "role": "system",
                "content": f"Responda APENAS com um objeto JSON válido seguindo este schema. Schema: {schema_hint}",
            }
        )
    response = client.chat(tier, effective_messages, **kwargs)
    try:
        return json.loads(response.content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM não retornou JSON válido: {response.content[:300]}") from exc


def chat_typed(
    client: AzureOpenAIClient,
    tier: str,
    messages: List[Dict[str, str]],
    *,
    response_model: type[T],
    max_retries: int = 2,
    **kwargs: Any,
) -> TypedResponse[T]:
    """Chamada tipada com response_format=json_schema + parse em dataclass."""
    from .client import LLMError

    if max_retries < 0:
        raise ValueError("max_retries deve ser >= 0")

    schema = dataclass_to_schema(response_model)
    tier_cfg = client.config.tier(tier)
    response_format = build_response_format_for_style(
        schema,
        name=response_model.__name__,
        api_style=tier_cfg.api_style,
    )

    call_kwargs = dict(kwargs)
    call_kwargs["response_format"] = response_format
    call_kwargs.setdefault("temperature", 0.0)
    call_kwargs.setdefault("reasoning_summary", "concise")

    attempts = max_retries + 1
    last_error: Exception | None = None

    for attempt in range(attempts):
        response = client.chat(tier=tier, messages=messages, **call_kwargs)
        if response.refusal is not None:
            return TypedResponse(
                parsed=None,
                refusal=response.refusal,
                raw=response,
                schema_used=schema,
                retries=attempt,
            )
        try:
            payload = decode_json_object(response.content)
            if not isinstance(payload, dict):
                raise TypeError("payload JSON retornado não é objeto")
            parsed = instantiate_dataclass(response_model, payload)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            repaired = _attempt_repair(
                client,
                tier=tier,
                response_content=response.content,
                response_format=response_format,
                response_model=response_model,
                error=exc,
                call_kwargs=call_kwargs,
            )
            if repaired is not None:
                try:
                    parsed = instantiate_dataclass(response_model, repaired)
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
            if isinstance(exc, json.JSONDecodeError) and is_length_finish_reason(
                response.finish_reason
            ):
                call_kwargs["max_tokens"] = next_max_tokens(
                    coerce_positive_int(call_kwargs.get("max_tokens")),
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


def _attempt_repair(
    client: AzureOpenAIClient,
    *,
    tier: str,
    response_content: str,
    response_format: Dict[str, Any],
    response_model: type,
    error: Exception,
    call_kwargs: Dict[str, Any],
) -> Dict[str, Any] | None:
    """Tenta reparar JSON inválido via segunda chamada LLM."""
    from .client import LLMError

    if not isinstance(error, json.JSONDecodeError):
        return None
    content = str(response_content or "").strip()
    if "{" not in content:
        return None
    tier_cfg = client.config.tier(tier)
    repair_messages = [
        {
            "role": "system",
            "content": "Repare o JSON inválido e retorne APENAS um objeto JSON válido.",
        },
        {
            "role": "user",
            "content": f"Contrato alvo: {response_model.__name__}\nErro: {error}\nJSON:\n{content}",
        },
    ]
    repair_kwargs = dict(call_kwargs)
    repair_kwargs["temperature"] = 0.0
    repair_kwargs["response_format"] = response_format
    repair_kwargs["max_tokens"] = next_max_tokens(
        coerce_positive_int(repair_kwargs.get("max_tokens")),
        tier_default=tier_cfg.default_max_tokens,
        hard_cap=8192,
    )
    try:
        repaired = client.chat(tier=tier, messages=repair_messages, **repair_kwargs)
    except (LLMError, RuntimeError):
        return None
    if repaired.refusal is not None:
        return None
    try:
        payload = decode_json_object(repaired.content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def generate_code(
    client: AzureOpenAIClient,
    prompt: str,
    *,
    language: str = "python",
    context: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
) -> Any:
    """Helper de alto nível para geração de código."""
    from .config import CODEX, EXPERT

    target_tier = CODEX if CODEX in client.config.tiers else EXPERT
    system_msg = (
        f"Você é um especialista em geração de código {language}. "
        "Retorne APENAS o código solicitado. "
        "Não inclua explicações, markdown fences ou comentários narrativos. "
        "Use docstrings e comentários técnicos onde apropriado."
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_msg}]
    if context:
        messages.append({"role": "user", "content": f"Contexto:\n{context}"})
    messages.append({"role": "user", "content": prompt})
    return client.chat(
        tier=target_tier,
        messages=messages,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def ping(client: AzureOpenAIClient) -> bool:
    """Health check — tenta fast → expert → god → codex."""
    if not client.is_configured:
        return False
    from .config import EXPERT, FAST, GOD, CODEX

    for tier in (FAST, EXPERT, GOD, CODEX):
        if tier not in client.config.tiers:
            continue
        try:
            client.chat(
                tier=tier,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=16,
                temperature=0.0,
                timeout=15.0,
            )
            return True
        except Exception:
            continue
    return False
