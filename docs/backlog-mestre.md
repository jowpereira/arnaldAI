# ◉ Arnaldo — Backlog Mestre de Engenharia

> Documento operacional de trabalho. Objetivo: listar de forma detalhada
> tudo que pode e deve ser feito no produto, marcando o que já existe,
> o que está parcial e o que ainda falta.
>
> Data de referência: 2026-05-18.

---

## 1) Como Ler Este Documento

### 1.1 Legenda de status

- `[x]` implementado e validado com teste
- `[~]` implementado parcialmente (funciona, mas com lacunas explícitas)
- `[ ]` não implementado
- `[!]` risco técnico crítico que pode gerar regressão se ignorado

### 1.2 Convenções usadas

- Cada item tem um ID estável (`LLM-007`, `GRAFO-012`, etc.) para facilitar
  rastreio em commit, PR e issue.
- Todo item possui:
  - **Status**
  - **Evidência atual** (arquivo/trecho onde o comportamento existe)
  - **Lacuna real**
  - **Critério de aceite**
  - **Dependências**

### 1.3 Escopo (o que é “todas as tarefas possíveis” aqui)

“Todas” aqui significa “todas as frentes relevantes para levar o Arnaldo do
estado atual para um estado de produção auditável e evolutivo”, cobrindo:

- core do produto
- substrate cognitivo
- LLM + contratos estruturados
- runtime e execução
- governança/política
- memória/sessão
- observabilidade/custo
- qualidade (testes, lint, typecheck)
- segurança operacional
- documentação operacional

Não inclui tarefas de marketing, comercial, design de site institucional ou
operações corporativas fora do repositório.

---

## 2) Snapshot de Estado Atual

### 2.1 O que já está sólido

- `[x]` Camada de grafo tipado com bi-temporalidade, plasticidade e persistência
- `[x]` Camada LLM com roteamento por tiers e múltiplos estilos de API
- `[x]` `chat_typed` com `response_format=json_schema` e parse tipado via dataclass
- `[x]` `IntentCompiler` migrado para structured output tipado
- `[x]` `SynapseNode` já aceita `output_contract_model` e persiste `output_schema`
- `[x]` Sync de capabilities dinâmicas do `execution-graph` para o `CapabilityRegistry`
- `[x]` Kernel em modo `graph` já cria organização seed nativa de grafo (workflow vazio), delegando compilação do plano ao runtime
- `[x]` `GraphRuntime` persiste o plano realmente executado em `graph-workflow-materialized.json`, tornando o workflow materializado auditável por run
- `[x]` Execução em grafo isolada ao workflow materializado do run (sinapses legadas fora do plano não são executadas)
- `[x]` `GraphRuntime` aplica `sweep_decay` + retenção por run (`graph_retention_applied`)
- `[x]` Sincronização de capability do grafo sanitiza `module_path` nulo/`None`
- `[x]` Governança hard-disabled no modo `graph` via policy permissiva explícita
- `[x]` Bootstrap de contexto entre runs em modo grafo (`graph_context_bootstrapped`) a partir de memórias persistidas por sinapse
- `[x]` Blackboard versionado com namespace de ação/capability (`StepContext.output_history` + `snapshot_related_outputs`) usado para composição contextual entre sinapses
- `[x]` Agentes dinâmicos de tooling agora são escopados por capability (`toolsmith_<capability>` para forja/estabilização e `toolrunner_<capability>` para execução com `module_path`), com `workflow_composer` para composição de múltiplos fluxos de tooling
- `[x]` Pós-sync do grafo agora aciona auto-forja de capabilities dinâmicas sem `module_path` e persiste o caminho do módulo de volta no `execution-graph`
- `[x]` Runtime de grafo injeta e executa sinapses `execute_tooling` com `module_path` real (ferramenta dinâmica sem passar por LLM)
- `[x]` Runtime injeta automaticamente `compose_tooling` quando há múltiplas capabilities de tooling no mesmo workflow, permitindo composição dinâmica entre fluxos
- `[x]` `execute_tooling` recebe snapshot contextual enriquecido (outputs recentes, tool outputs, contexto relacionado e versão) para execução dinâmica orientada por histórico
- `[x]` Arestas `ACTIVATES` de tooling agora evitam encadeamento cruzado entre capabilities distintas e fazem pareamento por `capability_id` para estabilização/execução paralela
- `[x]` Sync kernel<-grafo agora persiste sinais de execução real (`real_execution_successes`, `last_tool_execution_status`) no `CapabilityRegistry` para continuidade entre runs
- `[x]` `execute_tooling` agora afeta maturidade da capability nos dois sentidos: reforça com sucesso real e penaliza com demotion quando `status` é não real (`not_implemented/failed/error/fallback`)
- `[x]` ToolForge passou a validar scaffolds de forma funcional (`py_compile` + `run(payload)`), reduzindo risco de módulo inválido já no nascimento

### 2.2 O que ainda é gargalo

- `[~]` Runtime em grafo agora possui blackboard versionado e namespace por ação/capability; falta evoluir o ranking contextual de heurístico para semântico (embedding/rerank)
- `[x]` Engine de execução tipada de `SynapseNode` integrada ao fluxo principal
- `[~]` Migração do pipeline `OrganizationIR` (AgentGenome efêmero) para `CognitiveGraph` avançou no runtime e no kernel; falta remover `OrganizationIR` como envelope de compatibilidade
- `[ ]` Política de bloqueio real (hoje permissiva em pontos críticos)
- `[ ]` Cost tracking real por usage/token no ledger

---

## 3) Backlog Detalhado por Trilha

## 3.1 Trilha LLM e Contratos Estruturados

### LLM-001 — Cliente Azure base com múltiplos estilos de API
- Status: `[x]`
- Evidência: `arnaldo/llm/client.py`, `arnaldo/llm/config.py`
- Lacuna: nenhuma estrutural
- Critério de aceite: chamadas `deployments`, `v1`, `responses` funcionais
- Dependências: credenciais Azure válidas

### LLM-002 — Roteamento task->tier explícito
- Status: `[x]`
- Evidência: `arnaldo/llm/router.py`, `tests/test_llm_integration.py`
- Lacuna: tuning fino por task real de produção
- Critério de aceite: mapa cobrindo tasks críticas e override funcionando

### LLM-003 — `chat_json` para compatibilidade transitória
- Status: `[x]`
- Evidência: `arnaldo/llm/client.py::chat_json`
- Lacuna: sem garantia forte de schema
- Critério de aceite: manter compatibilidade sem quebrar chamadas antigas

### LLM-004 — Structured outputs strict por dataclass
- Status: `[x]`
- Evidência: `arnaldo/llm/structured.py::dataclass_to_schema`
- Lacuna: ampliar casos avançados de typing (TypedDict/Protocol não cobertos)
- Critério de aceite: schema strict válido para casos de uso atuais

### LLM-005 — Envelope por estilo de API (`response_format` vs `text.format`)
- Status: `[x]`
- Evidência: `arnaldo/llm/structured.py::build_response_format_for_style`
- Lacuna: monitorar drift de APIs futuras
- Critério de aceite: payload correto em `deployments/v1/responses`

### LLM-006 — `chat_typed` com parse tipado e retry
- Status: `[x]`
- Evidência: `arnaldo/llm/client.py::chat_typed`
- Lacuna: política de retry/backoff ainda simples (apenas temperatura 0)
- Critério de aceite: sucesso tipado, retry em erro de parse, falha clara ao esgotar tentativas

### LLM-007 — Tratamento explícito de refusal
- Status: `[x]`
- Evidência: `LLMResponse.refusal`, parse em `client.py`
- Lacuna: telemetria agregada de recusas ainda não centralizada
- Critério de aceite: refusal não explode parsing e retorna evento discriminado

### LLM-008 — Observabilidade de latência/retries por tier
- Status: `[ ]`
- Evidência: inexistente
- Lacuna: não há métricas por chamada/erro/retry no client
- Critério de aceite: registrar duração, tentativas, motivo de fallback no trace/evidence
- Dependências: formato canônico de telemetria

### LLM-009 — Cache de schema compilado por nome/versão
- Status: `[ ]`
- Evidência: inexistente
- Lacuna: primeira chamada de schema novo pode ser cara no provider
- Critério de aceite: cache local com invalidação por hash do schema
- Dependências: desenho de cache em memória/arquivo

### LLM-010 — Catálogo central de contratos tipados
- Status: `[~]`
- Evidência: `arnaldo/llm/contracts.py::ContractModelRegistry`
- Lacuna: ainda falta versionamento formal por contrato (ex.: `name@vN`) e estratégia de migração
- Critério de aceite: registry com versionamento e validação de colisão de nomes
- Dependências: integração com runtime/engine

---

## 3.2 Trilha Intent/Task/Organization (Pipeline atual)

### PIPE-001 — IntentCompiler heurístico resiliente
- Status: `[x]`
- Evidência: `arnaldo/components/intent_compiler.py`
- Lacuna: heurísticas ainda simplificadas para casos ambíguos
- Critério de aceite: nunca quebrar sem LLM e sempre retornar IR válido

### PIPE-002 — Enriquecimento tipado no IntentCompiler
- Status: `[x]`
- Evidência: `IntentEnrichment` + `chat_typed` no compiler
- Lacuna: schema atual ainda pequeno (bom para robustez, mas pouco expressivo)
- Critério de aceite: campos enriquecidos sem quebrar fallback

### PIPE-003 — TaskCompiler com derivação semântica mais rica
- Status: `[~]`
- Evidência: `arnaldo/components/task_compiler.py`
- Lacuna: regras ainda pouco contextualizadas por domínio
- Critério de aceite: task IR com critérios e incertezas mais específicos por objetivo

### PIPE-004 — OrganizationGenerator com composição dinâmica de agentes
- Status: `[~]`
- Evidência: `arnaldo/components/organization_generator.py` (adição dinâmica de `clarifier`, `toolsmith`, `risk_auditor` e geração de múltiplos `design_tooling` por gap de capability); `arnaldo/kernel.py::_build_graph_native_agents` + `arnaldo/runtime/graph_runtime.py::_materialize_runtime_workflow` (toolsmith/toolrunner por capability + `workflow_composer` para composição dinâmica multi-tooling)
- Lacuna: ainda usa `AgentGenome` como contrato de orquestração e precisa evoluir para origem 100% `SynapseNode`
- Critério de aceite: migração para semântica de grafo persistente
- Dependências: trilha de execução com `CognitiveGraph`

### PIPE-005 — Migração `OrganizationIR` -> `CognitiveGraph` operacional
- Status: `[~]`
- Evidência: `GraphRuntime` executa via `CognitiveGraph`, persiste `execution-graph.msgpack`, enriquece/normaliza workflow dinamicamente (`_materialize_runtime_workflow`) e semeia fluxo quando `organization.workflow` vem vazio; o plano efetivamente materializado e executado agora é persistido em `graph-workflow-materialized.json`; `Kernel` em modo `graph` cria `OrganizationIR` seed com workflow vazio e agentes dinâmicos
- Lacuna: `OrganizationIR` ainda existe como envelope intermediário em vez de enviar o plano 100% grafo-first no contrato de runtime
- Critério de aceite: workflow executável via nós/arestas com estado plástico
- Dependências: engine de execução de synapses

---

## 3.3 Trilha Substrate Cognitivo (Graph)

### GRAFO-001 — Tipagem forte de nós/arestas
- Status: `[x]`
- Evidência: `arnaldo/graph/nodes.py`, `edges.py`
- Lacuna: nenhuma crítica
- Critério de aceite: invariantes preservados em adição/remoção

### GRAFO-002 — Bi-temporalidade em nós e arestas
- Status: `[x]`
- Evidência: `temporal.py`, uso em nodes/edges/store
- Lacuna: faltam utilitários de consulta temporal avançada por janela
- Critério de aceite: consulta de validade por tempo-evento e transação

### GRAFO-003 — Proveniência e baseline de confiança
- Status: `[x]`
- Evidência: `provenance.py`
- Lacuna: enriquecimento automático da proveniência no runtime ainda parcial
- Critério de aceite: toda inserção com origem explícita

### GRAFO-004 — Plasticidade Hebb-Stent (nós e arestas)
- Status: `[x]`
- Evidência: `plasticity.py`, `store.py::record_outcome`, `graph_runtime.py::_evolve_capability_nodes`
- Lacuna: falta estender feedback para mais tipos de aresta além de `FORGED_BY`
- Critério de aceite: feedback de execução muda pesos de forma auditável

### GRAFO-005 — Decay adaptativo por domínio
- Status: `[x]`
- Evidência: `plasticity.py::DecayPolicy`, `sweep_decay`
- Lacuna: calibration por dados reais ainda não feita
- Critério de aceite: stale/archive coerentes por classe de domínio

### GRAFO-006 — Retrieval híbrido (vetorial + estrutural + plasticidade)
- Status: `[x]`
- Evidência: `matching.py`, `store.py::match`
- Lacuna: falta benchmark em datasets reais
- Critério de aceite: recall útil superior ao baseline textual simples

### GRAFO-007 — Hierarquia de grafos (`GraphRef`)
- Status: `[x]`
- Evidência: `refs.py`, `store.py::attach_subgraph/resolve_subgraph`
- Lacuna: modo federado/snapshot ainda pendente
- Critério de aceite: OWNED/SHARED funcionando com prevenção de ciclos

### GRAFO-008 — `SynapseNode` com contratos explícitos no payload
- Status: `[x]`
- Evidência: `nodes.py::SynapseNode.specialist`
- Lacuna: execução desses contratos ainda não fechada no pipeline principal
- Critério de aceite: contratos influenciam execução e validação

### GRAFO-009 — `output_contract_model` persistido como schema strict
- Status: `[x]`
- Evidência: `nodes.py` grava `output_contract_model` + `output_schema`
- Lacuna: falta consumo runtime generalizado
- Critério de aceite: engine resolve modelo e aplica execução tipada

### GRAFO-010 — Registry de modelos para resolução robusta
- Status: `[~]`
- Evidência: `ExecutionEngine` integrado a `ContractModelRegistry`; `GraphRuntime` injeta registry explícito
- Lacuna: registry ainda local ao runtime (faltam políticas de namespace/versão cross-runtime)
- Critério de aceite: registro explícito com erro claro em conflito
- Dependências: engine de execução

---

## 3.4 Trilha Runtime e Execução

### RT-001 — Runtime local determinístico mínimo
- Status: `[x]`
- Evidência: `arnaldo/runtime/local.py`
- Lacuna: outputs ainda template/hardcoded
- Critério de aceite: continuidade do pipeline sem dependência externa

### RT-002 — MultiAgentRuntime placeholder
- Status: `[~]`
- Evidência: `arnaldo/runtime/multiagent.py`
- Lacuna: ainda delega comportamento local simplificado
- Critério de aceite: provider real com execução por agente

### RT-003 — Engine de execução de `SynapseNode` tipado
- Status: `[x]`
- Evidência: `arnaldo/graph/execution.py::ExecutionEngine`; `arnaldo/runtime/graph_runtime.py` (integração no fluxo principal)
- Lacuna: acompanhar tuning de `max_parallel` e fairness entre níveis em grafos grandes
- Critério de aceite: executar synapse com `chat_typed`, context write, refusal handling e feedback Hebb
- Dependências: registry de contratos/modelos

### RT-004 — Contexto de execução (blackboard) para composição
- Status: `[x]`
- Evidência: `arnaldo/graph/execution.py::StepContext` (`output_history`, `version`, `snapshot_related_outputs`, snapshots por ferramenta) + `ExecutionEngine._build_messages` (injeta “Contexto relacionado (acao/capability)”); `arnaldo/runtime/graph_runtime.py::_bootstrap_step_context` reidrata metadados (`action`, `agent_id`, `capability_id`, `channel`) e retorna `context_version`; cobertura em `tests/test_graph_execution.py::test_step_context_tracks_versioned_related_history` e `tests/test_graph_runtime_integration.py::test_graph_runtime_bootstraps_context_from_previous_memories`
- Lacuna: seleção contextual ainda heurística (ranking por action/capability/canal), sem embedding/reranking semântico
- Critério de aceite: leitura/escrita de outputs por `node_id`, inclusive recusas/erros
- Dependências: RT-003

### RT-005 — Execução sequencial por arestas `ACTIVATES`
- Status: `[x]`
- Evidência: `ExecutionEngine.execute_activates_parallel/execute_activates_reachable` com `allowed_node_ids`; `GraphRuntime` restringe execução ao conjunto materializado de `step_by_node`; conectividade dinâmica `ACTIVATES` usa pareamento por `capability_id` para tooling, evita arestas sequenciais cruzadas entre capabilities distintas e conecta `compose_tooling` como estágio de composição quando múltiplos fluxos estão ativos; cobertura em `tests/test_graph_runtime_integration.py::test_graph_runtime_ignores_legacy_seed_synapses_outside_current_workflow` e `tests/test_dynamic_features.py::test_graph_runtime_pairs_dynamic_branches_by_capability`
- Lacuna: falta scheduler distribuído para alto volume; concorrência atual é local por threadpool
- Critério de aceite: engine executa sequência validada, com proteção de ciclo, paralelismo por níveis e isolamento contra nós legados
- Dependências: RT-003, RT-004

### RT-009 — Retenção operacional do execution graph por run
- Status: `[x]`
- Evidência: `arnaldo/runtime/graph_runtime.py::_apply_graph_retention` (`sweep_decay`, limite de memória arquivada e remoção de excesso) + evento `graph_retention_applied`; cobertura em `tests/test_graph_runtime_integration.py::test_graph_runtime_records_retention_event`
- Lacuna: política ainda baseada em limites simples por contagem (sem heurística por valor semântico)
- Critério de aceite: cada run aplica decay e controla crescimento estrutural do grafo
- Dependências: GRAFO-005, RT-003

### RT-010 — Execução funcional de ferramentas dinâmicas via synapse
- Status: `[x]`
- Evidência: `ExecutionEngine` executa `module_path` quando `action=execute_tooling` (`arnaldo/graph/execution.py::_execute_tooling_synapse`) e injeta contexto enriquecido no payload da ferramenta (`recent_outputs`, `recent_tool_outputs`, `related_outputs`, `context_version`); `GraphRuntime` injeta passos `execute_tooling` a partir de capabilities com módulo conhecido (`_collect_tool_execution_targets`), adiciona `compose_tooling` para integração multi-tooling e usa o resultado de execução para ajustar maturidade/risco da capability (`_evolve_capability_nodes`); cobertura em `tests/test_graph_execution.py::test_execute_synapse_tooling_runs_dynamic_module_without_llm`, `tests/test_graph_execution.py::test_execute_synapse_tooling_receives_enriched_context_snapshot`, `tests/test_dynamic_features.py::test_graph_runtime_injects_execute_tooling_for_available_modules`, `tests/test_dynamic_features.py::test_graph_runtime_injects_compose_tooling_for_multiple_tooling_capabilities` e testes de promoção/demotion em `tests/test_dynamic_features.py`
- Lacuna: validação de conector ainda é funcional mínima (invocação `run(payload)`), sem suíte de integração externa por provedor
- Critério de aceite: runtime executa ferramenta real, registra sucesso/erro no contexto/evidence e não depende de LLM para esse passo
- Dependências: CAP-003, RT-003

### RT-006 — Fallback deterministico quando LLM indisponível
- Status: `[x]`
- Evidência: `ExecutionEngine._fallback_result`
- Lacuna: nenhuma crítica no fluxo principal atual
- Critério de aceite: runtime nunca trava pipeline por indisponibilidade de LLM
- Dependências: RT-003

### RT-006A — Política de neutralidade de plasticidade em fallback
- Status: `[x]`
- Evidência: fallback não chama `record_outcome` (não reforça/penaliza indevidamente)
- Lacuna: nenhuma crítica imediata
- Critério de aceite: runtime nunca trava pipeline por indisponibilidade de LLM
- Dependências: RT-003

### RT-007 — Propagação de refusal para Evidence Ledger
- Status: `[x]`
- Evidência: `arnaldo/runtime/graph_runtime.py` grava `record_type="llm_refusal"` no `evidence.jsonl`; cobertura em `tests/test_graph_runtime_integration.py`
- Lacuna: nenhuma crítica no fluxo principal atual
- Critério de aceite: refusal registrado com tipo/summary/payload padronizados
- Dependências: RT-003

### RT-008 — Integração kernel -> graph runtime
- Status: `[x]`
- Evidência: `ArnaldoKernel._build_runtime()` com default `graph`; CLI com `--runtime-mode graph`; artefato do run expõe `graph_workflow_materialized`; cobertura em `tests/test_graph_runtime_integration.py`
- Lacuna: nenhuma crítica para o objetivo atual (runtime funcional em grafo)
- Critério de aceite: runtime de grafo executável por default
- Dependências: RT-003/004/005

---

## 3.5 Trilha Policy/Governança/Segurança (Depriorizada por direção atual)

> Direção vigente: foco em funcionalidades de criação dinâmica e evolução de
> sinapses/ferramentas. Esta trilha segue documentada, mas fora do ciclo atual.

### GOV-001 — PolicyEngine básico
- Status: `[~]`
- Evidência: `arnaldo/components/policy_engine.py` (fora do caminho crítico no modo grafo) + `arnaldo/kernel.py::_build_graph_runtime_policy` (bypass explícito no `graph`)
- Lacuna: trilha de governança está deliberadamente despriorizada para foco funcional
- Critério de aceite: quando repriorizado, reativar enforcement real com razões auditáveis

### GOV-002 — Gating por capacidade crítica ausente
- Status: `[~]`
- Evidência: checkpoints no organization/policy
- Lacuna: gating ainda não interrompe de forma dura todos os fluxos externos
- Critério de aceite: operação externa negada sem capability e sem termos aceitos

### GOV-003 — Política de side effects por autonomia
- Status: `[~]`
- Evidência: ajustes no kernel/session
- Lacuna: enforcement incompleto em tempo de execução de ferramentas
- Critério de aceite: nenhuma ação externa fora do perfil permitido

### GOV-004 — Trilha de auditoria completa para decisões de policy
- Status: `[ ]`
- Evidência: parcial em evidence/trace
- Lacuna: não há esquema único de “decisão + justificativa + contexto”
- Critério de aceite: reconstrução causal ponto-a-ponto por `run_id`

### GOV-005 — Hardening para execução de ferramentas em sandbox
- Status: `[~]`
- Evidência: `runtime/sandbox.py` + manager
- Lacuna: falta matriz de permissões granular por capability
- Critério de aceite: capability declara escopo de FS/network/process enforceável

---

## 3.6 Trilha Capability Registry e Tool Forge

### CAP-001 — Registry de capabilities com resolução de missing
- Status: `[x]`
- Evidência: `capability_registry.py` (required ausente -> `missing`; optional ausente -> `degraded`)
- Lacuna: metadados de maturidade ainda simples
- Critério de aceite: resolução consistente de required/missing/degraded

### CAP-002 — ToolForge scaffold para gaps
- Status: `[~]`
- Evidência: `tool_forge.py` agora valida scaffold com smoke funcional (`py_compile` + import do módulo + execução de `run(payload)`), além de registrar `smoke_status` no metadata
- Lacuna: validação ainda local/sintética (sem chamada real a API/provedor externo)
- Critério de aceite: tool forjada testável e registrável sem intervenção manual extensa

### CAP-003 — Loop forge->test->promote maturidade
- Status: `[~]`
- Evidência: `GraphRuntime` promove `CapabilityNode` de tooling (`design_tooling`/`stabilize_tooling`/`execute_tooling`) e grava relação de proveniência `FORGED_BY`; para `execute_tooling`, a maturidade agora usa limiares de sucesso real (`real_execution_successes`) e também demote em execução não real/erro (`not_implemented/failed/error/fallback`); `ArnaldoKernel` sincroniza capabilities do grafo para o registry (`graph-capability-sync.json`), preservando `real_execution_successes` e `last_tool_execution_status`, e no pós-sync auto-forja capabilities dinâmicas sem `module_path` (`graph-tool-forge.json`) persistindo o `module_path` no `execution-graph`
- Lacuna: promoção/demotion ainda não depende de suíte de integração por provedor real (sinal principal ainda é execução local de `run(payload)` + smoke de scaffold)
- Critério de aceite: `draft -> tested -> trusted` guiado por testes e métricas

### CAP-004 — Catálogo de risco por capability
- Status: `[ ]`
- Evidência: campos existem, enforcement parcial
- Lacuna: risco não influencia plenamente policy/runtime
- Critério de aceite: capabilities high-risk exigem gates adicionais

---

## 3.7 Trilha Memória, Sessão e Aprendizagem

### MEM-001 — SessionManager funcional multi-turno
- Status: `[x]`
- Evidência: `arnaldo/session/*`
- Lacuna: retenção de sessão/memória semântica ainda simples, embora o `execution-graph` já tenha sweep/retention por run
- Critério de aceite: continuidade estável entre turnos

### MEM-002 — MemoryStore básico
- Status: `[~]`
- Evidência: `arnaldo/memory/store.py`
- Lacuna: sem indexação semântica e filtros avançados
- Critério de aceite: consulta por tipo/contexto e retenção controlada

### MEM-003 — Migração `MemoryStore` para `CognitiveGraph`
- Status: `[ ]`
- Evidência: roadmap e arquitetura já apontam
- Lacuna: dualidade de armazenamento ainda aberta
- Critério de aceite: uma única fonte de verdade para memória operacional

### MEM-004 — Aprendizagem procedural por evidência de runtime
- Status: `[ ]`
- Evidência: inexistente
- Lacuna: updates procedurais ainda pouco conectados ao resultado real
- Critério de aceite: padrões úteis emergem via feedback e ficam recuperáveis

---

## 3.8 Trilha Observabilidade, Custo e Operações

### OPS-001 — Trace e evidence por run
- Status: `[x]`
- Evidência: `runtime/local.py`, `kernel.py`, `RunStore`
- Lacuna: schema de eventos ainda pode ser normalizado
- Critério de aceite: eventos essenciais para replay causal

### OPS-002 — Normalização de usage tokens no client
- Status: `[x]`
- Evidência: parser de responses/chat no client
- Lacuna: sem agregador de custo financeiro
- Critério de aceite: usage consistente entre estilos de API

### OPS-003 — Cost tracking monetário
- Status: `[ ]`
- Evidência: inexistente (futuro em docs)
- Lacuna: não há custo por run/tier/task
- Critério de aceite: custo estimado no evidence + relatório final

### OPS-004 — Métricas de qualidade por fase do pipeline
- Status: `[ ]`
- Evidência: inexistente
- Lacuna: sem KPIs técnicos por componente
- Critério de aceite: dashboard de métricas mínimas (latência, erro, fallback, refusal)

### OPS-005 — Playbook de troubleshooting expandido
- Status: `[~]`
- Evidência: `docs/operations.md`
- Lacuna: falta casos de structured output/refusal/retry
- Critério de aceite: troubleshooting cobre incidentes recorrentes

---

## 3.9 Trilha Qualidade e Testes

### QA-001 — Testes de grafo (núcleo)
- Status: `[x]`
- Evidência: `tests/test_graph.py`, `tests/test_graph_refs.py`
- Lacuna: cenários de carga longa não cobertos
- Critério de aceite: invariantes de grafo protegidos por regressão

### QA-002 — Testes LLM integration
- Status: `[x]`
- Evidência: `tests/test_llm_integration.py`
- Lacuna: cenários extremos de payload ainda poucos
- Critério de aceite: configuração/parsing/roteamento protegidos

### QA-003 — Testes structured outputs (nova suíte)
- Status: `[x]`
- Evidência: `tests/test_structured.py`
- Lacuna: aumentar cenários de unions complexas
- Critério de aceite: schema, envelope, retry e refusal cobertos

### QA-004 — Testes da engine de execução de synapse
- Status: `[x]`
- Evidência: `tests/test_graph_execution.py`
- Lacuna: ampliar cenários de execução sequencial por arestas
- Critério de aceite: cobrir sucesso, refusal, fallback e erro LLM
- Dependências: RT-003

### QA-005 — Typecheck abrangente além de `graph/`
- Status: `[ ]`
- Evidência: `operations` cita mypy só para `arnaldo/graph/`
- Lacuna: restante do código sem gate de tipos estritos
- Critério de aceite: pipeline CI com mypy nas áreas críticas

### QA-006 — Testes de integração do runtime em grafo no kernel
- Status: `[x]`
- Evidência: `tests/test_graph_runtime_integration.py`
- Lacuna: ampliar cenários com client LLM real/mocked por action específica
- Critério de aceite: default graph validado + refusal persistido no ledger

### QA-007 — Testes de funcionalidades dinâmicas (agentes/ferramentas/sinapses)
- Status: `[x]`
- Evidência: `tests/test_dynamic_features.py`
- Lacuna: ampliar cobertura para grafos muito grandes (>10^4 nós)
- Critério de aceite: criação dinâmica de agentes, tool forge sem termos e enriquecimento do grafo validados

---

## 3.10 Trilha Documentação e Governança de Conhecimento

### DOC-001 — Arquitetura canônica atualizada
- Status: `[x]`
- Evidência: `docs/architecture.md`
- Lacuna: manter sincronia com código a cada entrega grande
- Critério de aceite: seção de estado de implementação sem divergência factual

### DOC-002 — Operações com exemplos atualizados para `chat_typed`
- Status: `[x]`
- Evidência: `docs/operations.md`
- Lacuna: acrescentar exemplos de refusal/retry em troubleshooting
- Critério de aceite: caminho feliz + falha explicados

### DOC-003 — Backlog mestre versionado e rastreável
- Status: `[x]`
- Evidência: este documento
- Lacuna: precisa virar ritual de atualização por ciclo
- Critério de aceite: cada task relevante com status e owner técnico

### DOC-004 — ADRs para decisões estruturais grandes
- Status: `[ ]`
- Evidência: inexistente
- Lacuna: decisões de arquitetura podem perder contexto histórico
- Critério de aceite: 1 ADR por decisão de impacto em contratos/runtime/store

---

## 4) Ordem Recomendada de Execução (Próximos Ciclos)

## Ciclo A (imediato, alto impacto)

1. GRAFO-010 / LLM-010 — registry canônico de modelos/contratos
2. PIPE-005 — Reduzir dependência de `OrganizationIR` e gerar fluxo nativamente no grafo
3. CAP-003 — Loop forge->test->promote de maturidade
4. OPS-003 — Cost tracking monetário por run/tier
5. RT-002 — MultiAgentRuntime real com execução distribuída por agente

## Ciclo B (integração de pipeline)

1. MEM-003 — Migração `MemoryStore` -> `CognitiveGraph`
2. PIPE-004 — Evoluir composição dinâmica de agentes por domínio/objetivo
3. OPS-004 — Métricas de qualidade por fase do pipeline
4. QA-005 — Typecheck abrangente além de `graph/`

## Ciclo C (produção e escala)

1. OPS-003 — cost tracking real
2. OPS-004 — métricas de qualidade
3. CAP-003 — promoção de maturidade de ferramentas baseada em evidência
4. MEM-003 — unificação de memória no grafo

---

## 5) Riscos e Nuances que Mudam Prioridade

- `[!]` Se OPS-003 não existir, otimização de custo vira opinião, não medição.
- `[!]` Se PIPE-005 atrasar demais, teremos duplicidade arquitetural (`OrganizationIR` vs `CognitiveGraph`) por tempo excessivo.
- `[!]` Se CAP-003 não fechar com validação real de conector, promoção de maturidade seguirá baseada em sinal fraco.

Nuance importante:

- O runtime em grafo já é o padrão e o grafo de execução já persiste entre runs
  da sessão. O próximo salto é remover `OrganizationIR` como origem primária e
  gerar o plano diretamente em estrutura de grafo.

---

## 6) Checklist de Controle de Qualidade para Cada Entrega

Antes de marcar qualquer item como `[x]`, exigir:

1. Teste automatizado cobrindo caminho feliz e ao menos um caminho de falha.
2. Atualização de docs afetadas (`architecture.md`, `operations.md`, este backlog).
3. Sem regressão na suíte completa (`uv run pytest`).
4. Evidência de integração real (não apenas função isolada sem uso).
5. Rastreabilidade de decisão quando houver trade-off estrutural.
