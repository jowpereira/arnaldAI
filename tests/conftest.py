"""Fixtures compartilhadas para testes do ArnaldAI."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.support_llm import AlwaysSuccessTypedClient


@pytest.fixture
def tmp_dir():
    """Diretório temporário para testes."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def tmp_generated_dir(tmp_dir: Path) -> Path:
    """Diretório 'generated' dentro de tmp para testes de tooling."""
    gen = tmp_dir / "generated"
    gen.mkdir()
    return gen


@pytest.fixture
def tmp_tool_forge_dir(tmp_dir: Path) -> Path:
    """Diretório 'tool_forge' dentro de tmp para testes de ToolForge."""
    forge = tmp_dir / "tool_forge"
    forge.mkdir()
    return forge


@pytest.fixture
def fake_llm_client() -> AlwaysSuccessTypedClient:
    """Client LLM fake que sempre retorna sucesso."""
    return AlwaysSuccessTypedClient()
