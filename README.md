# ◉ Arnaldo

**Substrate cognitivo simbólico para agentes que aprendem com auditabilidade.**

---

## O que é

Arnaldo é um **kernel cognitivo**: um grafo único, vivo e auditável onde
memórias, agentes e ferramentas co-existem como nós persistentes ligados
por arestas tipadas com plasticidade Hebbian. Cada nó pode possuir ou
referenciar outros grafos, formando uma hierarquia composicional.

Não é um framework de agentes. Não é wrapper de LLM. É **infraestrutura
para autonomia que acumula valor com o tempo** — onde conhecimento
adquirido em uma run é ativo capturado pelo sistema para ser reutilizado,
refinado e auditado.

**Princípio de composição:** agentes são **especializados e estritos**
(um agente, uma responsabilidade, contratos tipados, capabilities
restritas); workflows compõem agentes; workflows compõem workflows. A
recursão é fractal — um workflow tem assinatura `Input → Output` igual à
de um agente folha, então pode ser usado como step em outro workflow.
Fundamentos formais e validação teórica em
[`docs/architecture.md § 13`](docs/architecture.md#13-agentes-especializados-e-composição).

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│       "Crie um plano para uma startup B2B em 90 dias"                │
│                              │                                       │
│                              ▼                                       │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │              ARNALDO KERNEL                                 │     │
│  │                                                             │     │
│  │   Compilação ─▶ Pattern matching ─▶ Ativação transitória   │     │
│  │       │              no grafo            │                  │     │
│  │       │                                  ▼                  │     │
│  │       │                          Runtime + Sandbox          │     │
│  │       │                                  │                  │     │
│  │       └──────────── Plasticidade ◀──────┘                  │     │
│  │                     Hebbian                                 │     │
│  └────────────────────────────────────────────────────────────┘     │
│                              │                                       │
│                              ▼                                       │
│              Artefato + Evidência causal + Memória nova              │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Posicionamento

A indústria de agentes em 2025-2026 está dividida em dois eixos.

```
                                         estrutura
                                         elevada
                                            │
                         LangGraph ──── ARNALDO (alvo)
                       (state machine)  (substrate cognitivo)
                                            │
   ◄────────────────────────────────────────┼────────────────────────────────►
   modelo                                   │                          modelo
   opaco                                    │                       transparente
                                            │
                          OpenClaw ──── CrewAI / AutoGen
                       (runtime monolítico) (role-based)
                                            │
                                         estrutura
                                         frouxa
```

| Framework        | Memória persistente | Plasticidade | Auditabilidade | Hierarquia |
|------------------|---------------------|--------------|----------------|------------|
| LangGraph        | Bolt-on             | Não          | Trace          | Subgraphs estáticos |
| CrewAI           | Por-task            | Não          | Logs           | Não        |
| AutoGen          | Por-conversa        | Não          | Logs           | Não        |
| OpenClaw         | Arquivo MD          | Manual       | Limitada       | Não        |
| **Arnaldo**      | **Grafo vivo**      | **Hebbian**  | **Ledger causal** | **GraphRef** |

LangGraph trata memória como bolt-on. Arnaldo move o ponto de equilíbrio:
faz da memória o **substrato**, e dos agentes peças residentes nesse
substrato.

---

## Quickstart

```bash
# Setup (uv + Python 3.12)
uv venv --python 3.12
uv sync --extra dev

# Configurar Azure OpenAI (modo simples)
cp .env.example .env
# editar só 3 campos no .env:
# - AZURE_OPENAI_ENDPOINT
# - AZURE_OPENAI_API_KEY
# - AZURE_OPENAI_MODEL

# Validar
uv run pytest                              # 130 testes
uv run python -m arnaldo "Crie um plano B2B" --autonomy autonomo
```

Setup completo, configuração de tiers, troubleshooting:
[`docs/operations.md`](docs/operations.md).

---

## Arquitetura em uma página

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

Especificação formal, invariantes, modelo bi-temporal, plasticidade
Hebbian, retrieval híbrido, sistema epistêmico e hierarquia de grafos:
[`docs/architecture.md`](docs/architecture.md).

---

## Estado atual

```
Fase 0 — Fundação                                            ✓ concluída
   ✓ Contratos versionados (IntentIR, TaskIR, ...)
   ✓ Pipeline determinístico end-to-end
   ✓ CLI funcional

Fase 1 — Integração LLM                                      ✓ concluída
   ✓ Camada LLM stdlib-only com 4 tiers
     (gpt-5-pro / gpt-5 / gpt-5.4-nano / gpt-5.3-codex)
   ✓ IntentCompiler com fallback heurístico
   ⃝ Resto dos componentes com LLM real (pendente)

Fase 2 — Substrate cognitivo                                 ✓ pronto
   ✓ CognitiveGraph (3 nodes × 14 edges tipados)
   ✓ Modelo bi-temporal (event time + transaction time)
   ✓ Proveniência epistêmica (SourceRecord tipado)
   ✓ Plasticidade Hebbian + decay adaptativo
   ✓ Retrieval híbrido (vector + graph BFS + plasticity)
   ✓ Hierarquia de grafos (GraphRef OWNED + SHARED)
   ✓ Plasticidade transitiva entre níveis
   ✓ Persistência msgpack
   ✓ 96 testes verdes

Fase 3 — Plasticidade em produção                            ⃝ próxima
   ⃝ Hebbian após cada run real
   ⃝ Decay sweep agendado
   ⃝ Cost tracking em EvidenceLedger

Fase 4 — Episteme + Protocolos                               ⃝
   ⃝ EpistemicGapAnalyzer + CuriosityEngine
   ⃝ WebForager + KnowledgeIngester
   ⃝ GraphRef.FEDERATED (A2A) + SNAPSHOT
   ⃝ MCP client/server

Fase 5 — Backends de escala                                  ⃝
   ⃝ FalkorDB / Neo4j (para |V| > 10⁵)
   ⃝ Streaming responses (SSE)

Fase 6 — Frontend e observabilidade                          ⃝ planejada
   ⃝ Event bus (asyncio.Queue + SSE fanout)
   ⃝ FastAPI server (eventos, grafo, evidence, plasticidade)
   ⃝ Frontend Next.js com 7 painéis canônicos:
     P1 GraphView (Obsidian-style)
     P2 RunMonitor (LangSmith-style)
     P3 ActivationOverlay (peça única: grafo + run no mesmo plano)
     P4 EvidenceLedger (compliance-ready)
     P5 PlasticityHeatmap (diff de pesos)
     P6 NodeInspector (proveniência + bitemporal)
     P7 SessionConsole (chat com streaming)
```

Análise honesta linha-a-linha do que é stub vs funcional está em
[`docs/architecture.md § 20`](docs/architecture.md). Plano detalhado do
frontend em [`docs/architecture.md § 18`](docs/architecture.md#18-frontend-e-observabilidade).

---

## Comparação técnica

| Recurso                            | OpenClaw   | CrewAI | LangGraph | AutoGen | **Arnaldo** |
|------------------------------------|------------|--------|-----------|---------|-------------|
| Agentes pré-definidos              | estático   | ✓      | ✓         | ✓       | ❌ Emergentes |
| Topologia fixa                     | ✓          | ✓      | ✓         | ✓       | ❌ Emergente  |
| Compilação de intenção             | ❌         | ❌     | ❌        | ❌      | ✓           |
| Memória como grafo temporal        | ❌         | ❌     | ❌        | ❌      | ✓           |
| Plasticidade Hebbian               | ❌         | ❌     | ❌        | ❌      | ✓           |
| Hierarquia de grafos (refs)        | ❌         | ❌     | Limitada  | ❌      | ✓           |
| Workflow-of-workflows (recursivo)  | ❌         | Parcial| Subgraphs | ❌      | ✓ via GraphRef |
| Contratos tipados input/output     | ❌         | ❌     | ❌        | ❌      | ✓ (Fase 2.5) |
| Evidence Ledger nativo             | ❌         | ❌     | ❌        | ❌      | ✓           |
| Policy pré-execução                | ❌         | ❌     | Parcial   | ❌      | ✓           |
| Sandbox por run                    | ❌         | ❌     | ❌        | ❌      | ✓           |
| Tool Forge (síntese ativa)         | ❌         | ❌     | ❌        | ❌      | ✓           |
| Foragem epistêmica web             | ❌         | ❌     | ❌        | ❌      | Fase 4      |
| 4 tiers LLM (god/expert/fast/codex)| ❌         | ❌     | ❌        | ❌      | ✓           |
| Segurança estrutural               | ❌ (CVEs)  | ❌     | ❌        | ❌      | ✓           |

---

## API Python — exemplos rápidos

### Run única

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

### CognitiveGraph com hierarquia

```python
from arnaldo.graph import (
    CognitiveGraph, MemoryNode, SynapseNode,
    GraphRefKind, SourceRecord, SourceKind,
)

root = CognitiveGraph()
triager = SynapseNode.specialist(
    "GitHub Triager",
    role="triager",
    objective="categorizar issues",
)
root.add_node(triager)

# Sub-grafo OWNED com conhecimento privado do agente
private_kb = CognitiveGraph()
private_kb.add_node(MemoryNode.semantic(
    "GitHub API v4 usa GraphQL",
    source=SourceRecord(kind=SourceKind.EXTERNAL_AUTHORITY, identifier="docs.github.com"),
))

root.attach_subgraph(
    triager.id,
    private_kb,
    kind=GraphRefKind.OWNED,
)

# Sub-grafo SHARED compartilhado entre múltiplos agentes
shared_kb = CognitiveGraph()
root.attach_subgraph(triager.id, shared_kb, kind=GraphRefKind.SHARED)

# Persistência preserva refs
root.persist("storage/graph/root.msgpack")
```

Catálogo completo de exemplos:
[`docs/operations.md § 8`](docs/operations.md).

---

## Os três documentos

```
README.md (este)             — entrada, posicionamento, status atual

docs/
├── architecture.md          — documento canônico (23 seções)
│                              ├── tese e invariantes
│                              ├── modelo formal do grafo
│                              ├── nós e arestas tipados
│                              ├── bi-temporal + proveniência
│                              ├── plasticidade Hebbian
│                              ├── decay adaptativo
│                              ├── retrieval híbrido
│                              ├── grafos referenciando grafos
│                              ├── agentes especializados e composição
│                              ├── pipeline do kernel
│                              ├── camada LLM (4 tiers)
│                              ├── saídas estruturadas (response_format)
│                              ├── sistema epistêmico
│                              ├── frontend e observabilidade ★
│                              ├── envelope de capacidades
│                              ├── estado de implementação
│                              ├── critérios de aceitação
│                              ├── riscos honestos
│                              └── referências canônicas
│
└── operations.md            — guia operacional
                                ├── setup (uv + Python 3.12)
                                ├── configuração Azure (4 tiers)
                                ├── execução (CLI + API)
                                ├── estrutura de storage
                                ├── testes
                                ├── custo e observabilidade
                                ├── troubleshooting
                                ├── exemplos canônicos
                                │   ├── 8.1-8.7  uso atual
                                │   ├── 8.8  SynapseNode com contratos
                                │   ├── 8.9  make_workflow factory
                                │   ├── 8.10 workflow-of-workflows
                                │   ├── 8.11 plasticidade transitiva
                                │   └── 8.12 anti-padrões
                                └── frontend e observabilidade ★
                                    (planejado, ~6 semanas em 5 fases)
```

---

## Licença

Privado por enquanto. Sem licença pública definida.

## Referências canônicas

Para fundamentos teóricos (Hebb, Minsky, Tulving, Ebbinghaus) e papers
modernos (MAGMA, Zep, CoALA, Mixture-of-Agents), consulte
[`docs/architecture.md § 20`](docs/architecture.md).
