# ◉ Arnaldo — Operações

> Guia operacional. Documenta setup, configuração de LLM, estrutura de
> storage, troubleshooting e referência da CLI. Para fundamentos teóricos e
> formais, consulte [`architecture.md`](architecture.md).

---

## Sumário

1. [Setup](#1-setup)
2. [Configuração Azure OpenAI (4 tiers)](#2-configuração-azure-openai-4-tiers)
3. [Execução](#3-execução)
4. [Estrutura de storage](#4-estrutura-de-storage)
5. [Testes](#5-testes)
6. [Custo e observabilidade](#6-custo-e-observabilidade)
7. [Troubleshooting](#7-troubleshooting)
8. [API Python — exemplos canônicos](#8-api-python--exemplos-canônicos)
9. [Frontend e dashboard de observabilidade](#9-frontend-e-dashboard-de-observabilidade)

---

## 1. Setup

### 1.1 Requisitos

- **Python 3.12+**
- **uv** (gerenciador de pacotes Python — substitui pip/poetry/virtualenv)
- Acesso a um recurso **Azure OpenAI Foundry** com deployments
  `god-tier`, `expert-tier`, `fast-tier` (opcional: `gpt-5.3-codex` em
  recurso separado)

### 1.2 Instalação

```bash
# 1. uv (se ainda não instalado)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Python 3.12 via uv
uv python install 3.12

# 3. Clonar e criar venv
cd /caminho/para/autoagent
uv venv --python 3.12
uv sync --extra dev          # inclui pytest, ruff, mypy
```

### 1.3 Dependências

```
Core:
  networkx >= 3.2   — grafo (multidigrafo tipado)
  numpy    >= 1.24  — vetores e similaridade
  msgpack  >= 1.0   — serialização binária do grafo

Optional extras:
  embeddings:       sentence-transformers
  graph-backends:   neo4j, falkordb
  foraging:         httpx, beautifulsoup4, lxml
  dev:              pytest, mypy, ruff
```

A camada LLM em `arnaldo/llm/` é **stdlib-only** (urllib + json).
Sem dependências extras para falar com Azure OpenAI.

---

## 2. Configuração Azure OpenAI (4 tiers)

### 2.1 Arquivo `.env`

Copie `.env.example` para `.env` e preencha com seus valores:

```bash
# ─── Endpoint 1: Foundry Project (god/expert/fast via Responses API) ───
AZURE_OPENAI_ENDPOINT=https://<recurso>.services.ai.azure.com/api/projects/<project>/openai/v1
AZURE_OPENAI_API_KEY=<chave-do-project>
AZURE_OPENAI_API_VERSION=2025-04-01-preview

AZURE_TIER_GOD_DEPLOYMENT=god-tier
AZURE_TIER_EXPERT_DEPLOYMENT=expert-tier
AZURE_TIER_FAST_DEPLOYMENT=fast-tier

# ─── Endpoint 2: Codex (recurso separado, pode ter chave diferente) ───
AZURE_CODEX_BASE_URL=https://<codex-recurso>.services.ai.azure.com/api/projects/<codex-project>/openai/v1
AZURE_CODEX_DEPLOYMENT=gpt-5.3-codex
AZURE_CODEX_REASONING_EFFORT=xhigh
AZURE_CODEX_REASONING_SUMMARY=auto
AZURE_CODEX_API_KEY=<chave-do-codex>     # se diferente da global

# ─── Comportamento ────────────────────────────────────────────────────
ARNALDO_LLM_ENABLED=true
ARNALDO_LLM_TIMEOUT_SECONDS=120
ARNALDO_LLM_MAX_TOKENS_DEFAULT=2000

# Default: .env tem precedência sobre env vars do shell.
# Para reverter ao comportamento clássico (env > .env):
# ARNALDO_RESPECT_ENV=true
```

`.env` está no `.gitignore`. **Nunca commitar.**

### 2.2 Os 4 tiers

| Tier      | Modelo            | Uso                                    | Reasoning |
|-----------|-------------------|----------------------------------------|-----------|
| **GOD**   | gpt-5-pro         | raciocínio profundo, planejamento      | ~256 tok  |
| **EXPERT**| gpt-5             | síntese e análise, drafting            | ~128 tok  |
| **FAST**  | gpt-5.4-nano      | extração, classificação                | 0         |
| **CODEX** | gpt-5.3-codex     | geração de código com reasoning effort | ~120 tok  |

Modelos com reasoning consomem tokens internos **antes** de gerar output.
Dimensione `max_output_tokens` com folga:

```
GOD    → 8000
EXPERT → 4000
CODEX  → 4000
FAST   → 1500
```

### 2.3 Validar a configuração

```bash
uv run python -c "
from arnaldo.llm import load_config, AzureOpenAIClient, GOD, EXPERT, FAST, CODEX

config = load_config()
client = AzureOpenAIClient()
for t in [FAST, EXPERT, GOD, CODEX]:
    if t not in config.tiers:
        continue
    try:
        r = client.chat(tier=t, messages=[{'role':'user','content':'oi'}])
        print(f'[{t:6}] ✅ usage={r.usage}')
    except Exception as e:
        print(f'[{t:6}] ❌ {e}')
"
```

### 2.4 Roteamento task → tier

```python
from arnaldo.llm import tier_for_task

tier_for_task("intent.compile")           # → "expert"
tier_for_task("task.plan_complex")        # → "god"
tier_for_task("intent.extract_signals")   # → "fast"
tier_for_task("tool_forge.generate_connector")  # → "codex"
tier_for_task("unknown.task")             # → "expert" (default)

# Override
tier_for_task("intent.compile", override="god")
```

Mapa completo em `arnaldo/llm/router.py:TASK_TIER_MAP`.

### 2.5 Três estilos de API suportados

| Estilo          | URL pattern                                          | Body inclui `model`? |
|-----------------|------------------------------------------------------|----------------------|
| `deployments`   | `{endpoint}/openai/deployments/<dep>/chat/completions` | Não — deployment na URL |
| `v1`            | `{base}/chat/completions`                            | Sim                  |
| `responses`     | `{base}/responses`                                   | Sim (Responses API) |

Detecção automática por presença de `/openai/v1` no endpoint. Para tiers
custom, defina em `TierConfig.api_style`.

### 2.6 Fallback heurístico

Princípio: **se qualquer tier falhar, o kernel continua** com fallback
determinístico:

```python
try:
    enrichment = self._llm_client.chat_typed(...)
except (LLMError, RuntimeError, ValueError):
    return None  # heurístico mantém o resultado
```

### 2.7 Structured outputs (`response_format`)

Para saídas estruturadas em produção, prefira `chat_typed()` com dataclass.
O cliente converte automaticamente o tipo para JSON Schema strict e aplica o
envelope correto por `api_style`:

- `deployments`/`v1`: `response_format={"type":"json_schema",...}`
- `responses`: `text.format={"type":"json_schema",...}`

`chat_json()` segue disponível apenas para compatibilidade transitória
(`json_object` + validação client-side), mas sem contrato tipado enforced.

---

## 3. Execução

### 3.1 CLI

```bash
# Run única
uv run python -m arnaldo "Crie um plano para um SaaS B2B"

# Com nível de autonomia explícito
uv run python -m arnaldo "Analise o mercado de clínicas" --autonomy autonomo

# Sessão contínua (chat multi-turno)
uv run python -m arnaldo --chat --session minha_sessao --autonomy autonomo

# Modo livre com termos aceitos (intervenção mínima)
uv run python -m arnaldo --chat --session livre --autonomy livre --accept-terms

# Diretório de saída custom
uv run python -m arnaldo "Planeje um MVP" --out ./meus_resultados
```

### 3.2 Flags principais

| Flag                | Valor / efeito                                                   |
|---------------------|------------------------------------------------------------------|
| `--autonomy`        | `manual` / `assistido` / `autonomo` / `livre`                    |
| `--session <id>`    | Continuidade entre turnos (carrega `storage/sessions/<id>.json`) |
| `--accept-terms`    | Eleva governance_profile para `self_managed` (menos checkpoints) |
| `--chat`            | Loop interativo                                                  |
| `--out <dir>`       | Diretório onde a run vai ser registrada (default: `runs/`)       |

Notas operacionais:
- A CLI roda em `graph` por padrão e não expõe fallback local.
- Execução é strict-real por natureza: sem `mock`, sem `fallback` e sem toggle por env.
- Se LLM estiver indisponível/recusar/falhar, a run falha explicitamente com diagnóstico.
- Cada run imprime resumo rico no terminal (topologia, contadores, evidências, trace e caminhos de artefatos).
- Para mensagens de saudação/conversa inicial (`oi`, `olá`, etc.), o runtime materializa um workflow leve de 1 etapa no tier `fast` para reduzir latência.

### 3.3 Níveis de autonomia

```
manual (1)      Aprovação manual a cada step.
                Network: disabled. Filesystem: workspace-only.

assistido (2)   Aprovação para efeitos externos.
                Network: read. Filesystem: workspace-only.
                Default da CLI.

autonomo (3)    Aprovação para ações de alto risco.
                Network: read. Filesystem: workspace-only.

livre (6)       Intervenção mínima. Requer --accept-terms.
                Network: read_write. Filesystem: workspace_write.
                External messages: allowed.
                Spend money: blocked_unless_budget_defined.
                Unsafe actions: blocked.
```

---

## 4. Estrutura de storage

### 4.1 Layout completo

```
autoagent/
├── runs/                            # output por execução (gitignored)
│   └── run_<id>/
│       ├── adaptive-plan.json        # plano adaptativo do turno
│       ├── intent-ir.json            # IntentIR compilado
│       ├── task-ir.json              # TaskIR derivado
│       ├── cognitive-decision.json   # modo cognitivo escolhido
│       ├── capability-resolution.json# capacidades disponíveis e missing
│       ├── organization-ir.json      # seed organizacional para runtime
│       │                             #  (workflow pode vir vazio em modo graph)
│       ├── policy-decision.json      # veredito de governança
│       ├── sandbox-state.json        # sandbox provisionado
│       ├── session-state.json        # snapshot da sessão pós-turno
│       ├── tool-forge-report.json    # (opcional) tools geradas
│       ├── graph-capability-sync.json# (opcional) capacidades aprendidas do grafo
│       ├── artifact.md               # ★ artefato principal
│       ├── execution-graph.msgpack   # grafo de execução incremental da sessão
│       ├── trace.jsonl               # eventos do runtime
│       ├── evidence.jsonl            # ledger append-only
│       ├── agent_bus.jsonl           # mensagens entre agentes (vazio hoje)
│       └── result.md                 # resumo
│
├── storage/                          # estado global (gitignored)
│   ├── sessions/
│   │   ├── <session_id>.json         # SessionState
│   │   └── <session_id>.history.jsonl# histórico de turnos
│   │
│   ├── memory/                       # (transição para graph/)
│   │   ├── episodic.jsonl
│   │   ├── semantic.jsonl
│   │   ├── procedural.jsonl
│   │   ├── negative.jsonl
│   │   └── prospective.jsonl
│   │
│   ├── graph/                        # CognitiveGraph persistido
│   │   ├── root.msgpack              # grafo principal
│   │   └── <sub_graph_id>.msgpack    # sub-grafos (GraphRef.uri)
│   │
│   ├── tool_forge/
│   │   ├── generated/
│   │   │   ├── <tool>.py             # scaffolds gerados
│   │   │   └── <tool>.json           # metadados
│   │   └── index.json                # catálogo de tools forjadas
│   │
│   ├── sandboxes/
│   │   └── <run_id>/                 # sandbox por run
│   │       ├── workspace/
│   │       ├── artifacts/
│   │       ├── cache/
│   │       ├── tmp/
│   │       └── sandbox.json          # manifest
│   │
│   └── capability_registry.json      # capabilities dinâmicas
│
├── tests/                            # 90+ testes
└── docs/                             # 3 documentos canônicos
    ├── architecture.md
    └── operations.md (este)
```

No runtime `graph`, o kernel salva em `learned_preferences.execution_graph_uri`
o caminho do último `execution-graph.msgpack`, permitindo reaproveitar o grafo
de execução no próximo turno da mesma sessão.

### 4.2 Sandbox por run

Cada execução provisiona um sandbox isolado em `storage/sandboxes/<run_id>/`:

```python
SandboxState = {
    "version":        "sandbox/v0",
    "id":             "sandbox_8c2af1...",
    "run_id":         "run_e8a932...",
    "session_id":     "session_3fa67d...",
    "mode":           "managed_guarded" | "managed_open",
    "root_path":      ".../storage/sandboxes/<run_id>",
    "workspace_path": ".../workspace",
    "artifacts_path": ".../artifacts",
    "cache_path":     ".../cache",
    "temp_path":      ".../tmp",
    "network_mode":         "read" | "read_write" | "disabled",
    "filesystem_mode":      "workspace_write" | "write_run_directory_only",
    "allowed_external_messages": false | true,
}
```

⚠️ Atenção: o sandbox atual é **filesystem-based apenas** (provisiona
diretórios + JSON manifest). Não há isolamento de processo/rede em runtime
— enforcement vem da policy. Para deploy multi-tenant em produção, integrar
com Docker/gVisor (não implementado).

### 4.3 Evidence Ledger

Cada run gera `runs/<id>/evidence.jsonl`, append-only:

```json
{"id":"evidence_a1b2","run_id":"run_e8a9","task_id":"task_5d8a","record_type":"request_compiled","summary":"..."}
{"id":"evidence_c3d4","run_id":"run_e8a9","task_id":"task_5d8a","record_type":"step_completed","payload":{...}}
{"id":"evidence_e5f6","run_id":"run_e8a9","task_id":"task_5d8a","record_type":"artifact_created","payload":{...}}
```

Estrutura mínima: `id`, `run_id`, `task_id`, `created_at`, `record_type`,
`summary`, `payload`. Imutável após gravação.

### 4.4 CognitiveGraph persistido

```python
from arnaldo.graph import CognitiveGraph
from pathlib import Path

# Persistir
cog.persist(Path("storage/graph/root.msgpack"))

# Carregar
cog = CognitiveGraph.load(Path("storage/graph/root.msgpack"))

# Com sub-grafos (referenciados via uri):
sub.persist(Path("storage/graph/sub_xyz.msgpack"))
ref = cog.attach_subgraph(
    node_id="syn_abc",
    subgraph=sub,
    kind=GraphRefKind.SHARED,
    uri=Path("storage/graph/sub_xyz.msgpack"),
)
cog.persist(Path("storage/graph/root.msgpack"))

# Em nova sessão, sub-grafo carrega lazy:
cog2 = CognitiveGraph.load(Path("storage/graph/root.msgpack"))
node = cog2.get_node("syn_abc")
sub_resolved = cog2.resolve_subgraph(node.subgraph_refs[0])
```

Estimativa de tamanho: ~400 bytes/nó sem embedding, ~1.9 KB/nó com
embedding 384-d, ~250 bytes/aresta. Para 10⁴ nós + 10⁵ arestas ≈ 40 MB.

---

## 5. Testes

### 5.1 Rodar tudo

```bash
uv run pytest
```

### 5.2 Por suite

```bash
# Substrate cognitivo (96 testes — Fase 2 completa)
uv run pytest tests/test_graph.py tests/test_graph_refs.py -v

# Camada LLM (31 testes)
uv run pytest tests/test_llm_integration.py -v

# Kernel adaptive (3 testes de integração)
uv run pytest tests/test_adaptive_kernel.py -v
```

### 5.3 Com cobertura

```bash
uv run pytest --cov=arnaldo --cov-report=term-missing
```

### 5.4 Lint e typecheck

```bash
uv run ruff check arnaldo/
uv run mypy arnaldo/graph/
```

---

## 6. Custo e observabilidade

### 6.1 Usage por chamada

Todas as respostas LLM trazem `usage` normalizado:

```python
response = client.chat(tier=GOD, messages=[...])
print(response.usage)
# {"prompt_tokens": 234, "completion_tokens": 87, "total_tokens": 321,
#  "reasoning_tokens": 192}   ← apenas em tiers com reasoning
```

A normalização absorve a diferença entre Chat Completions
(`prompt_tokens`/`completion_tokens`) e Responses API
(`input_tokens`/`output_tokens`).

### 6.2 Cost tracking (futuro)

Em Fase 3, cada `usage` será gravado no Evidence Ledger:

```json
{
  "type": "llm_call",
  "tier": "god",
  "deployment": "god-tier",
  "usage": {"prompt_tokens": 234, "completion_tokens": 87, "reasoning_tokens": 192},
  "estimated_cost_usd": 0.012
}
```

Para cálculo de custo: tabela de preços por tier carregada de
`storage/pricing.json`, atualizada manualmente até integração com Azure
pricing API.

### 6.3 Otimização de custos

Três alavancas principais:

1. **Roteamento cognitivo** — não chamar GOD para tarefa que cabe em FAST.
   Já implementado em `TASK_TIER_MAP`.

2. **Pattern matching antes de LLM** — em Fase 2, antes de gerar novo
   synapse, consultar o grafo. Se existir synapse adequado, ativar em vez
   de criar novo (economia ~60% em domínios recorrentes).

3. **Prompt caching** — Azure suporta caching de prefixos. Para uso pesado
   de GOD/EXPERT, padronizar system prompts para máximo aproveitamento de
   cache. Não automatizado ainda.

---

## 7. Troubleshooting

### 7.1 HTTP 401 — chave inválida

```
LLMError: Azure OpenAI HTTP 401: invalid subscription key
```

Causas possíveis:

- Chave revogada/rotacionada
- Chave de outro recurso Azure (cada recurso tem chave própria)
- `.env` não está sendo lido (rode `uv run python -c "import os;
  print(os.environ.get('AZURE_OPENAI_API_KEY')[:10])"` para verificar)
- Env var do shell sobrescrevendo `.env` — definir
  `ARNALDO_RESPECT_ENV=false` (default já é assim).

**Para Codex em recurso separado:** defina `AZURE_CODEX_API_KEY` no `.env`
com a chave específica desse recurso.

### 7.2 HTTP 400 — operation unsupported

```
LLMError: Azure OpenAI HTTP 400: The requested operation is unsupported
```

Significa que o modelo não aceita o formato da API que você está usando.

- gpt-5.3-codex exige **Responses API** (`/responses`, não `/chat/completions`)
- Verifique se `api_style` do tier está correto (`RESPONSES` para Codex)

### 7.3 HTTP 400 — API version not supported

```
LLMError: Azure OpenAI HTTP 400: API version not supported
```

Endpoints v1 (Foundry Project) não precisam de `api-version` na URL. Se
estiver passando, remova. Ajuste `TierConfig.api_version = None` para esse
tier.

### 7.4 Status "incomplete" no Responses API

```python
response.finish_reason == "incomplete"
response.content == ""
```

`max_output_tokens` baixo demais — o modelo consumiu todo o budget em
reasoning interno antes de produzir output. Aumente para:

```
fast    → 1500
expert  → 4000
god     → 8000
codex   → 4000
```

### 7.5 GraphCycleError ao anexar sub-grafo

```
GraphCycleError: Anexar cog_xyz sob cog_abc cria ciclo
```

Você tentou criar `A → B → C → A` ou variante. A hierarquia precisa ser
DAG. Re-pense a relação — provavelmente um dos níveis deveria ser `SHARED`
em vez de `OWNED`.

### 7.6 Sub-grafo não encontrado em load

```python
loaded.resolve_subgraph(ref)
# → None
```

A `GraphRef` tem `uri` mas o arquivo não existe ou está corrompido.
Verifique:

```bash
ls -la storage/graph/
```

E que o `uri` da `ref` aponta para path correto.

---

## 8. API Python — exemplos canônicos

### 8.1 Run única

```python
from arnaldo import run

result = run(
    "Crie um plano de validação para um produto B2B",
    autonomy="autonomo",
    session_id="sessao_produto",
    terms_accepted=True,
)
print(result.run_dir)
print(result.files["artifact"])
```

### 8.2 Compilação parcial (sem execução)

```python
from arnaldo import compile_intent, compile_task

intent = compile_intent("Automatize o onboarding de clientes")
task = compile_task(intent)

print(task.goal)              # {"statement": "...", "type": "execute_or_automate"}
print(task.capability_needs)  # [{"id": "work.decompose", "required": True}, ...]
```

### 8.3 Kernel customizado

```python
from pathlib import Path
from arnaldo.kernel import ArnaldoKernel
from arnaldo.runtime import MultiAgentRuntime

runtime = MultiAgentRuntime()
runtime.configure_provider(...)

kernel = ArnaldoKernel(runtime=runtime)
result = kernel.run(
    "Valide a demanda por automação de clínicas",
    autonomy="autonomo",
    output_dir=Path("runs"),
    session_id="sessao_go_to_market",
    terms_accepted=True,
)
```

### 8.4 Cliente LLM standalone

```python
from dataclasses import dataclass
from arnaldo.llm import AzureOpenAIClient, GOD, EXPERT, CODEX

client = AzureOpenAIClient()

# Chat clássico
r = client.chat(
    tier=EXPERT,
    messages=[
        {"role": "system", "content": "Você é o Arnaldo."},
        {"role": "user", "content": "Resuma a teoria de harness em 3 linhas."},
    ],
)

# Structured output tipado (recomendado)
@dataclass
class Entity:
    name: str
    type: str

@dataclass
class EntityExtraction:
    entities: list[Entity]

typed = client.chat_typed(
    tier="fast",
    messages=[{"role":"user","content":"extraia entidades de 'João trabalha na Anthropic'"}],
    response_model=EntityExtraction,
)
if typed.refusal:
    print("LLM refusal:", typed.refusal)
else:
    print(typed.parsed.entities)

# JSON estruturado (compatibilidade transitória)
compat = client.chat_json(
    tier="fast",
    messages=[{"role":"user","content":"extraia entidades de 'João trabalha na Anthropic'"}],
    schema_hint='{"entities": [{"name": "string", "type": "string"}]}',
)

# Geração de código (escolhe CODEX automaticamente)
r = client.generate_code(
    prompt="Implemente um validador de CPF em Python",
    language="python",
    reasoning_effort="xhigh",
)
print(r.content)
```

### 8.5 CognitiveGraph — uso completo

```python
from arnaldo.graph import (
    CognitiveGraph, MemoryNode, SynapseNode, CapabilityNode,
    GraphEdge, EdgeKind, SourceRecord, SourceKind,
    GraphRefKind,
)

cog = CognitiveGraph()

# Adiciona nós
mem = MemoryNode.semantic(
    "MAGMA representa memória como multi-grafo de 4 dimensões",
    source=SourceRecord(
        kind=SourceKind.EXTERNAL_AUTHORITY,
        identifier="arxiv:2601.03236",
        confidence=0.92,
    ),
    domain="semantic_stable",
)
cog.add_node(mem)

syn = SynapseNode.specialist(
    "Critic — adversarial review",
    role="critic",
    objective="apontar lacunas e riscos",
)
cog.add_node(syn)

cap = CapabilityNode.tool(
    "validation.critic_review",
    description="Revisão crítica de outputs",
    maturity="trusted",
)
cog.add_node(cap)

# Arestas tipadas
cog.add_edge(GraphEdge.connect(syn.id, cap.id, EdgeKind.REQUIRES))
cog.add_edge(GraphEdge.connect(syn.id, mem.id, EdgeKind.MENTIONS))

# Ciclo de execução: ativação + outcome
cog.activate(syn.id)
# ... executa runtime ...
cog.record_outcome(syn.id, success=True)

# Sub-grafo OWNED com conhecimento privado do synapse
private_kb = CognitiveGraph()
private_kb.add_node(MemoryNode.semantic("Detalhe interno", source=SourceRecord.from_bootstrap("demo")))
cog.attach_subgraph(syn.id, private_kb, kind=GraphRefKind.OWNED)

# Plasticidade transitiva
trace = {private_kb.graph_id: {private_kb.iter_nodes().__next__().id}}
cog.record_outcome_recursive(
    syn.id, success=True, scoped_activations=trace
)

# Periodic decay sweep
counters = cog.sweep_decay()
print(counters)  # {"to_stale": ..., "to_archived": ..., "to_consolidated": ...}

# Persistência
cog.persist("storage/graph/root.msgpack")
```

### 8.6 Retrieval híbrido

```python
import numpy as np
from arnaldo.graph import NodeKind

# Em produção, query_embedding vem de Azure OpenAI embeddings
query_embedding = np.random.rand(384).astype(np.float32)

results = cog.match(
    query="por que o triager falhou ontem?",
    query_embedding=query_embedding,
    node_kinds=[NodeKind.MEMORY],
)

for r in results[:5]:
    print(f"{r.node.label}")
    print(f"  score={r.score:.3f} hop={r.hop_distance}")
    print(f"  sem={r.semantic_score:.2f} g={r.graph_score:.2f} p={r.plasticity_score:.2f}")
```

### 8.7 Federated match através de bridges

```python
results = cog.federated_match(
    node_id=syn.id,
    query="qual o estado interno do triager?",
)

for sub_graph_id, sub_results in results.items():
    print(f"Sub-graph {sub_graph_id}:")
    for r in sub_results:
        print(f"  - {r.node.label}")
```

Apenas nós listados em `ref.bridge_nodes` aparecem no resultado — o resto
do sub-grafo permanece privado.

### 8.8 Agentes especializados — SynapseNode com contratos

> Fundamentos em [`architecture.md § 13`](architecture.md#13-agentes-especializados-e-composição).

Princípio: cada agente tem **uma responsabilidade**, **contratos explícitos**
de entrada e saída, **triggers declarados** e **capabilities restritas**.

```python
from arnaldo.graph import SynapseNode

# Agente especialista: enquadrar intenção do usuário em contrato declarativo.
# Responsabilidade ÚNICA. Não decide. Não executa. Só enquadra.
framer = SynapseNode.specialist(
    label="Intent Framer",
    role="framer",
    objective="Enquadrar intenção bruta em contrato declarativo com goal e constraints",
    epistemic_style="evidence_first",

    # Contratos tipados (I2, I3 da arquitetura)
    input_contract={
        "schema": "user_intent_text",
        "required_fields": ["raw_text", "session_id"],
        "expected_types": {"raw_text": "str", "session_id": "str"},
    },
    output_contract={
        "schema": "framed_intent",
        "required_sections": ["goal", "constraints", "evidence", "uncertainties"],
        "validation_rules": {
            "goal": "non_empty_string",
            "constraints": "list_of_strings",
        },
    },

    # Triggers explícitos (I4) — gates booleanos antes do matching semântico
    activation_triggers={
        "keywords": ["criar", "construir", "planejar", "analisar"],
        "min_confidence": 0.65,
        "required_context_tags": ["new_session_start"],
    },

    # Capabilities restritas (I5 — Princípio do Menor Privilégio)
    required_capabilities=["intent.parse", "domain.classify"],
    forbidden_capabilities=[
        "send.external_message",
        "spend.money",
        "delete.user_data",
        "code.execute",
    ],

    tier_preference="expert",       # gpt-5 default; god para casos críticos
    max_prompt_tokens=1000,         # invariante I1 — força decomposição
)
```

### 8.9 Workflow como SynapseNode-orchestrator + sub-grafo OWNED

Workflow é **função composicional**: assinatura `Input → Output` igual a um
synapse folha; implementação interna é o sub-grafo dos steps.

```python
from arnaldo.graph import (
    CognitiveGraph, GraphEdge, EdgeKind, GraphRefKind, SynapseNode,
)

def make_pipeline_workflow(
    *,
    label: str,
    steps: list[SynapseNode],
    parent_graph: CognitiveGraph,
) -> tuple[SynapseNode, CognitiveGraph]:
    """Cria workflow como SynapseNode-orchestrator + sub-grafo OWNED.

    Topologia: pipeline sequencial (A → B → C → ...).
    """
    # 1) Sub-grafo interno com os steps + arestas ACTIVATES
    internal = CognitiveGraph()
    for step in steps:
        internal.add_node(step)
    for a, b in zip(steps, steps[1:]):
        internal.add_edge(GraphEdge.connect(a.id, b.id, EdgeKind.ACTIVATES))

    # 2) Synapse-orchestrator com contratos derivados das pontas
    first_input  = steps[0].payload.get("input_contract", {})
    last_output  = steps[-1].payload.get("output_contract", {})

    orchestrator = SynapseNode.specialist(
        label=label,
        role="orchestrator",
        objective=f"executar pipeline de {len(steps)} steps especializados",
        input_contract=first_input,
        output_contract=last_output,
        activation_triggers={
            "keywords": [],   # delegado aos steps internos
            "min_confidence": 0.5,
        },
        tier_preference="god",  # orquestração é decisão estratégica
    )

    # 3) Insere no grafo pai e anexa sub-grafo OWNED com bridges
    parent_graph.add_node(orchestrator)
    parent_graph.attach_subgraph(
        orchestrator.id, internal,
        kind=GraphRefKind.OWNED,
        bridge_nodes=[steps[0].id, steps[-1].id],   # interface pública
    )
    return orchestrator, internal


# ── Uso típico ────────────────────────────────────────────────────────
root = CognitiveGraph()

framer  = SynapseNode.specialist("Framer",  role="framer",  objective="...")
planner = SynapseNode.specialist("Planner", role="planner", objective="...")
critic  = SynapseNode.specialist("Critic",  role="critic",  objective="...")

workflow, internal = make_pipeline_workflow(
    label="Frame → Plan → Critic",
    steps=[framer, planner, critic],
    parent_graph=root,
)

# workflow agora é cidadão do grafo: persistente, plástico, reutilizável.
root.persist("storage/graph/root.msgpack")
```

### 8.10 Workflow-of-workflows — composição recursiva

Um workflow pode aparecer como **step** dentro de outro workflow. Sua
assinatura `Input → Output` é igual à de um synapse folha; o nível superior
não enxerga o sub-grafo interno.

```python
# Workflow básico: exploração paralela
explore_wf, _ = make_pipeline_workflow(
    label="Exploração paralela",
    steps=[framer, explorer_a, synthesizer],
    parent_graph=root,
)

# Workflow avançado que INCLUI o de exploração + adiciona critic forte
advanced_critic = SynapseNode.specialist("Adversarial Critic", role="critic", objective="...")

advanced_wf, _ = make_pipeline_workflow(
    label="Exploração + Crítica avançada",
    steps=[explore_wf, advanced_critic],   # ← workflow tratado como step
    parent_graph=root,
)

# Ao ativar advanced_wf, o runtime:
#   1) Resolve o sub-grafo OWNED de advanced_wf
#   2) Ativa explore_wf (que resolve seu próprio sub-grafo recursivamente)
#   3) Ativa adversarial_critic
#   4) Plasticidade transitiva propaga reward em todos os níveis
```

### 8.11 Plasticidade transitiva após execução

Após uma run bem-sucedida do workflow, propague o reward Hebbian através de
toda a hierarquia:

```python
# Trace de ativação coletado durante a execução
activation_trace = {
    # graph_id → {node_ids realmente ativados nesta run}
    advanced_wf_internal.graph_id: {explore_wf.id, advanced_critic.id},
    explore_internal.graph_id:     {framer.id, synthesizer.id},
    # explorer_a NÃO aparece — não foi ativado (poda emergente)
}

root.record_outcome_recursive(
    advanced_wf.id,
    success=True,
    scoped_activations=activation_trace,
    max_depth=3,
)

# Efeitos:
#   advanced_wf.weight     ↑    (workflow inteiro funcionou)
#   explore_wf.weight      ↑    (sub-workflow funcionou)
#   framer.weight          ↑
#   synthesizer.weight     ↑
#   explorer_a.weight      —    (não ativado nesta run)
#   ref_strength (todos)   ↑    (canais entre níveis fortalecidos)
```

Isso é **backpropagation simbólica de reward** — sem gradientes, apenas
Hebbian update por nível.

### 8.12 Anti-padrões — o que NÃO fazer

```python
# ❌ ANTI-PADRÃO: agente que faz "tudo"
SynapseNode.specialist(
    label="Agente Mestre",
    role="generic",
    objective=(
        "Compilar intenção, planejar, executar, validar, escrever artefato "
        "e enviar notificações para o usuário"  # ← 5 responsabilidades!
    ),
    required_capabilities=["*"],     # ← whitelist vazia/total
    forbidden_capabilities=[],        # ← sem PoLP
    max_prompt_tokens=8000,           # ← excede invariante I1
)
# Bag of Agents: 17× taxa de erro vs especialização (MAST, NeurIPS 2025)


# ❌ ANTI-PADRÃO: workflow ad-hoc sem persistência
def execute_inline(intent):
    # workflow inventado a cada chamada — sem reuso, sem aprendizado
    a = run_framer(intent)
    b = run_planner(a)
    return run_critic(b)


# ✅ CORRETO: workflow persistente, reutilizável, plástico
workflow, _ = make_pipeline_workflow(
    label="Frame → Plan → Critic",
    steps=[framer, planner, critic],
    parent_graph=root,
)
root.persist("storage/graph/root.msgpack")   # próxima sessão recupera
```

Detalhes formais e fundamentação teórica:
[`architecture.md § 13`](architecture.md#13-agentes-especializados-e-composição).

### 8.13 ExecutionEngine tipado para `SynapseNode`

Quando quiser executar synapses diretamente no `CognitiveGraph` com contratos
tipados, use `ExecutionEngine`:

```python
from dataclasses import dataclass
from arnaldo.graph import CognitiveGraph, EdgeKind, ExecutionEngine, GraphEdge, SynapseNode

@dataclass
class CriticOutput:
    result: str
    evidence: list[str]

graph = CognitiveGraph()

framer = SynapseNode.specialist(
    "Framer",
    role="framer",
    objective="enquadrar intenção",
    output_contract_model=CriticOutput,
    tier_preference="fast",
)
critic = SynapseNode.specialist(
    "Critic",
    role="critic",
    objective="avaliar riscos",
    output_contract_model=CriticOutput,
    tier_preference="expert",
)
graph.add_node(framer)
graph.add_node(critic)
graph.add_edge(GraphEdge.connect(framer.id, critic.id, EdgeKind.ACTIVATES, weight=0.8))

engine = ExecutionEngine(
    graph=graph,
    llm_client=client,  # AzureOpenAIClient
    model_registry={"CriticOutput": CriticOutput},
)

# Executa cadeia linear derivada das arestas ACTIVATES
path, ctx, results = engine.execute_activates_chain(
    framer.id,
    request="Crie um plano para SaaS B2B e aponte os riscos",
)

print(path)               # [framer_id, critic_id]
print(ctx.outputs)        # output tipado por synapse_id
print(ctx.refusals)       # refusals registrados (se houver)
print([r.success for r in results])

# Execução por camadas com paralelismo local (branches ACTIVATES)
path, ctx, results = engine.execute_activates_parallel(
    framer.id,
    request="Explore alternativas e sintetize um plano",
    max_parallel=4,
)
```

Observações:

- O runtime em grafo é o caminho padrão do kernel.
- Para topologia `parallel_with_synthesis`, o `GraphRuntime` seleciona
  automaticamente `execute_activates_parallel` e registra o modo em
  `trace.jsonl` (`event_type=graph_execution_planned`).
- Em modo `graph`, o kernel entrega ao runtime uma organização seed e pode
  deixar `workflow=[]`; o plano executável é compilado no próprio grafo.
- O próximo passo é migrar de organização temporária por run para grafo
  cognitivo persistido entre runs.
- O `GraphRuntime` atual já:
  - cria/reaproveita sinapses dinamicamente por `agent_id + action`;
  - enriquece o workflow dinamicamente no runtime (inclusive quando `organization.workflow` vem vazio);
  - adiciona etapas de `design_tooling` (gaps ausentes) e `stabilize_tooling` (capabilities degradadas);
  - materializa `CapabilityNode` para capabilities observadas;
  - promove maturidade de `CapabilityNode` (`draft -> tested -> trusted`) após execução bem-sucedida de etapas de tooling;
  - sincroniza capabilities dinâmicas do grafo de execução para o `CapabilityRegistry` (ciclo entre runs);
  - registra `MemoryNode` por step executado (knowledge trail);
  - persiste `execution-graph.msgpack` e reutiliza na sessão seguinte.

---

## 9. Frontend e dashboard de observabilidade

> Esta seção descreve o frontend e dashboard de observabilidade do Arnaldo.
> Fundamentos teóricos e justificativa arquitetural estão em
> [`architecture.md § 18`](architecture.md#18-frontend-e-observabilidade).
>
> **Status:** Em planejamento (Fase A-E). Backend já tem ~90% do necessário;
> falta camada de eventos + servidor HTTP/SSE + UI Next.js.

### 9.1 Visão geral

O frontend é composto por **sete painéis canônicos** que coexistem em
modos:

| Painel | Função |
|--------|--------|
| **P1 GraphView**        | Mapa do grafo cognitivo (Obsidian-style) |
| **P2 RunMonitor**       | Trace tree em tempo real (LangSmith-style) |
| **P3 ActivationOverlay**| Sobrepõe ativações da run sobre o grafo |
| **P4 EvidenceLedger**   | Cadeia causal append-only (compliance) |
| **P5 PlasticityHeatmap**| Diff de pesos antes/depois de runs |
| **P6 NodeInspector**    | Drawer com tudo sobre um nó (incl. proveniência) |
| **P7 SessionConsole**   | Chat com o Arnaldo + streaming token-by-token |

### 9.2 Stack técnico planejado

```
Backend
  FastAPI 0.115+        HTTP + SSE
  sse-starlette         reconnect, heartbeats
  asyncio.Queue         event bus interno
  msgpack               serialização (já existe)
  arnaldo/observability/{events,bus}.py (a criar)
  arnaldo/server/                       (a criar)

Frontend (/web)
  Next.js 15            App Router, RSC, streaming
  TypeScript strict     type-safety end-to-end
  shadcn/ui + Tailwind  primitives
  Cytoscape.js + fcose  P1 GraphView
  react-flow            workflow editáveis
  Framer Motion         pulse de nós, edge flow (P3)
  EventSource nativo    SSE consumer
  ai-sdk/react useChat  P7 SessionConsole
```

### 9.3 Eventos canônicos (taxonomia)

O bus emite eventos do tipo `GraphEvent` em pontos-chave do kernel:

```
Lifecycle:        run.started, run.completed, run.failed, run.paused
Pipeline:         intent.compiled, task.derived, cognitive.decision
Grafo:            graph.node_activated, graph.edge_traversed,
                  graph.subgraph_attached
Plasticidade:     plasticity.weight_updated, plasticity.decay_sweep
LLM:              llm.call_started, llm.token_delta, llm.call_completed,
                  llm.refusal, llm.validation_failed
Tools:            tool.invoked, tool.args_partial, tool.completed
Memória:          memory.retrieved, memory.stored
Episteme:         episteme.gap_detected, episteme.curiosity_signal
Policy:           policy.evaluated, policy.blocked, policy.human_checkpoint
Evidence:        evidence.recorded
```

Spec completa em [`architecture.md § 18.6`](architecture.md#186-eventos-como-contrato--taxonomia-formal).

### 9.4 Como rodar (planejado)

```bash
# Backend
uv run arnaldo serve --port 8000
# → FastAPI em http://localhost:8000
# → SSE em http://localhost:8000/events/live

# Frontend (em /web, projeto separado)
cd web
pnpm install
pnpm dev
# → http://localhost:3000
```

### 9.5 Endpoints HTTP

```
POST /sessions/{sid}/turn        Inicia uma run (retorna run_id)
GET  /events/{run_id}            SSE stream filtrado por run
GET  /events/live                SSE stream global (todas as runs)
GET  /graph                      Snapshot JSON do CognitiveGraph
GET  /graph/{node_id}            Detalhes de um nó (com SourceRecord)
GET  /evidence/{run_id}          Ledger imutável da run
GET  /plasticity/diff?run_id=... Diff de pesos antes/depois
```

### 9.6 Padrões UX a respeitar

- **Progressive disclosure** — cada clique aprofunda. Nunca dump completo
  no primeiro carregamento.
- **Discriminação visual de eventos** — refusal não é erro:
  - ✓ verde (success), ⚠ amarelo (warning), ✗ vermelho (error),
    🛑 roxo (refusal), ⏱ cinza (timeout), 🚫 vermelho-cadeado (policy)
- **Custo annotation por span** — sempre inline:
  - `"gpt-5-pro (god) · 1.2s · in 234 / out 87 / reasoning 192 · $0.0042"`
- **Filtros sticky toolbar** — 5-6 essenciais + Cmd+K. Anti-padrão
  Datadog-style com 20 combinados.
- **Local view por default** — N hops do nó focal. Expansão sob demanda.
- **Hash chain opcional** — para compliance regulatório (EU AI Act,
  SOC 2). Fase 2+.

### 9.7 Anti-padrões explicitamente vetados

| Anti-padrão                       | Por quê |
|-----------------------------------|----------------------------------------|
| Bag of Dashboards (30 widgets)    | Overwhelm visual |
| WebSocket para tudo               | SSE basta; WS só para human-in-loop |
| Schema proprietário não-OTel      | Bloqueia integração com Phoenix/Langfuse |
| Refusal como erro                 | Polui métricas; é evento legítimo |
| Grafo "completo" sempre visível   | 10k nós → freeze |
| Frontend Python (Streamlit)       | Limita animação; perde interatividade |

### 9.8 Plano de implementação

```
Fase A — Event Bus + Instrumentação (1 semana)        ~330 LoC backend
Fase B — Backend HTTP/SSE          (1 semana)         ~200 LoC backend
Fase C — Frontend P1+P2+P7         (2 semanas)        ~1200 LoC frontend
Fase D — P3 + P4                    (1 semana)         ~500 LoC frontend
Fase E — P5 + P6 + polish           (1 semana)         ~300 LoC frontend
────────────────────────────────────────────────────────────────────────
Total                              ~6 semanas         ~2.530 LoC
```

Demo funcional convincente já em A+B+C (4 semanas).
