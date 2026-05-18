"""LLM integration layer for Arnaldo.

Public surface:
- load_config() / AzureOpenAIConfig / TierConfig: configuração de tiers
- AzureOpenAIClient: cliente HTTP stdlib-only para Azure OpenAI
- LLMResponse: envelope tipado para resposta
- tier_for_task(): roteamento task → tier
- GOD / EXPERT / FAST: constantes de tier
"""
from __future__ import annotations

from .config import (
    AzureOpenAIConfig,
    TierConfig,
    load_config,
    GOD,
    EXPERT,
    FAST,
    CODEX,
    API_STYLE_DEPLOYMENTS,
    API_STYLE_V1,
    API_STYLE_RESPONSES,
)
from .client import AzureOpenAIClient, LLMResponse, LLMError
from .contracts import ContractModelRegistry, DEFAULT_CONTRACT_REGISTRY
from .router import tier_for_task, TASK_TIER_MAP
from .structured import TypedResponse, dataclass_to_schema

__all__ = [
    "AzureOpenAIConfig",
    "TierConfig",
    "load_config",
    "AzureOpenAIClient",
    "LLMResponse",
    "LLMError",
    "ContractModelRegistry",
    "DEFAULT_CONTRACT_REGISTRY",
    "TypedResponse",
    "dataclass_to_schema",
    "tier_for_task",
    "TASK_TIER_MAP",
    "GOD",
    "EXPERT",
    "FAST",
    "CODEX",
    "API_STYLE_DEPLOYMENTS",
    "API_STYLE_V1",
    "API_STYLE_RESPONSES",
]
