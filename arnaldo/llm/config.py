"""Configuration loader for Azure OpenAI tiers (stdlib only)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


# Constantes de tier
GOD = "god"  # gpt-5-pro     — raciocínio profundo
EXPERT = "expert"  # gpt-5         — síntese e análise
FAST = "fast"  # gpt-5.4-nano  — extração e formatação
CODEX = "codex"  # gpt-5.3-codex — geração de código (com reasoning effort)

# Estilos de API Azure OpenAI
API_STYLE_DEPLOYMENTS = "deployments"  # URL: /openai/deployments/<name>/chat/completions
API_STYLE_V1 = "v1"  # URL: <base>/chat/completions, model no body
API_STYLE_RESPONSES = "responses"  # URL: <base>/responses (Responses API com reasoning)


def _load_dotenv(path: Path = Path(".env"), override: bool = True) -> None:
    """Carrega variáveis de .env sem dependências externas.

    Args:
        path: caminho do .env (default: ./.env)
        override: se True (padrão), .env sobrescreve env vars existentes.
                  Isso é diferente do comportamento clássico (env > .env), mas
                  faz sentido no Arnaldo: .env é o source of truth do projeto e
                  não deve ser corrompido por env vars residuais de outros projetos.

    Para desabilitar override, defina ARNALDO_RESPECT_ENV=true antes do import.
    """
    if not path.exists():
        return
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return

    # Permite que o usuário force comportamento clássico (env > .env)
    if os.environ.get("ARNALDO_RESPECT_ENV", "").strip().lower() in {"1", "true", "yes"}:
        override = False

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


# Auto-load on import (.env tem precedência por default)
_load_dotenv()


@dataclass(frozen=True)
class TierConfig:
    """Configuração de um tier do roteador LLM.

    Suporta dois estilos de API Azure OpenAI:
    - "deployments": URL inclui o nome do deployment
    - "v1": URL base inclui /openai/v1, model vai no body
    """

    name: str
    model: str  # deployment name (deployments style) ou model name (v1 style)
    description: str
    api_style: str = API_STYLE_DEPLOYMENTS
    base_url: Optional[str] = None  # override do endpoint default
    api_version: Optional[str] = None  # override da api_version global (None = usa default)
    api_key: Optional[str] = None  # override da api_key global (recursos Azure diferentes)
    default_temperature: float = 0.7
    default_max_tokens: int = 2000
    supports_reasoning: bool = False
    default_reasoning_effort: Optional[str] = None  # "low" | "medium" | "high" | "xhigh"
    default_reasoning_summary: Optional[str] = None  # "auto" | "concise" | "detailed"
    uses_max_completion_tokens: bool = (
        False  # gpt-5 series usa max_completion_tokens, não max_tokens
    )


@dataclass(frozen=True)
class AzureOpenAIConfig:
    """Configuração agregada de Azure OpenAI."""

    endpoint: str
    api_key: str
    api_version: str
    tiers: Dict[str, TierConfig] = field(default_factory=dict)
    timeout_seconds: float = 120.0
    max_tokens_default: int = 2000
    enabled: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint) and bool(self.api_key) and self.enabled

    def tier(self, name: str) -> TierConfig:
        tier = self.tiers.get(name)
        if tier is None:
            available = list(self.tiers.keys())
            raise ValueError(f"Tier '{name}' não configurado. Disponíveis: {available}")
        return tier


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional(name: str) -> Optional[str]:
    """Retorna a env var, ou None se vazia/ausente."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip()


def _env_first(*names: str) -> Optional[str]:
    """Retorna a primeira env var não-vazia dentre vários aliases."""
    for name in names:
        value = _env_optional(name)
        if value:
            return value
    return None


def load_config() -> AzureOpenAIConfig:
    """Lê configuração completa de variáveis de ambiente.

    Fluxo simples recomendado:
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_MODEL (ou AZURE_OPENAI_DEPLOYMENT)

    Com isso, GOD/EXPERT/FAST compartilham o mesmo modelo/deployment.
    Se o endpoint for /openai/v1, CODEX também pode reutilizar a mesma base.

    Fluxo avançado opcional:
    - overrides por tier (AZURE_TIER_GOD_DEPLOYMENT, ...)
    - CODEX em base separada (AZURE_CODEX_BASE_URL / AZURE_CODEX_API_KEY)

    Detecção de api_style:
    - Endpoint inclui '/openai/v1' → tiers usam api_style=responses (Foundry Project)
    - Senão → api_style=deployments (compatibilidade com endpoints legados)
    """
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")

    # Detecta estilo da API:
    # - Se endpoint termina com /openai/v1 (com ou sem /api/projects/...) → Responses API
    # - Caso contrário (cognitive services puro) → Deployments
    is_v1_endpoint = "/openai/v1" in endpoint
    tier_api_style = API_STYLE_RESPONSES if is_v1_endpoint else API_STYLE_DEPLOYMENTS
    tier_base_url = endpoint if is_v1_endpoint else None
    shared_model = _env_first("AZURE_OPENAI_MODEL", "AZURE_OPENAI_DEPLOYMENT")

    # Tiers de raciocínio (GOD/EXPERT) consomem ~200 reasoning_tokens internos
    # antes de gerar output, então max_output_tokens precisa ser grande o bastante
    tiers: Dict[str, TierConfig] = {
        GOD: TierConfig(
            name=GOD,
            model=_env_first("AZURE_TIER_GOD_DEPLOYMENT") or shared_model or "god-tier",
            description="gpt-5-pro — raciocínio profundo, planejamento, síntese complexa",
            api_style=tier_api_style,
            base_url=tier_base_url,
            default_temperature=1.0,
            default_max_tokens=8000,  # ~200 reasoning + espaço para output substancial
            supports_reasoning=is_v1_endpoint,  # só se endpoint suporta Responses
            default_reasoning_effort="high" if is_v1_endpoint else None,
            default_reasoning_summary="auto" if is_v1_endpoint else None,
        ),
        EXPERT: TierConfig(
            name=EXPERT,
            model=_env_first("AZURE_TIER_EXPERT_DEPLOYMENT") or shared_model or "expert-tier",
            description="gpt-5 — síntese e análise padrão, drafting de artefatos",
            api_style=tier_api_style,
            base_url=tier_base_url,
            default_temperature=1.0,
            default_max_tokens=4000,  # reasoning + output de tamanho médio
            supports_reasoning=is_v1_endpoint,
            default_reasoning_effort="medium" if is_v1_endpoint else None,
            default_reasoning_summary="auto" if is_v1_endpoint else None,
        ),
        FAST: TierConfig(
            name=FAST,
            model=_env_first("AZURE_TIER_FAST_DEPLOYMENT") or shared_model or "fast-tier",
            description="gpt-5.4-nano — extração, formatação, classificação rápida (sem reasoning)",
            api_style=tier_api_style,
            base_url=tier_base_url,
            default_temperature=1.0,
            default_max_tokens=1500,
            supports_reasoning=False,  # nano não faz reasoning
        ),
    }

    # Registra CODEX quando explicitamente configurado ou quando o endpoint
    # simples já é Responses API e pode reutilizar a mesma base/modelo.
    codex_base_url = _env_optional("AZURE_CODEX_BASE_URL")
    reuse_primary_for_codex = bool(is_v1_endpoint and shared_model)
    if codex_base_url or reuse_primary_for_codex:
        tiers[CODEX] = TierConfig(
            name=CODEX,
            model=_env_first("AZURE_CODEX_DEPLOYMENT") or shared_model or "gpt-5.3-codex",
            description="gpt-5.3-codex — geração de código via Responses API com reasoning effort",
            api_style=API_STYLE_RESPONSES,
            base_url=(codex_base_url or endpoint).rstrip("/"),
            api_version=_env_optional("AZURE_CODEX_API_VERSION"),
            # Recurso Codex pode ter chave separada da Foundry Project
            api_key=_env_optional("AZURE_CODEX_API_KEY") or api_key,
            default_temperature=1.0,
            default_max_tokens=4000,
            supports_reasoning=True,
            default_reasoning_effort=_env_optional("AZURE_CODEX_REASONING_EFFORT") or "xhigh",
            default_reasoning_summary=_env_optional("AZURE_CODEX_REASONING_SUMMARY") or "auto",
            uses_max_completion_tokens=False,
        )

    return AzureOpenAIConfig(
        endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
        tiers=tiers,
        timeout_seconds=_env_float("ARNALDO_LLM_TIMEOUT_SECONDS", 120.0),
        max_tokens_default=_env_int("ARNALDO_LLM_MAX_TOKENS_DEFAULT", 2000),
        enabled=_env_bool("ARNALDO_LLM_ENABLED", True),
    )
