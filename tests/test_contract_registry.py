from __future__ import annotations

from dataclasses import dataclass

import pytest

from arnaldo.llm import ContractModelRegistry


@dataclass
class ContractA:
    value: str


@dataclass
class ContractB:
    count: int


def test_register_and_resolve_contract_model() -> None:
    reg = ContractModelRegistry()
    key = reg.register(ContractA)
    assert key == "ContractA"
    assert reg.resolve("ContractA") is ContractA
    assert reg.has("ContractA")


def test_register_with_custom_name() -> None:
    reg = ContractModelRegistry()
    reg.register(ContractA, name="intent_frame_v1")
    assert reg.resolve("intent_frame_v1") is ContractA


def test_register_collision_raises() -> None:
    reg = ContractModelRegistry()
    reg.register(ContractA, name="shared")
    with pytest.raises(ValueError):
        reg.register(ContractB, name="shared")


def test_register_non_dataclass_raises() -> None:
    reg = ContractModelRegistry()

    class NotDataclass:
        pass

    with pytest.raises(TypeError):
        reg.register(NotDataclass)


def test_register_many_supports_dict_and_list() -> None:
    reg = ContractModelRegistry()
    reg.register_many({"a": ContractA})
    reg.register_many([ContractB])
    assert reg.resolve("a") is ContractA
    assert reg.resolve("ContractB") is ContractB

