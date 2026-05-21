# Navegação — "Onde acho X?"

> Mapa rápido de navegação. Atualizar quando novo módulo for criado ou movido.

---

## Entry Points

| O quê | Onde |
| --- | --- |
| CLI | `arnaldo/cli.py` → `main()` |
| `python -m arnaldo` | `arnaldo/__main__.py` |
| API Python | `arnaldo/core.py` |

## Grafo Cognitivo

| O quê | Onde |
| --- | --- |
| Substrato principal | `arnaldo/graph/store.py` → `CognitiveGraph` |
| Nós tipados | `arnaldo/graph/nodes.py` → `NodeKind`, `MemoryNode`, `SynapseNode`, `CapabilityNode` |
| Arestas tipadas | `arnaldo/graph/edges.py` → `EdgeKind` |
| Plasticidade Hebbian | `arnaldo/graph/plasticity.py` |
| Proveniência | `arnaldo/graph/provenance.py` → `SourceRecord` |
| Modelo bi-temporal | `arnaldo/graph/temporal.py` |
| Hierarquia (GraphRef) | `arnaldo/graph/refs.py` |
| Workflows | `arnaldo/graph/workflows.py` |
| Pattern matching | `arnaldo/graph/matching.py` |
| Engine de execução | `arnaldo/graph/execution.py` |

## Pipeline do Kernel

| O quê | Onde |
| --- | --- |
| Kernel principal | `arnaldo/kernel.py` |
| Intent compiler | `arnaldo/components/intent_compiler.py` |
| Task compiler | `arnaldo/components/task_compiler.py` |
| Cognitive control | `arnaldo/components/cognitive_control.py` |
| Adaptive planner | `arnaldo/components/adaptive_planner.py` |
| Policy engine | `arnaldo/components/policy_engine.py` |
| Capability registry | `arnaldo/components/capability_registry.py` |
| Tool forge | `arnaldo/components/tool_forge.py` |
| Organization generator | `arnaldo/components/organization_generator.py` |

## LLM

| O quê | Onde |
| --- | --- |
| Cliente Azure OpenAI | `arnaldo/llm/client.py` → `AzureOpenAIClient` |
| Config de tiers | `arnaldo/llm/config.py` → `load_config()` |
| Roteamento task→tier | `arnaldo/llm/router.py` → `TASK_TIER_MAP` |
| Structured outputs | `arnaldo/llm/structured.py` → `dataclass_to_schema`, `chat_typed` |
| Contratos tipados | `arnaldo/llm/contracts.py` → `ContractModelRegistry` |

## Runtime

| O quê | Onde |
| --- | --- |
| Interface base | `arnaldo/runtime/base.py` → `RuntimeAdapter` |
| Runtime de grafo | `arnaldo/runtime/graph_runtime.py` → `GraphRuntime` |
| Runtime local | `arnaldo/runtime/local.py` → `LocalRuntime` |
| Runtime multi-agente | `arnaldo/runtime/multiagent.py` → `MultiAgentRuntime` |
| Sandbox | `arnaldo/runtime/sandbox.py` |

## Memória e Sessão

| O quê | Onde |
| --- | --- |
| MemoryStore | `arnaldo/memory/store.py` |
| Session manager | `arnaldo/session/manager.py` |
| Run store | `arnaldo/storage/run_store.py` |

## Outros

| O quê | Onde |
| --- | --- |
| Contratos IR | `arnaldo/contracts/ir.py` |
| Reality gap | `arnaldo/reality/gap.py` |
| Proatividade | `arnaldo/proactivity/manager.py` |

## Documentação

| O quê | Onde |
| --- | --- |
| Arquitetura formal | `docs/architecture.md` |
| Guia operacional | `docs/operations.md` |
| Backlog detalhado | `docs/backlog-mestre.md` |
| Changelog | `CHANGELOG.md` |

## Customização de Agentes (.github/)

| O quê | Onde |
| --- | --- |
| Instruções globais | `.github/copilot-instructions.md` |
| Diretrizes técnicas | `.github/instructions/project.instructions.md` |
| Padrões Python | `.github/instructions/python.instructions.md` |
| Padrões do grafo | `.github/instructions/graph.instructions.md` |
| Padrões da LLM | `.github/instructions/llm.instructions.md` |
| Padrões de teste | `.github/instructions/testing.instructions.md` |
| Captura de conhecimento | `.github/instructions/knowledge-capture.instructions.md` |
| Agente coordenador | `.github/agents/Arnaldo.agent.md` |
| Agente planner | `.github/agents/planner.agent.md` |
| Agente TDD | `.github/agents/tdd.agent.md` |
| Agente reviewer | `.github/agents/reviewer.agent.md` |
| Hook: quality (format+guard) | `.github/hooks/quality.json` |
| Script: post-edit | `.github/hooks/scripts/post_edit.py` |
| Script: session context | `.github/hooks/scripts/session_context.py` |
| Skill: arnaldo-context | `.github/skills/arnaldo-context/SKILL.md` |
| Prompts (10) | `.github/prompts/*.prompt.md` |
| Memória repo | `.github/memories/repo/` |

## Testes

| O quê | Onde |
| --- | --- |
| Todos os testes | `tests/` |
| Helpers LLM | `tests/support_llm.py` |
| Config pytest | `pyproject.toml` → `[tool.pytest.ini_options]` |
