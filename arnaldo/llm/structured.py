"""Utilities para structured outputs (dataclass ↔ JSON Schema strict)."""

from __future__ import annotations

import dataclasses as dc
from dataclasses import dataclass
from enum import Enum
import types
import typing as t
from typing import Any, Generic, TypeVar, get_args, get_origin

T = TypeVar("T")


@dataclass(slots=True)
class TypedResponse(Generic[T]):
    """Envelope discriminado para chamadas tipadas."""

    parsed: T | None
    refusal: str | None
    raw: Any
    schema_used: dict[str, Any]
    retries: int = 0

    @property
    def is_success(self) -> bool:
        return self.parsed is not None and self.refusal is None


def dataclass_to_schema(cls: type[Any], *, strict: bool = True) -> dict[str, Any]:
    """Converte uma dataclass em JSON Schema."""
    if not dc.is_dataclass(cls):
        raise TypeError(f"{cls!r} não é dataclass")

    type_hints = t.get_type_hints(cls, include_extras=True)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for field in dc.fields(cls):
        field_type = type_hints.get(field.name, Any)
        properties[field.name] = _python_type_to_json_schema(field_type, strict=strict)
        if strict:
            required.append(field.name)
        elif field.default is dc.MISSING and field.default_factory is dc.MISSING:
            required.append(field.name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
    }
    if strict:
        schema["additionalProperties"] = False
    return schema


def build_response_format_for_style(
    schema: dict[str, Any],
    *,
    name: str,
    api_style: str,
) -> dict[str, Any]:
    """Monta o bloco de `response_format` conforme o estilo de API."""
    if api_style == "responses":
        return {
            "type": "json_schema",
            "name": name,
            "schema": schema,
            "strict": True,
        }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": schema,
            "strict": True,
        },
    }


def instantiate_dataclass(cls: type[T], data: dict[str, Any]) -> T:
    """Reconstrói uma instância de dataclass a partir de um dict."""
    if not dc.is_dataclass(cls):
        raise TypeError(f"{cls!r} não é dataclass")
    if not isinstance(data, dict):
        raise TypeError("payload JSON deve ser objeto (dict)")

    type_hints = t.get_type_hints(cls, include_extras=True)
    kwargs: dict[str, Any] = {}
    for field in dc.fields(cls):
        if field.name not in data:
            continue
        target_type = type_hints.get(field.name, Any)
        kwargs[field.name] = _coerce_value(data[field.name], target_type)
    return cls(**kwargs)


def _python_type_to_json_schema(tp: Any, *, strict: bool) -> dict[str, Any]:
    origin = get_origin(tp)
    args = get_args(tp)

    # Annotated[T, ...] -> T
    if origin is t.Annotated:
        return _python_type_to_json_schema(args[0], strict=strict)

    # Literal["a", "b"] -> enum
    if origin is t.Literal:
        values = list(args)
        schema: dict[str, Any] = {"enum": values}
        literal_types = {type(v) for v in values}
        if literal_types == {str}:
            schema["type"] = "string"
        elif literal_types <= {int}:
            schema["type"] = "integer"
        elif literal_types <= {int, float}:
            schema["type"] = "number"
        elif literal_types == {bool}:
            schema["type"] = "boolean"
        return schema

    # Union / Optional
    if origin in (t.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        has_none = len(non_none) != len(args)
        if len(non_none) == 1:
            schema = _python_type_to_json_schema(non_none[0], strict=strict)
            if has_none:
                return _nullable_schema(schema)
            return schema

        union_branches = [_python_type_to_json_schema(a, strict=strict) for a in non_none]
        if has_none:
            union_branches.append({"type": "null"})
        return {"anyOf": union_branches}

    # Coleções
    if origin in (list, t.List, tuple, set, frozenset):
        item_type = args[0] if args else str
        return {
            "type": "array",
            "items": _python_type_to_json_schema(item_type, strict=strict),
        }

    if origin in (dict, t.Dict):
        key_type = args[0] if len(args) >= 1 else str
        value_type = args[1] if len(args) >= 2 else Any
        if key_type not in (str, Any):
            raise TypeError("apenas Dict[str, X] é suportado em output estruturado")
        value_schema = _python_type_to_json_schema(value_type, strict=strict)
        return {
            "type": "object",
            "additionalProperties": value_schema,
        }

    # Dataclass aninhada
    if isinstance(tp, type) and dc.is_dataclass(tp):
        return dataclass_to_schema(tp, strict=strict)

    # Enum
    if isinstance(tp, type) and issubclass(tp, Enum):
        values = [member.value for member in tp]
        schema = {"enum": values}
        value_types = {type(v) for v in values}
        if value_types == {str}:
            schema["type"] = "string"
        elif value_types <= {int}:
            schema["type"] = "integer"
        elif value_types <= {int, float}:
            schema["type"] = "number"
        elif value_types == {bool}:
            schema["type"] = "boolean"
        return schema

    # Primitivos
    primitive_map: dict[Any, dict[str, Any]] = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
    }
    if tp in primitive_map:
        return dict(primitive_map[tp])

    # Tipo desconhecido: default conservador
    return {"type": "string"}


def _nullable_schema(schema: dict[str, Any]) -> dict[str, Any]:
    out = dict(schema)
    schema_type = out.get("type")
    if isinstance(schema_type, str):
        out["type"] = [schema_type, "null"]
        return out
    if isinstance(schema_type, list):
        if "null" not in schema_type:
            out["type"] = [*schema_type, "null"]
        return out

    any_of = list(out.get("anyOf", []))
    any_of.append({"type": "null"})
    out["anyOf"] = any_of
    return out


def _coerce_value(value: Any, target_type: Any) -> Any:
    if target_type is Any:
        return value

    origin = get_origin(target_type)
    args = get_args(target_type)

    # Annotated[T, ...] -> T
    if origin is t.Annotated:
        return _coerce_value(value, args[0])

    if value is None:
        if _allows_none(target_type):
            return None
        raise TypeError(f"campo não permite null: {target_type}")

    if origin is t.Literal:
        if value in args:
            return value
        raise TypeError(f"valor fora de Literal: {value!r}")

    if origin in (t.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        errors: list[Exception] = []
        for branch in non_none:
            try:
                return _coerce_value(value, branch)
            except (TypeError, ValueError) as exc:
                errors.append(exc)
        raise TypeError(f"valor {value!r} não casa com Union {non_none!r}: {errors}")

    if isinstance(target_type, type) and dc.is_dataclass(target_type):
        if not isinstance(value, dict):
            raise TypeError("dataclass aninhada espera dict")
        return instantiate_dataclass(target_type, value)

    if isinstance(target_type, type) and issubclass(target_type, Enum):
        return target_type(value)

    if origin in (list, t.List):
        if not isinstance(value, list):
            raise TypeError("lista esperada")
        item_type = args[0] if args else Any
        return [_coerce_value(item, item_type) for item in value]

    if origin is tuple:
        if not isinstance(value, list):
            raise TypeError("tupla espera lista JSON")
        item_type = args[0] if args else Any
        return tuple(_coerce_value(item, item_type) for item in value)

    if origin in (dict, t.Dict):
        if not isinstance(value, dict):
            raise TypeError("dict esperado")
        key_type = args[0] if len(args) >= 1 else str
        value_type = args[1] if len(args) >= 2 else Any
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if key_type in (Any, str):
                coerced_key = str(k)
            else:
                coerced_key = key_type(k)
            out[coerced_key] = _coerce_value(v, value_type)
        return out

    if target_type is str:
        if not isinstance(value, str):
            raise TypeError("string esperada")
        return value
    if target_type is bool:
        if not isinstance(value, bool):
            raise TypeError("bool esperado")
        return value
    if target_type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("int esperado")
        return value
    if target_type is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("float esperado")
        return float(value)

    return value


def _allows_none(tp: Any) -> bool:
    origin = get_origin(tp)
    if origin in (t.Union, types.UnionType):
        return any(arg is type(None) for arg in get_args(tp))
    return False
