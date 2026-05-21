# Arquitetura — ArnaldAI

> Mapa vivo da arquitetura. Atualizar quando houver mudança estrutural.
> Formato: `- [YYYY-MM] Descrição — contexto`

---

## Stack

- Python 3.12+ com uv (gerenciador de pacotes)
- NetworkX (multidigrafo tipado)
- NumPy (vetores de embedding + similaridade)
- msgpack (serialização binária do grafo)
- Azure OpenAI (4 tiers: GOD/EXPERT/FAST/CODEX, stdlib-only)

## Camadas

- **Camada 0 — Entrada:** CLI (`arnaldo/cli.py`), API Python (`arnaldo/core.py`)
- **Camada 1 — Compilação:** IntentCompiler → TaskCompiler → CognitiveControlPlane
- **Camada 2 — Substrate:** CognitiveGraph com MemoryNode, SynapseNode, CapabilityNode
- **Camada 3 — Ativação:** PatternMatcher → ActivationPattern
- **Camada 4 — Execução:** RuntimeAdapter (Local, Graph, MultiAgent) + Sandbox + PolicyEngine
- **Camada 5 — Evolução:** EvidenceLedger, PlasticityEngine, sweep_decay
- **Camada 6 — Episteme:** GapAnalyzer, CuriosityEngine, WebForager (Fase 4+)

## Módulos Principais

| Módulo | Responsabilidade |
|--------|-----------------|
| `arnaldo/kernel.py` | Pipeline principal: compile → match → execute |
| `arnaldo/graph/store.py` | CognitiveGraph — substrato vivo |
| `arnaldo/graph/plasticity.py` | Plasticidade Hebbian + decay adaptativo |
| `arnaldo/graph/provenance.py` | SourceRecord — proveniência epistêmica |
| `arnaldo/llm/client.py` | AzureOpenAIClient — stdlib-only |
| `arnaldo/llm/router.py` | TASK_TIER_MAP — roteamento task → tier |
| `arnaldo/memory/store.py` | MemoryStore — ledger + memory-graph |
| `arnaldo/components/tool_forge.py` | Forja de ferramentas dinâmicas |

## Princípios Invioláveis

- LLM eleva qualidade, mas estrutura nunca depende dele (fallback heurístico)
- Sem origem, sem inserção (proveniência obrigatória)
- Plasticidade é função pura com bounds explícitos
- Decay é adaptativo por domínio, nunca uniforme
- GraphRef forma DAG — ciclos rejeitados
