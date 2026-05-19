from __future__ import annotations

from dataclasses import fields, is_dataclass
from types import SimpleNamespace
from typing import Any, get_args, get_origin


def _payload_for_type(tp: Any) -> Any:
    origin = get_origin(tp)
    args = get_args(tp)

    if origin is list:
        return []
    if origin is dict:
        return {}
    if origin is tuple:
        return []
    if origin is set:
        return []
    if origin is not None and args:
        non_none = [arg for arg in args if arg is not type(None)]
        if non_none:
            return _payload_for_type(non_none[0])

    if tp is str:
        return "ok"
    if tp is int:
        return 1
    if tp is float:
        return 1.0
    if tp is bool:
        return True
    if is_dataclass(tp):
        return payload_for_model(tp)
    return "ok"


def payload_for_model(model: type[Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in fields(model):
        if field.name in {"goal", "goal_type", "status"}:
            payload[field.name] = "ok"
            continue
        if field.name in {"evidence", "uncertainties", "warnings", "steps", "sections"}:
            payload[field.name] = []
            continue
        if field.name == "constraints":
            payload[field.name] = []
            continue
        payload[field.name] = _payload_for_type(field.type)
    return payload


class AlwaysSuccessTypedClient:
    is_configured = True

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat_typed(
        self,
        tier: str,
        messages: list[dict[str, str]],
        *,
        response_model: type[Any],
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "tier": tier,
                "messages": list(messages),
                "kwargs": dict(kwargs),
                "response_model": response_model,
            }
        )
        payload = payload_for_model(response_model)
        return SimpleNamespace(parsed=response_model(**payload), refusal=None)
