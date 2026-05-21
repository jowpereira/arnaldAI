---
applyTo: "arnaldo/llm/**/*.py"
description: "Padrões da camada LLM do ArnaldAI — stdlib-only, 4 tiers, sem SDKs"
---

# Camada LLM — Padrões Obrigatórios

A camada LLM do ArnaldAI é **stdlib-only**. Esta é uma decisão arquitetural inviolável.

## Regra Cardinal: stdlib-only

```python
# ✅ PERMITIDO — apenas stdlib
import json
import urllib.request
import urllib.error
import os

# ❌ PROIBIDO — qualquer SDK de terceiros
# import openai
# import httpx
# import requests
# import aiohttp
# from azure.ai import ...
# from langchain import ...
```

A única dependência permitida nesta camada é a **stdlib do Python**. Sem exceção.

## Arquitetura: 4 Tiers

| Tier | Uso | Modelo típico |
|------|-----|---------------|
| `GOD` | Tarefas críticas, planejamento estratégico | GPT-4o, Claude Opus |
| `EXPERT` | Análise, síntese, código complexo | GPT-4o-mini |
| `FAST` | Classificação, extração, tarefas rápidas | GPT-4o-mini |
| `CODEX` | Geração/revisão de código | GPT-4o |

## Roteamento

```python
# arnaldo/llm/router.py — TASK_TIER_MAP
# Toda task nova DEVE ser mapeada para um tier
# Se não mapeada, o roteador DEVE usar FAST como fallback seguro
```

## Contratos

```python
# arnaldo/llm/contracts.py — LLMRequest, LLMResponse
# SEMPRE usar os contratos tipados — nunca dicts crus
# SEMPRE incluir model_tier no request
# SEMPRE retornar LLMResponse com usage tracking
```

## Structured Output

```python
# arnaldo/llm/structured.py
# Azure OpenAI strict mode:
# - Campos opcionais DEVEM ter default (None ou valor)
# - JSON Schema gerado deve ser válido para strict=true
# - Testar schema com test_structured.py antes de deploy
```

## Fallback Heurístico

```python
# REGRA: Estrutura antes de LLM
# Se LLM falha (timeout, rate limit, erro):
# 1. NÃO relançar exceção cegamente
# 2. Tentar heurística determinística (IntentCompiler, TaskCompiler)
# 3. Retornar IR válido com confidence degradada
# 4. Registrar fallback em GraphEvent
```

## Configuração

```python
# arnaldo/llm/config.py
# NUNCA hardcodar:
# - API keys → .env (AZURE_OPENAI_API_KEY)
# - Endpoints → .env (AZURE_OPENAI_ENDPOINT)
# - Deployment names → .env ou config
# - Timeouts → constantes nomeadas no módulo
```

## Client HTTP

```python
# arnaldo/llm/client.py
# Implementação com urllib.request (NÃO requests/httpx)
# DEVE implementar:
# - Retry com backoff exponencial
# - Timeout configurável
# - Headers de autenticação via Bearer token
# - Parsing de resposta com json.loads
# - Tratamento de HTTP 429 (rate limit)
```

## Erros Comuns

- Importar SDK de terceiros (openai, httpx, requests) → viola stdlib-only
- Não mapear task nova em TASK_TIER_MAP → roteamento incorreto
- Campo opcional sem default em structured output → Azure rejeita schema
- Não tratar 429 → cascata de falhas em rate limit
- .env não carregado → client falha silenciosamente com auth error
