# Changelog
Todas as mudanças relevantes do projeto serão documentadas neste arquivo.

Este projeto segue:
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
- [Semantic Versioning](https://semver.org/spec/v2.0.0.html) estritamente

## Política SemVer (estrita)
- `MAJOR (X.0.0)`: mudanças incompatíveis de API/contrato/comportamento esperado.
- `MINOR (0.X.0)`: novas funcionalidades compatíveis com versões anteriores.
- `PATCH (0.0.X)`: correções e ajustes compatíveis, sem nova funcionalidade pública.

## [Unreleased]
### Added
- Plasticidade operacional de arestas `ACTIVATES` no `ExecutionEngine`, com reforço/degradação por outcome real das transições executadas.
- Criação/reforço dinâmico de arestas `COLLABORATED_WITH` entre branches paralelos bem-sucedidos, materializando colaboração entre sinapses.
- `MultiAgentRuntime` funcional com execução distribuída por ondas de agentes, paralelismo por família de ação e `agent_bus` com eventos de ciclo de vida.
- Suíte `tests/test_multiagent_runtime.py` cobrindo paralelismo por onda, execução dinâmica de ferramenta por `module_path` e fallback de módulo ausente.

### Changed
- CLI simplificada para execução sempre em `graph` com modo real estrito por padrão (sem toggle por variável de ambiente para fallback).
- Saída da CLI reformulada para resumo operacional rico da run (topologia, contadores de workflow/evidência/trace, capacidades e caminhos de artefatos).
- `IntentCompiler`, `GraphRuntime` e `ExecutionEngine` agora usam `strict_real=True` por padrão, exigindo LLM configurada no fluxo principal.
- `GraphRuntime` agora materializa workflow leve para mensagens conversacionais de saudação (`open_ended_execution`) em 1 etapa (`draft_artifact`) com tier `fast`.
- `ExecutionEngine` passou a aplicar hints por synapse (`max_tokens`, `timeout`, `temperature`, `max_retries`, `reasoning_effort/summary`) diretamente na chamada `chat_typed`.

## [0.2.0] - 2026-05-18
### Added
- Camada LLM com roteamento por tiers, `chat_typed` e structured outputs com `response_format=json_schema`.
- Registro e resolução de contratos tipados para saídas estruturadas.
- Substrate cognitivo de grafo (`CognitiveGraph`) com nós/arestas tipados, temporalidade, plasticidade e referências de subgrafos.
- Engine de execução de sinapses com execução por arestas `ACTIVATES`, fallback e contexto de execução.
- Runtime em modo grafo com materialização dinâmica de workflow por run.
- Criação dinâmica de agentes de tooling por capability (`toolsmith_*`, `toolrunner_*`, `workflow_composer`).
- Execução funcional de ferramentas dinâmicas (`execute_tooling`) com `module_path`.
- Composição dinâmica de workflows de tooling (`compose_tooling`) quando há múltiplas capabilities no mesmo fluxo.
- Persistência de plano materializado por run em `graph-workflow-materialized.json`.
- Módulos de sessão, memória e análise de gap de realidade.
- ToolForge com smoke funcional (`py_compile` + import + execução de `run(payload)`).
- Suíte de testes cobrindo LLM, grafo, execução de sinapses, runtime de grafo e funcionalidades dinâmicas.

### Changed
- `ArnaldoKernel` passa a operar com runtime de grafo como caminho principal.
- `core.run(...)` e CLI aceitam parâmetros de sessão (`session_id`, `terms_accepted`) no fluxo atual.
- Sincronização de capabilities entre grafo e registry com metadados de execução real (`real_execution_successes`, `last_tool_execution_status`).
- `pyproject.toml` atualizado para `0.2.0`, Python `>=3.12`, dependências e extras organizados por domínio.
- Documentação consolidada em `docs/architecture.md`, `docs/operations.md` e `docs/backlog-mestre.md`.

### Removed
- `SPEC.md` removido.
- `docs/arquitetura.md` e `docs/minimo.md` substituídos pela nova documentação canônica.

## [0.1.0] - 2026-05-04
### Added
- Primeira versão funcional do núcleo do Arnaldo com componentes iniciais de compilação/execução.
