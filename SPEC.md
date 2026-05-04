# Arnaldo Execution Kernel — Detailed Specification

## 1. Propósito
- Definir, em nível operacional, como o Arnaldo transforma intenções humanas em execuções verificáveis, mantendo governança e autonomia graduada.
- Estabelecer contratos claros entre componentes atuais (`IntentCompiler`, `TaskCompiler`, `CognitiveControlPlane`, `OrganizationGenerator`, `PolicyEngine`, `LocalRuntime`, `RunStore`) e os módulos que precisam nascer para cumprir a visão de "compilador de organizações cognitivas".
- Guiar o desenvolvimento da próxima geração do núcleo, onde Arnaldo executa tarefas abertas, conversa com humanos quando necessário, coordena subagentes e aciona ferramentas externas com segurança.
- Refletir que o Arnaldo opera como **worker genérico único**: um kernel configurável que instancia agentes efêmeros e ferramentas sob demanda em cada run, dispensando orquestração manual de múltiplos serviços residentes.

## 2. Objetivos Principais
1. **Autonomia graduada real**: permitir que o usuário selecione níveis de autonomia que desbloqueiam permissões e graus de iniciativa.
2. **Coordenação multiagente efêmera**: gerar, executar e desmontar organizações temporárias, sem exigir agentes persistentes fora do kernel.
3. **Interação humana contínua**: manter um canal de diálogo onde Arnaldo esclarece dúvidas, solicita aprovação e entrega progresso.
4. **Execução verificável**: cada passo gera evidências rastreáveis, armazenadas em ledger auditável.
5. **Evolução adaptativa**: registrar experiências para retroalimentar memória, reputação e melhoria de topologias/capacidades.

## 3. Fora de Escopo Imediato
- Monetização e billing.
- Integrações proprietárias sem disponibilidade pública de API.
- Interface gráfica. O foco inicial é CLI + APIs.
- Persistência de dados pessoais sensíveis sem consentimento explícito.

## 4. Atores e Stakeholders
- **Usuário operador**: pessoa que declara intenções, recebe resultados, concede aprovações.
- **Arnaldo Kernel**: orquestrador que compila intenção, decide modos cognitivos e delega execução.
- **Agentes principais**: entidades temporárias com objetivo/contrato definido (framer, planner, critic, etc.).
- **Subagentes/Workers**: processos ou ferramentas específicos que executam subtarefas ou chamadas externas.
- **Policy Owner**: responsável por configurar limites de autonomia, orçamentos e políticas.
- **Auditor**: revisa evidências e trilhas de execução.

## 5. Termos Relevantes
- **Intent IR**: contrato declarativo da intenção estruturada.
- **Task IR**: representação intermediária com goal, deliverables, critérios e riscos.
- **Organization IR**: grafo efêmero de agentes, workflow, checkpoints e permissões.
- **Capability Registry**: catálogo das capacidades efetivamente disponíveis (internas + externas).
- **Policy Decision**: veredito sobre permissões dadas as restrições de autonomia.
- **Evidence Ledger**: armazenamento append-only de eventos de execução.

## 6. Visão Geral de Arquitetura
```
Usuário ↔ Interface Conversacional ↔ Intent Compiler → Task Compiler
                                          ↓                 ↓
                               Cognitive Control Plane    Capability Registry
                                          ↓                 ↓
                          Organization Generator → Policy Engine → Runtime Adapter
                                          ↓                                   ↓
                                 Memory System ← Evidence Ledger ← Runtime Eventos
                                          ↓
                                   Evolution Engine / Reality Gap Detector
```
- **Plano de Controle Cognitivo** coordena quais modos mentais e topologias usar.
- **Plano de Execução** materializa agentes, agenda passos e roda runtime (local ou via provider externo).
- **Plano de Governança** aplica políticas, aprovações e logs de auditoria.

## 7. Componentes e Requisitos Detalhados
### 7.1 Interface Conversacional
- Fornece CLI e API.
- Mantém sessão de diálogo com o usuário, exibindo progresso, bloqueios e perguntas.
- Deve puxar histórico de memória para contextualizar novas intenções.

### 7.2 Intent Intake & Compiler
- Entrada: texto natural + metadados (restrições, preferências, nível de autonomia desejado).
- Saída: `IntentIR` com campos:
  - `id`, `version`, `created_at`.
  - `original_request`, `desired_state`, `primary_goal`.
  - `autonomy`: `{mode: manual|assistido|autonomo, max_level: int, delegation: "allowed"|"restricted"}`.
  - `constraints`: granular (rede, filesystem, mensagens externas, orçamento).
  - `inferred_requirements`: lista context-aware (usar LLM/ontologia para extrair entregáveis obrigatórios).
  - `open_questions`: itens classificados (`blocking: bool`, `confidence: float`).
  - `signals`: métricas numéricas (ambiguidade, impacto externo, dados sensíveis, irreversibilidade).
- Deve integrar um módulo de NLU para mapear intents conhecidas e sugerir planos iniciais.

### 7.3 Task Compiler
- Constrói `TaskIR` com seções:
  - `goal`: `{statement, type, success_state}`.
  - `context`: origem (CLI, API, automação), escopo (generic, domain-specific).
  - `deliverables`: lista dinâmicas com `id`, `schema`, `acceptance_criteria`.
  - `success_criteria`: `[{id, description, metric?, evaluation_mode}]`.
  - `autonomy`: herdado do Intent IR, com ajustes baseados em políticas globais.
  - `risk`: mapeia sinais para níveis (low/medium/high) + justificativas.
  - `capability_needs`: resultante de matching entre deliverables e capacidades.
  - `uncertainty`: lista com `question`, `blocking`, `owner` (agente ou humano), `resolution_strategy`.
- Task Compiler registra resumo no Evidence Ledger.

### 7.4 Cognitive Control Plane
- Entrada: `TaskIR`, histórico de memória, políticas.
- Saída: `CognitiveDecision` com campos ampliados:
  - `selected_modes`: combinações (p.ex. `parallel_exploration`, `debate_adversarial`, `tool_forge`, `simulation`).
  - `confidence_threshold`: mínimo de confiança antes de finalizar.
  - `human_checkpoint_strategy`: quando interromper para validação humana.
  - `communication_plan`: periodicidade de atualização para o usuário.
  - `budget`: horas, tokens, custos monetários.
- Deve avaliar heurísticas: se risco alto → adiciona `reality_gap_detection`; se capacidade faltante crítica → agenda `tool_forge`.

### 7.5 Capability Registry & Tool Forge
- **Registry**: fonte de verdade das capacidades instaladas.
  - Estrutura de entrada: `Capability {id, name, description, provider, inputs, outputs, cost, policies, health}`.
  - API para registrar/atualizar capacidades (manual ou gerado por Tool Forge).
- **Resolver**: retorna `available`, `missing`, `degraded` (capacidade instalada mas com saúde baixa) e `suggested_substitutes`.
- **Tool Forge**: pipeline para sintetizar ou importar nova capacidade quando uma necessidade obrigatória está ausente.
  - Passos: diagnosticar lacuna, propor ferramenta (LLM + templates), gerar spec, validar em sandbox, registrar capacidade com metadados e testes.
  - Interage com usuário quando autonomia < nível requerido para criação automática.

### 7.6 Organization Generator
- Cria `OrganizationIR` com topologia apropriada.
- Componentes obrigatórios:
  - `agents`: lista de `AgentGenome` contendo `objective`, `epistemic_style`, `required_capabilities`, `forbidden_capabilities`, `communication_channels`.
  - `workflow`: grafo direcionado (não apenas lista linear). Cada `step` tem `id`, `agent_id`, `action`, `inputs`, `outputs`, `policy_checks`.
  - `handoff_rules`: critérios para transições (ex.: `step_a` success → `step_b`, failure → `critic`).
  - `communication_canvas`: onde logs/conversas dos agentes ficam acessíveis.
  - `human_checkpoints`: com `reason`, `blocking`, `prompt_template` para solicitar intervenção.

### 7.7 Policy Engine
- Avalia `OrganizationIR` + `TaskIR` + políticas globais.
- Gere `PolicyDecision` com:
  - `allowed`: bool.
  - `approval_required`: bool.
  - `effective_constraints`: granular (rede, execução de código, escrita em disco, mensagens externas, transações financeiras, ferramentas específicas).
  - `escalation_plan`: contatos, canais, limites de tempo.
  - `audit_hooks`: quais eventos precisam de evidência reforçada (ex. exportar dados).
- Atualiza ledger com decisão e justificativas.

### 7.8 Runtime Adapter
- Deve suportar múltiplos backends:
  1. **Local deterministic** (herda `LocalRuntime` para testes).
  2. **LLM provider**: orquestra agentes em providers externos (Microsoft Agent Framework, OpenAI Swarm, etc.).
  3. **Custom executor**: scripts/containers especializados.
- Features:
  - Loop de execução: `prepare → execute step → capture outputs → validate → record evidence → decide next action`.
  - Comunicação entre agentes via canal compartilhado (ex: `agent_bus.jsonl`).
  - Suporte a subagentes disparados dinamicamente (ex.: `agent.spawn("researcher")`).
  - Regras de backoff/retry.
  - Integração com `Reality Gap Detector` para comparar plano vs realidade.

### 7.9 Memory System
- Camadas:
  1. **Episódica**: histórico de runs, trace, evidence.
  2. **Semântica**: embeddings de artefatos, decisões, conclusões.
  3. **Procedimental**: receitas aprovadas, playbooks, topologias funcionais.
  4. **Negativa**: falhas, riscos, comportamentos proibidos.
- APIs:
  - `memory.store(event)` → guarda dados com metadado.
  - `memory.retrieve(query, filters)` → retorna itens relevantes.
  - `memory.recommend_capabilities(task)` → sugere capacidades com base em runs anteriores.

### 7.10 Evidence Ledger
- Formato append-only com possibilidade de verificação (hash em cadeia).
- Registro mínimo por evento:
  - `id`, `timestamp`, `run_id`, `task_id`, `agent_id?`, `event_type`, `summary`, `payload`, `human_involved`.
- Deve permitir export para auditoria externas.

### 7.11 Reality Gap Detector
- Compara espec (Task IR + success criteria) com outputs reais.
- Calcula métricas (`coverage`, `confidence`, `gaps`).
- Quando gap crítico identificado:
  - avisa `critic` agent;
  - registra evidência com status `gap_detected`;
  - em modo manual/assistido, solicita instruções ao humano.

### 7.12 Evolution Engine
- Analisa execuções passadas para promover/demitir topologias e genomas.
- Métricas chave: tempo, satisfação humana, conformidade com critérios, ocorrência de gaps, intervenções obrigatórias.
- Atualiza catálogo de templates (p.ex. pipeline vs paralelo) com notas de eficácia.

## 8. Modos de Autonomia
| Modo       | Permissões padrão                                   | Regras de intervenção                                       |
|-----------|------------------------------------------------------|-------------------------------------------------------------|
| `manual`  | Somente leitura, sem efeitos externos, subagente bloqueado | Cada etapa requer confirmação humana.                        |
| `assistido` | Rede leitura, ferramentas diagnósticas, subagentes limitados | Checkpoints em etapas de risco; humano pode delegar exceções. |
| `autonomo` | Ferramentas externas permitidas (dentro de políticas), criação de subagentes, escrita controlada | Humano acionado apenas em falhas críticas ou orçamento excedido. |
- Policy Engine ajusta permissões com base em confiança histórica (memória negativa reduz limites).

## 9. Protocolos de Interação Humana
1. **Kick-off**: coleta de intenção e restrições.
2. **Check-ins programados**: baseados em `communication_plan` (ex.: a cada n passos ou minutos).
3. **Escalonamento automático**: gatilhos para chamar humano (incerteza `blocking`, falta de capability crítica, violação de orçamento, reality gap grave).
4. **Feedback final**: usuário avalia entrega → memórias atualizadas (sucesso/falha, satisfação, notas).

## 10. Comunicação Entre Agentes
- Canal padronizado (`agent_bus.jsonl`): cada mensagem inclui `from`, `to`, `intent`, `payload`, `confidence`.
- Subagentes podem solicitar habilidades extras via `capability_request`. Policy Engine decide se aprova automaticamente conforme autonomia.
- Logs de conversa são evidências obrigatórias.

## 11. Modelagem de Dados
- **Intent IR (v1)**
```json
{
  "version": "intent-ir/v1",
  "id": "intent_abcd1234",
  "created_at": "2026-05-04T15:00:00Z",
  "original_request": "...",
  "desired_state": "...",
  "primary_goal": "create_or_generate",
  "autonomy": {"mode": "assistido", "max_level": 2, "delegation": "allowed"},
  "constraints": {"network": "read", "filesystem": "sandbox", "external_side_effects": "approval_required"},
  "inferred_requirements": ["..."],
  "open_questions": [{"question": "...?", "blocking": true, "confidence": 0.4}],
  "signals": {"ambiguity": 2, "data_sensitivity": 0}
}
```
- Estruturas equivalentes para Task IR, Organization IR, Policy Decision e Evidence devem ser versionadas e validadas contra JSON Schema.

## 12. Persistência
- `RunStore` evoluirá para aceitar drivers (filesystem, S3, database).
- Cada run gera diretório com:
  - `intent-ir.json`
  - `task-ir.json`
  - `cognitive-decision.json`
  - `capability-resolution.json`
  - `organization-ir.json`
  - `policy-decision.json`
  - `artifact/` (pode conter múltiplos arquivos)
  - `trace.jsonl`
  - `evidence.jsonl`
  - `agent_bus.jsonl`

## 13. Observabilidade
- Métricas: tempo por etapa, número de intervenções humanas, lacunas detectadas, custo.
- Alerts: runtime falhou, capacidade indisponível, policy violada.
- Dashboards (futura UI) baseados nestes logs.

## 14. Segurança e Governança
- Controle de acesso baseado em papéis (operador, policy owner, auditor).
- Sanitização de entradas/artefatos (remover segredos, PII).
- Hashing de evidências e resultados para garantir integridade.
- Logs imutáveis para decisões de política.

## 15. Fluxos de Falha e Recuperação
1. **Capability ausente** → Tool Forge tenta gerar; se autonomia baixa, pede aprovação humana.
2. **Erro em runtime** → tenta fallback (outro agente, modo manual). Registra trace com `event_type = runtime_error`.
3. **Policy negou ação** → comunica usuário com opções: ajustar autonomia, conceder exceção, abortar.
4. **Reality gap crítico** → critic agent recomenda revisão, runtime pausa se modo manual/assistido.

## 16. Testes e Validação
- Unit tests para cada componente.
- Contract tests para IRs (JSON Schema).
- Simulações multiagente com cenários curtos (p.ex. gerar plano de produto) e longos (execução em múltiplas etapas).
- Testes de regressão para autonomia: modo manual não exec rutinas externas; modo autônomo deve executar com logs completos.

## 17. Roadmap de Entrega
1. **Sprint 1**: JSON Schema para IRs + Policy Engine configurável + Interface conversacional com check-ins.
2. **Sprint 2**: Runtime híbrido (local + stub multiagente) + canal de comunicação entre agentes + Evidence Ledger com hashing.
3. **Sprint 3**: Memory System (episódica + semântica) + Reality Gap Detector básico.
4. **Sprint 4**: Tool Forge MVP + autonomia escalonada (permissões dinâmicas).
5. **Sprint 5**: Evolution Engine inicial + dashboards de observabilidade.

## 18. Questões em Aberto
- Qual provider multiagente será priorizado (Microsoft Agent Framework, OpenAI Swarm, construção própria)?
- Como orquestrar orçamentos monetários (p.ex. limite de tokens)?
- Precisamos de autenticação multiusuário no CLI? Ou apenas em API?
- Qual é o SLA desejado para runs autônomos? Há limite de duração?
- Como lidar com dados confidenciais em memórias? Precisaremos de criptografia em repouso e em trânsito?

## 19. Referências
- README.md (manifesto original).
- Código atual em `arnaldo/` (núcleo determinístico).
- Pesquisas internas de frameworks agenticos (2025-2026).

## 20. Apêndice Visual

### 20.1 Camadas do Kernel Cognitivo
```
+----------------------+----------------------+----------------------+----------------------+
|      Intenção        | Coordenação Cognitiva|        Execução      |   Evidência & Memória|
| Usuário → Interface  | Control Plane ↔      | Organization Generator| Evidence Ledger ↔    |
|   → Intent → Task    | Capability Registry  |   → Runtime/Tool Forge| Memory/Evolution/Gaps|
+----------------------+----------------------+----------------------+----------------------+
```

### 20.2 Fluxo Conversacional e Operacional
```
Usuário
  │
  ▼
Interface Conversacional ⇄ Atualizações
  │
  ▼
Intent Compiler → Task Compiler → Cognitive Control Plane
                                   │
                                   ▼
                        Capability Registry ↔ Policy Engine
                                   │
                                   ▼
                         Organization Generator
                                   │
                                   ▼
Runtime Adapter ⇄ Subagentes/Tool Forge
      │                    │
      ▼                    ▼
Evidence Ledger ⇄ Memory System ⇄ Evolution/Gaps
```

### 20.3 Decisão de Autonomia
```
               +---------------------+
               | Intenção Recebida   |
               +----------+----------+
                          │
                          ▼
               +---------------------+
               | Selecionar Modo     |
               | manual/assist/aut   |
               +----+-----------+----+
                    │           │
        +-----------+           +-----------+
        ▼                                   ▼
  +-----------+                       +-----------+
  |  Manual   |                       | Assist/Aut|
  +-----+-----+                       +-----+-----+
        │                                   │
        ▼                                   ▼
Policy bloqueia efeitos           Policy libera efeitos graduais
Runtime local determinístico      Runtime + Subagentes/Tool Forge
Checkpoints obrigatórios          Checkpoints dinâmicos / exceções
        │                                   │
        ▼                                   ▼
 Interação humana contínua        Interação sob gatilhos críticos
```

