---
name: arnaldo-context
description: 'Contexto técnico completo do ArnaldAI — substrate cognitivo simbólico, arquitetura do grafo, pipeline do kernel, camada LLM e comandos essenciais. Use em qualquer tarefa que exija entender o projeto antes de agir.'
---

# Skill: Contexto do ArnaldAI

## Identidade

- **Nome:** ArnaldAI
- **Versão:** 0.2.0
- **Propósito:** Kernel cognitivo simbólico — grafo único, vivo e auditável onde memórias, agentes e ferramentas co-existem como nós persistentes ligados por arestas tipadas com plasticidade Hebbian. Cada nó pode possuir ou referenciar outros grafos, formando uma hierarquia composicional.
- **Stack:** Python 3.12+ (uv), NetworkX, NumPy, msgpack
- **LLM:** Azure OpenAI direto (stdlib-only, urllib + json, sem SDKs)

## Arquitetura

```
┌────────────────────────────────────────────────────────────────────┐
│                       CAMADA 0: ENTRADA                             │
│   CLI · API Python · (futuro: MCP/A2A servers)                      │
├────────────────────────────────────────────────────────────────────┤
│                  CAMADA 1: COMPILAÇÃO DECLARATIVA                   │
│   IntentCompiler → TaskCompiler → CognitiveControlPlane            │
│   (tier LLM apropriado + fallback heurístico garantido)            │
├────────────────────────────────────────────────────────────────────┤
│                CAMADA 2: SUBSTRATE COGNITIVO                        │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │              CognitiveGraph (substrate vivo)             │    │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────┐         │    │
│   │  │MemoryNode  │  │SynapseNode │  │CapabilityNode        │    │
│   │  └────────────┘  └────────────┘  └────────────┘         │    │
│   │   arestas tipadas + plasticidade Hebbian                 │    │
│   │   GraphRef → outros CognitiveGraphs (hierarquia)         │    │
│   └──────────────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────────────────┤
│                  CAMADA 3: SÍNTESE DE ATIVAÇÃO                      │
│   PatternMatcher → ActivationPattern → execução                    │
├────────────────────────────────────────────────────────────────────┤
│                     CAMADA 4: EXECUÇÃO                              │
│   RuntimeAdapter + Sandbox + PolicyEngine                          │
├────────────────────────────────────────────────────────────────────┤
│                CAMADA 5: VERIFICAÇÃO E EVOLUÇÃO                     │
│   EvidenceLedger · PlasticityEngine.record_outcome_recursive       │
├────────────────────────────────────────────────────────────────────┤
│                CAMADA 6: EPISTEME (foragem ativa, Fase 4)           │
│   GapAnalyzer · CuriosityEngine · WebForager                       │
└────────────────────────────────────────────────────────────────────┘
```

## Estrutura do Código

```
arnaldo/
├── __init__.py
├── __main__.py              ← Entry point (python -m arnaldo)
├── cli.py                   ← CLI com streaming ao vivo
├── core.py                  ← Funções core de alto nível
├── kernel.py                ← Kernel principal (pipeline compile→match→execute)
├── components/
│   ├── adaptive_planner.py  ← Planejador adaptativo
│   ├── capability_registry.py ← Registro de capabilities
│   ├── cognitive_control.py ← Plano cognitivo (CognitiveControlPlane)
│   ├── intent_compiler.py   ← Compilador de intenção (LLM + heurística)
│   ├── organization_generator.py ← Gerador de organização
│   ├── policy_engine.py     ← Motor de políticas
│   ├── task_compiler.py     ← Compilador de tarefas
│   └── tool_forge.py        ← Forja de ferramentas dinâmicas
├── contracts/
│   └── ir.py                ← Representação intermediária (IR)
├── graph/
│   ├── edges.py             ← EdgeKind + arestas tipadas
│   ├── execution.py         ← Engine de execução de grafo
│   ├── matching.py          ← PatternMatcher (ativação)
│   ├── nodes.py             ← NodeKind + nós tipados
│   ├── plasticity.py        ← Plasticidade Hebbian + decay
│   ├── provenance.py        ← SourceRecord + proveniência epistêmica
│   ├── refs.py              ← GraphRef (hierarquia de grafos)
│   ├── store.py             ← CognitiveGraph (substrato principal)
│   ├── temporal.py          ← Modelo bi-temporal (T, T′)
│   └── workflows.py         ← Workflows como objetos de primeira classe
├── llm/
│   ├── client.py            ← AzureOpenAIClient (stdlib-only)
│   ├── config.py            ← TierConfig + load_config()
│   ├── contracts.py         ← ContractModelRegistry
│   ├── router.py            ← TASK_TIER_MAP (task → tier)
│   └── structured.py        ← dataclass_to_schema + chat_typed
├── memory/
│   └── store.py             ← MemoryStore (ledger + memory-graph)
├── proactivity/
│   └── manager.py           ← Motor de proatividade
├── reality/
│   └── gap.py               ← RealityGapDetector
├── runtime/
│   ├── base.py              ← RuntimeAdapter (interface)
│   ├── graph_runtime.py     ← GraphRuntime (execução em grafo)
│   ├── local.py             ← LocalRuntime
│   ├── multiagent.py        ← MultiAgentRuntime
│   └── sandbox.py           ← Sandbox de execução
├── session/
│   └── manager.py           ← Gerenciador de sessão
└── storage/
    └── run_store.py          ← Persistência de runs
```

## LLM — 4 Tiers

| Tier      | Modelo            | Uso                                    |
|-----------|-------------------|----------------------------------------|
| **GOD**   | gpt-5-pro         | Raciocínio profundo, planejamento      |
| **EXPERT**| gpt-5             | Síntese e análise, drafting            |
| **FAST**  | gpt-5.4-nano      | Extração, classificação               |
| **CODEX** | gpt-5.3-codex     | Geração de código com reasoning effort |

Configuração via `.env` (nunca commitado). Validação: `docs/operations.md § 2.3`.

## Os Sete Invariantes

1. **Tipagem** — Todo nó tem `kind ∈ NodeKind`; toda aresta tem `kind ∈ EdgeKind`
2. **Proveniência** — Todo nó e toda aresta carregam `SourceRecord` não-vazio
3. **Bi-temporal** — Toda relação carrega `(T, T′)`
4. **Plasticidade** — Pesos `∈ [floor, ceiling] ⊂ [0,1]`, `|Δw| ≤ cap_per_step`
5. **Decay tipado** — Half-life por domain, nunca uniforme
6. **Auditabilidade** — Toda mutação gera `GraphEvent` persistível
7. **DAG hierarquia** — `GraphRef` forma DAG; ciclos → `GraphCycleError`

## Comandos Essenciais

```bash
# Setup
uv venv --python 3.12
uv sync --extra dev

# Testes
uv run pytest -x -v                          # todos
uv run pytest tests/test_graph.py -v          # específico
uv run pytest --cov=arnaldo                   # cobertura

# Linting
uv run ruff check arnaldo/ tests/
uv run ruff format arnaldo/ tests/

# Type checking
uv run mypy arnaldo/

# CLI
uv run python -m arnaldo "Crie um plano B2B" --autonomy autonomo

# Validar LLM
uv run python -c "
from arnaldo.llm import load_config, AzureOpenAIClient, FAST
client = AzureOpenAIClient()
r = client.chat(tier=FAST, messages=[{'role':'user','content':'oi'}])
print(f'✅ usage={r.usage}')
"
```

## Documentação Canônica

| Doc | Conteúdo |
|-----|----------|
| `README.md` | Visão geral, quickstart, posicionamento |
| `docs/architecture.md` | Especificação formal completa (invariantes, modelo bi-temporal, plasticidade, etc.) |
| `docs/operations.md` | Setup, configuração LLM, storage, troubleshooting |
| `docs/backlog-mestre.md` | Backlog detalhado com status por trilha |
| `CHANGELOG.md` | Histórico de versões (semver) |
