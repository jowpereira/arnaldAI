from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pytest

from arnaldo.llm import API_STYLE_DEPLOYMENTS, API_STYLE_RESPONSES, TierConfig
from arnaldo.llm.client import AzureOpenAIClient, LLMResponse
from arnaldo.llm.config import AzureOpenAIConfig
from arnaldo.llm.structured import (
    build_response_format_for_style,
    dataclass_to_schema,
    instantiate_dataclass,
)


class Priority(str, Enum):
    LOW = "low"
    HIGH = "high"


@dataclass
class Child:
    value: str


@dataclass
class Parent:
    name: str
    optional_note: str | None
    tags: list[str]
    child: Child
    priority: Priority


class StubAzureClient(AzureOpenAIClient):
    def __init__(self, *, api_style: str, responses: list[LLMResponse]) -> None:
        tier = TierConfig(
            name="fast",
            model="fast-tier",
            description="fast",
            api_style=api_style,
            base_url=(
                "https://example.services.ai.azure.com/api/projects/p/openai/v1"
                if api_style == API_STYLE_RESPONSES
                else None
            ),
        )
        config = AzureOpenAIConfig(
            endpoint="https://example.cognitiveservices.azure.com",
            api_key="fake",
            api_version="2025-04-01-preview",
            tiers={"fast": tier},
        )
        super().__init__(config=config)
        self._stub_responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def chat(self, tier: str, messages: list[dict[str, str]], **kwargs: object) -> LLMResponse:
        self.calls.append({"tier": tier, "messages": messages, "kwargs": kwargs})
        if not self._stub_responses:
            raise AssertionError("stub sem respostas restantes")
        return self._stub_responses.pop(0)


def _response(
    *,
    content: str,
    refusal: str | None = None,
    finish_reason: str = "stop",
) -> LLMResponse:
    return LLMResponse(
        content=content,
        tier="fast",
        deployment="fast-tier",
        model="fast-tier",
        finish_reason=finish_reason,
        refusal=refusal,
    )


def test_dataclass_to_schema_is_strict_and_nested() -> None:
    schema = dataclass_to_schema(Parent)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"name", "optional_note", "tags", "child", "priority"}

    child_schema = schema["properties"]["child"]
    assert child_schema["type"] == "object"
    assert child_schema["additionalProperties"] is False
    assert child_schema["required"] == ["value"]


def test_dataclass_to_schema_handles_optional_list_and_enum() -> None:
    schema = dataclass_to_schema(Parent)
    optional_type = schema["properties"]["optional_note"]["type"]
    assert sorted(optional_type) == ["null", "string"]
    assert schema["properties"]["tags"]["items"]["type"] == "string"
    assert schema["properties"]["priority"]["enum"] == ["low", "high"]


def test_build_response_format_by_style() -> None:
    schema = dataclass_to_schema(Child)
    responses_format = build_response_format_for_style(
        schema, name="Child", api_style=API_STYLE_RESPONSES
    )
    assert responses_format["type"] == "json_schema"
    assert responses_format["name"] == "Child"
    assert responses_format["strict"] is True

    deployments_format = build_response_format_for_style(
        schema, name="Child", api_style=API_STYLE_DEPLOYMENTS
    )
    assert deployments_format["type"] == "json_schema"
    assert deployments_format["json_schema"]["name"] == "Child"
    assert deployments_format["json_schema"]["strict"] is True


def test_instantiate_dataclass_nested() -> None:
    data = {
        "name": "ana",
        "optional_note": None,
        "tags": ["x", "y"],
        "child": {"value": "ok"},
        "priority": "high",
    }
    parsed = instantiate_dataclass(Parent, data)
    assert isinstance(parsed, Parent)
    assert isinstance(parsed.child, Child)
    assert parsed.priority is Priority.HIGH


def test_instantiate_dataclass_rejects_invalid_nested_shape() -> None:
    data = {
        "name": "ana",
        "optional_note": None,
        "tags": ["x"],
        "child": "invalid",
        "priority": "high",
    }
    with pytest.raises(TypeError):
        instantiate_dataclass(Parent, data)


def test_chat_typed_success_uses_responses_envelope() -> None:
    client = StubAzureClient(
        api_style=API_STYLE_RESPONSES,
        responses=[
            _response(
                content=(
                    '{"name":"ana","optional_note":null,"tags":["x"],'
                    '"child":{"value":"ok"},"priority":"high"}'
                )
            )
        ],
    )
    result = client.chat_typed(
        tier="fast",
        messages=[{"role": "user", "content": "extraia"}],
        response_model=Parent,
    )

    assert result.is_success
    assert result.parsed is not None
    call_kwargs = client.calls[0]["kwargs"]
    assert call_kwargs["response_format"]["type"] == "json_schema"
    assert call_kwargs["response_format"]["name"] == "Parent"


def test_chat_typed_retries_after_invalid_json() -> None:
    client = StubAzureClient(
        api_style=API_STYLE_RESPONSES,
        responses=[
            _response(content="not-json"),
            _response(
                content=(
                    '{"name":"ana","optional_note":"n","tags":["x"],'
                    '"child":{"value":"ok"},"priority":"low"}'
                )
            ),
        ],
    )
    result = client.chat_typed(
        tier="fast",
        messages=[{"role": "user", "content": "extraia"}],
        response_model=Parent,
        max_retries=1,
        temperature=0.7,
    )

    assert result.is_success
    assert result.retries == 1
    assert len(client.calls) == 2
    assert client.calls[0]["kwargs"]["temperature"] == 0.7
    assert client.calls[1]["kwargs"]["temperature"] == 0.0


def test_chat_typed_parses_json_inside_markdown_fence() -> None:
    fenced = (
        "```json\n"
        '{"name":"ana","optional_note":"n","tags":["x"],'
        '"child":{"value":"ok"},"priority":"low"}\n'
        "```"
    )
    client = StubAzureClient(
        api_style=API_STYLE_RESPONSES,
        responses=[_response(content=fenced)],
    )
    result = client.chat_typed(
        tier="fast",
        messages=[{"role": "user", "content": "extraia"}],
        response_model=Parent,
    )

    assert result.is_success
    assert result.parsed is not None
    assert result.parsed.child.value == "ok"


def test_chat_typed_parses_first_object_when_text_has_prefix_suffix() -> None:
    noisy = (
        "Segue abaixo o JSON solicitado:\n"
        '{"name":"ana","optional_note":"n","tags":["x"],'
        '"child":{"value":"ok"},"priority":"low"}\n'
        "fim"
    )
    client = StubAzureClient(
        api_style=API_STYLE_RESPONSES,
        responses=[_response(content=noisy)],
    )
    result = client.chat_typed(
        tier="fast",
        messages=[{"role": "user", "content": "extraia"}],
        response_model=Parent,
    )

    assert result.is_success
    assert result.parsed is not None
    assert result.parsed.name == "ana"


def test_chat_typed_recovers_from_raw_newline_inside_json_string() -> None:
    broken = (
        '{"name":"ana","optional_note":"linha 1\n'
        'linha 2","tags":["x"],"child":{"value":"ok"},"priority":"high"}'
    )
    client = StubAzureClient(
        api_style=API_STYLE_RESPONSES,
        responses=[_response(content=broken)],
    )
    result = client.chat_typed(
        tier="fast",
        messages=[{"role": "user", "content": "extraia"}],
        response_model=Parent,
    )

    assert result.is_success
    assert result.parsed is not None
    assert result.parsed.optional_note == "linha 1\nlinha 2"


def test_chat_typed_repairs_invalid_json_using_secondary_call() -> None:
    broken = (
        '{"name":"ana","optional_note":"nota","tags":["x"],'
        '"child":{"value":"ok"},"priority":"high","extra":"abc'
    )
    repaired = (
        '{"name":"ana","optional_note":"nota","tags":["x"],'
        '"child":{"value":"ok"},"priority":"high"}'
    )
    client = StubAzureClient(
        api_style=API_STYLE_RESPONSES,
        responses=[_response(content=broken), _response(content=repaired)],
    )
    result = client.chat_typed(
        tier="fast",
        messages=[{"role": "user", "content": "extraia"}],
        response_model=Parent,
        max_retries=0,
    )

    assert result.is_success
    assert result.parsed is not None
    assert result.parsed.priority is Priority.HIGH
    assert len(client.calls) == 2


def test_chat_typed_increases_max_tokens_after_incomplete_finish_reason() -> None:
    client = StubAzureClient(
        api_style=API_STYLE_RESPONSES,
        responses=[
            _response(content='{"name":"ana","optional_note":"x"', finish_reason="incomplete"),
            _response(
                content=(
                    '{"name":"ana","optional_note":"n","tags":["x"],'
                    '"child":{"value":"ok"},"priority":"low"}'
                )
            ),
        ],
    )
    result = client.chat_typed(
        tier="fast",
        messages=[{"role": "user", "content": "extraia"}],
        response_model=Parent,
        max_retries=1,
        max_tokens=320,
    )

    assert result.is_success
    assert len(client.calls) == 2
    first_tokens = client.calls[0]["kwargs"]["max_tokens"]
    second_tokens = client.calls[1]["kwargs"]["max_tokens"]
    assert int(second_tokens) > int(first_tokens)


def test_chat_typed_defaults_reasoning_summary_to_concise() -> None:
    client = StubAzureClient(
        api_style=API_STYLE_RESPONSES,
        responses=[
            _response(
                content=(
                    '{"name":"ana","optional_note":"n","tags":["x"],'
                    '"child":{"value":"ok"},"priority":"low"}'
                )
            )
        ],
    )
    result = client.chat_typed(
        tier="fast",
        messages=[{"role": "user", "content": "extraia"}],
        response_model=Parent,
    )

    assert result.is_success
    assert client.calls[0]["kwargs"]["reasoning_summary"] == "concise"


def test_chat_typed_returns_refusal_without_retry() -> None:
    client = StubAzureClient(
        api_style=API_STYLE_RESPONSES,
        responses=[_response(content="", refusal="blocked")],
    )
    result = client.chat_typed(
        tier="fast",
        messages=[{"role": "user", "content": "conteúdo sensível"}],
        response_model=Parent,
        max_retries=2,
    )

    assert result.parsed is None
    assert result.refusal == "blocked"
    assert result.retries == 0
    assert len(client.calls) == 1
