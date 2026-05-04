# Arnaldo

**Arnaldo é um sistema operacional cognitivo para transformar intenção humana em execução verificável.**

Ele não é apenas um chatbot, nem apenas um agente com ferramentas, nem apenas uma camada de multiagentes. A tese central do projeto é mais ambiciosa:

> O usuário declara uma realidade desejada.  
> O Arnaldo compila essa intenção em uma organização temporária de agentes, ferramentas, políticas, memória, evidências e critérios de sucesso.  
> A organização executa, valida, aprende e desaparece, deixando artefatos, provas e novas capacidades para usos futuros.

Em vez de pensar em "um assistente que responde", o Arnaldo deve ser pensado como um **compilador de trabalho**.

```text
Pedido humano
  -> intenção estruturada
  -> representação intermediária de trabalho
  -> grafo de capacidades
  -> organização temporária de agentes
  -> execução observável
  -> validação adversarial
  -> artefatos entregáveis
  -> memória e evolução do sistema
```

### Operação Como Worker Genérico

- Existe **um único kernel** configurável que roda como worker genérico. Ele recebe intenções, aplica políticas e orquestra todo o fluxo cognitivo em um processo só.
- Os **agentes e ferramentas são instanciados sob demanda** para cada execução. Eles vivem apenas durante aquela organização temporária e desaparecem ao final, deixando artefatos e evidências.
- Não é necessário manter um enxame permanente de agentes. O usuário cuida da intenção, autonomia e restrições; o Arnaldo decide quantos agentes efêmeros criar, quais ferramentas invocar e em que ordem.
- O runtime local pode ser substituído por provedores externos conforme autonomia/política, mas continua existindo como guardião único dos contratos e do ledger.

O objetivo é criar uma plataforma capaz de executar tarefas abertas, ambíguas e compostas, mas sem cair no caos típico de sistemas agenticos totalmente livres. O Arnaldo deve ser genérico, mas governado; autônomo, mas auditável; expansível, mas seguro.

---

## Sumário

- [Visão](#visão)
- [Tese](#tese)
- [Norte Estético E Técnico](#norte-estético-e-técnico)
- [O Que Torna O Arnaldo Sobre-Humano](#o-que-torna-o-arnaldo-sobre-humano)
- [O Que O Arnaldo Não É](#o-que-o-arnaldo-não-é)
- [Princípios De Design](#princípios-de-design)
- [Arquitetura Geral](#arquitetura-geral)
- [Cognitive Control Plane](#cognitive-control-plane)
- [Fluxo De Execução](#fluxo-de-execução)
- [Intent Compiler](#intent-compiler)
- [Task IR](#task-ir)
- [Capability Graph](#capability-graph)
- [Agent Genome](#agent-genome)
- [Organization Generator](#organization-generator)
- [Agent Runtime](#agent-runtime)
- [Tool Forge](#tool-forge)
- [Evidence Ledger](#evidence-ledger)
- [Policy Engine](#policy-engine)
- [Memory System](#memory-system)
- [Evolution Engine](#evolution-engine)
- [Reality Gap Detector](#reality-gap-detector)
- [Simulation Engine](#simulation-engine)
- [Modos De Interface](#modos-de-interface)
- [Autonomia Graduada](#autonomia-graduada)
- [Exemplo Completo](#exemplo-completo)
- [MVP Proposto](#mvp-proposto)
- [Roadmap](#roadmap)
- [Glossário](#glossário)

---

## Visão

O Arnaldo deve permitir que uma pessoa diga:

> "Quero lançar um produto, validar demanda, criar a landing page, montar uma campanha, falar com os primeiros leads e medir os resultados."

E receba não apenas um plano em texto, mas uma execução organizada:

- pesquisa de mercado com fontes;
- hipóteses de público;
- proposta de valor;
- landing page;
- lista de leads;
- sequência de abordagem;
- plano de experimentos;
- métricas de sucesso;
- riscos;
- decisões justificadas;
- próximos passos;
- registro de evidências;
- aprendizado reaproveitável.

O Arnaldo deve conseguir fazer isso para muitas classes de problema: desenvolvimento de software, pesquisa estratégica, automação operacional, criação de conteúdo, análise documental, planejamento comercial, estudos técnicos, organização pessoal, execução de projetos e descoberta de oportunidades.

A visão final é que o usuário não gerencie prompts, ferramentas ou agentes. O usuário gerencia intenção, restrições, autonomia e critérios de sucesso.

---

## Tese

O mercado já está convergindo para agentes com ferramentas, workflows, handoffs, memória, execução durável e observabilidade. Isso deixará de ser diferencial.

O diferencial do Arnaldo é a camada acima dos frameworks:

```text
Frameworks resolvem:
  "como rodar agentes?"

Arnaldo resolve:
  "quais agentes devem existir?"
  "por que devem existir?"
  "com quais ferramentas?"
  "com quais permissões?"
  "em qual organização?"
  "com quais critérios de saída?"
  "com quais evidências?"
  "com qual memória?"
  "com qual evolução depois da execução?"
```

O Arnaldo deve ser menos parecido com um "super assistente" e mais parecido com um **kernel cognitivo**.

Ele recebe intenções, compila trabalho e cria organizações temporárias sob demanda.

---

### A Barra Anti-Commodity

Uma decisão de produto só deve entrar no núcleo do Arnaldo se ela continuar relevante mesmo quando todos os frameworks tiverem:

- agentes declarativos;
- workflows visuais;
- memória integrada;
- ferramentas via MCP;
- handoffs;
- multiagente;
- observabilidade;
- execução durável;
- agentes no-code.

Se uma funcionalidade puder ser reduzida a "o framework X também faz", ela não é o centro do Arnaldo. Ela pode ser infraestrutura, mas não tese.

O centro do Arnaldo é a capacidade de decidir:

```text
qual forma de pensamento usar,
qual organização criar,
qual evidência exigir,
qual risco aceitar,
qual ferramenta permitir,
qual memória consultar,
qual capacidade criar,
quando parar,
quando perguntar,
quando executar,
quando discordar do usuário.
```

Essa camada é mais importante do que qualquer agente individual.

---

## Norte Estético E Técnico

O Arnaldo deve ser elegante, eficiente e moderno não apenas na interface, mas na estrutura interna.

Elegância aqui não significa aparência limpa por cima de um sistema confuso. Elegância significa que cada parte tem uma função clara, cada decisão deixa rastro, cada abstração reduz complexidade real e cada execução produz algo verificável.

### Superfície Simples, Núcleo Profundo

O usuário deve sentir que está lidando com algo simples:

```text
"Arnaldo, quero transformar essa ideia em um negócio validado."
```

Mas por baixo, o sistema deve acionar uma arquitetura profunda:

```text
compilação de intenção
  -> análise de incerteza
  -> escolha de topologia
  -> criação de agentes
  -> seleção de ferramentas
  -> execução com políticas
  -> validação adversarial
  -> geração de artefatos
  -> registro de evidências
  -> aprendizado
```

A complexidade deve existir, mas não deve vazar para o usuário sem necessidade.

### Eficiência Como Inteligência

O Arnaldo não deve resolver tudo com força bruta. Um sistema realmente moderno precisa saber quando não chamar agentes.

Ele deve escolher o menor mecanismo suficiente:

```text
resposta direta
  se o problema é simples;

função determinística
  se o problema é mecânico;

workflow
  se o processo é conhecido;

agente único
  se há ambiguidade moderada;

organização multiagente
  se há incerteza, paralelismo ou conflito de critérios;

simulação
  se o custo do erro é alto;

Tool Forge
  se falta capacidade real;

humano
  se há risco, valor subjetivo ou autoridade necessária.
```

Eficiência não é apenas gastar menos token. É usar a forma correta de cognição para cada tarefa.

### Modernidade Sem Teatro

O Arnaldo não deve parecer avançado por mostrar dezenas de agentes conversando. Isso é espetáculo.

Ele deve parecer avançado porque:

- entrega artefatos úteis;
- mostra raciocínio auditável;
- evita trabalho desnecessário;
- sabe o que não sabe;
- cria ferramentas quando precisa;
- lembra o que aprendeu;
- não repete erros;
- adapta a organização ao problema;
- mantém o usuário no nível certo de controle.

O ideal é que o usuário veja pouco ruído e muita consequência.

### Gosto Operacional

O sistema deve desenvolver "gosto" no sentido operacional: preferência por soluções mais simples, reversíveis, mensuráveis e executáveis.

```yaml
operational_taste:
  prefer:
    - "artefatos executáveis sobre texto genérico"
    - "experimentos pequenos sobre planos grandiosos"
    - "evidência sobre autoridade"
    - "contratos sobre prompts longos"
    - "capacidade tipada sobre ferramenta por nome"
    - "execução reversível sobre ação irreversível"
    - "simulação antes de aposta cara"
  avoid:
    - "personas fixas demais"
    - "cadeias longas sem validação"
    - "ferramentas demais no contexto"
    - "autonomia sem política"
    - "memória sem procedência"
    - "texto bonito sem lastro"
```

---

## O Que Torna O Arnaldo Sobre-Humano

"Sobre-humano" não deve significar místico. Deve significar capacidades operacionais que humanos raramente conseguem combinar de forma consistente.

O Arnaldo deve ser sobre-humano por composição, não por pose.

### 1. Cognição Paralela

Humanos pensam majoritariamente em sequência. O Arnaldo deve conseguir pensar em paralelo:

- múltiplas hipóteses;
- múltiplas estratégias;
- múltiplos times;
- múltiplos cenários;
- múltiplos críticos;
- múltiplas formas de evidência.

Para uma decisão importante, o sistema não deveria produzir "uma resposta". Deveria produzir alternativas competindo sob critérios explícitos.

### 2. Ausência De Ego Cognitivo

Um humano se apega à própria ideia. O Arnaldo deve criar mecanismos para destruir suas próprias conclusões.

Toda resposta relevante pode ser atacada por:

- Skeptic Agent;
- Reality Gap Detector;
- Evidence Auditor;
- Counterfactual Simulator;
- Cost Controller;
- Domain Risk Reviewer.

O objetivo não é parecer certo. É sobreviver a crítica.

### 3. Memória Sem Fadiga

O Arnaldo deve lembrar:

- o que funcionou;
- o que falhou;
- quais hipóteses foram testadas;
- quais ferramentas foram ruins;
- quais decisões custaram caro;
- quais preferências do usuário são estáveis;
- quais padrões aparecem em tarefas diferentes.

Humanos esquecem. O sistema deve acumular experiência operacional.

### 4. Criação De Capacidade

Um assistente comum usa ferramentas. O Arnaldo deve perceber quando uma capacidade não existe e propor sua criação.

Isso é uma mudança de categoria:

```text
usar ferramenta
  -> selecionar capacidade
  -> detectar lacuna
  -> projetar ferramenta
  -> testar ferramenta
  -> registrar ferramenta
  -> usar ferramenta em organizações futuras
```

O sistema não apenas trabalha dentro do espaço de ação existente. Ele expande esse espaço.

### 5. Execução Com Prova

Humanos frequentemente entregam opinião. O Arnaldo deve entregar trabalho com procedência.

Cada decisão importante deve responder:

```text
de onde veio isso?
quão confiável é?
qual premissa sustenta?
o que contradiz?
qual teste validaria?
qual risco permanece?
```

Isso cria uma máquina de trabalho com lastro.

### 6. Simulação De Consequências

Antes de executar ações caras, o Arnaldo deve criar futuros possíveis e testar a robustez do plano.

Ele deve perguntar:

- e se o canal falhar?
- e se o prazo dobrar?
- e se o custo subir?
- e se o usuário não tiver tempo?
- e se o concorrente já tiver distribuição?
- e se a integração for inviável?

O objetivo não é prever o futuro. É encontrar fragilidades antes que elas virem custo real.

### 7. Autonomia Com Freios Finos

Humanos delegam mal porque dão liberdade demais ou de menos. O Arnaldo deve operar com autonomia granular:

```text
pode pesquisar,
pode escrever,
pode executar localmente,
pode testar,
mas não pode gastar,
não pode enviar,
não pode publicar,
não pode acessar dados privados,
não pode assumir risco jurídico
sem aprovação.
```

Isso permite potência sem irresponsabilidade.

### 8. Longo Horizonte

O Arnaldo não deve existir apenas no turno atual. Ele deve carregar objetivos ao longo do tempo:

- lembrar decisões;
- acompanhar experimentos;
- reavaliar hipóteses;
- cobrar pendências;
- detectar regressões;
- preservar contexto;
- adaptar estratégia.

O sistema deve conseguir trabalhar em ciclos de dias, semanas e meses.

### 9. Metacognição

O Arnaldo deve pensar sobre o próprio pensamento.

Antes de executar, ele deve decidir:

```text
isso precisa de pesquisa?
isso precisa de debate?
isso precisa de simulação?
isso precisa de ferramenta nova?
isso precisa de aprovação?
isso pode ser resolvido diretamente?
isso deve ser recusado?
```

A metacognição é o que impede o sistema de virar uma fábrica cara de agentes desnecessários.

---

## O Que O Arnaldo Não É

### Não é um chatbot

Chat é apenas uma das interfaces possíveis. O núcleo do Arnaldo não deve depender de conversa linear.

### Não é um conjunto fixo de agentes

Agentes fixos como "Pesquisador", "Escritor" e "Revisor" são úteis, mas limitados. O Arnaldo deve gerar agentes específicos conforme a tarefa.

### Não é um roteador de ferramentas

Selecionar ferramentas é uma parte pequena do problema. A questão maior é criar uma estrutura de execução, validação e aprendizado.

### Não é automação cega

O Arnaldo não deve executar ações sensíveis sem política, contrato e aprovação. A autonomia precisa ser graduada.

### Não é "IA fazendo tudo"

O sistema deve saber quando responder, quando planejar, quando executar, quando pedir aprovação, quando criar ferramenta, quando testar hipótese e quando admitir incerteza.

---

## Princípios De Design

### 1. Intenção acima de prompt

O usuário não deve precisar aprender a escrever prompts complexos. O sistema deve converter linguagem natural em contratos de intenção.

### 2. Contratos acima de conversa

Toda execução relevante deve ter contrato:

- objetivo;
- restrições;
- recursos;
- ferramentas;
- permissões;
- critérios de sucesso;
- formato de saída;
- evidências exigidas.

### 3. Organizações acima de agentes

O agente individual é uma unidade pequena demais para tarefas complexas. O Arnaldo deve criar organizações temporárias.

### 4. Capacidades acima de ferramentas

O sistema não deve escolher ferramentas por nome. Deve escolher por capacidade tipada.

### 5. Evidência acima de confiança

Nenhum resultado importante deve ser aceito apenas porque parece convincente. O sistema deve carregar evidências, fontes, premissas, validações e incertezas.

### 6. Evolução acima de memória passiva

O Arnaldo não deve apenas lembrar. Ele deve melhorar seus próprios padrões de execução com base em resultados.

### 7. Generacidade com governança

O sistema deve ser genérico, mas não livre de limites. Autonomia sem política vira risco.

### 8. Runtime desacoplado

O Arnaldo pode usar Microsoft Agent Framework, OpenAI Agents SDK, LangGraph, Google ADK ou outro runtime. Mas o núcleo conceitual deve ser independente.

### 9. Tudo importante deve ser versionável

Planos, agentes, ferramentas, memórias, políticas, contratos e artefatos precisam poder ser versionados, auditados e reproduzidos.

### 10. O sistema deve aprender com falhas

A memória negativa é tão importante quanto a memória positiva. O Arnaldo deve lembrar o que não funcionou.

### 11. Metacognição antes de execução

Antes de criar agentes, o sistema deve decidir qual forma de pensamento a tarefa merece. Resposta direta, função determinística, workflow, agente único, debate, simulação e Tool Forge são modos diferentes de cognição, não variações do mesmo prompt.

---

## Arquitetura Geral

```text
┌─────────────────────────────────────────────────────────────┐
│                         Usuário                              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Arnaldo Interface                         │
│        Chat, Command Mode, Ops Mode, Evidence Mode            │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Intent Compiler                           │
│     Converte pedido humano em intenção declarativa            │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                         Task IR                              │
│   Representação intermediária estável, tipada e versionada    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Cognitive Control Plane                      │
│ Decide modo cognitivo, risco, profundidade e forma de ação    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Capability Graph                          │
│      Mapa de ferramentas, agentes, dados e capacidades        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Organization Generator                       │
│    Cria topologia, agentes, contratos e plano de execução     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Policy Engine                           │
│      Permissões, aprovações, orçamento, dados e risco         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       Agent Runtime                          │
│     Execução em Microsoft Agent Framework ou adaptadores      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Evidence Ledger                           │
│      Fontes, decisões, tool calls, validações e incertezas    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Evolution Engine                          │
│        Reputação, aprendizado, templates e melhoria           │
└─────────────────────────────────────────────────────────────┘
```

---

## Cognitive Control Plane

O Cognitive Control Plane é a camada que decide como o Arnaldo deve pensar antes de decidir quem deve agir.

Sem essa camada, o sistema tende a chamar agentes para tudo. Isso é caro, lento e pouco elegante.

Com essa camada, o Arnaldo escolhe dinamicamente o modo cognitivo adequado:

```yaml
cognitive_control:
  task_id: "task_001"
  ambiguity: "high"
  reversibility: "medium"
  external_impact: "low"
  data_sensitivity: "low"
  required_confidence: "high"
  selected_modes:
    - "research"
    - "parallel_hypothesis_generation"
    - "adversarial_review"
    - "reality_gap_detection"
  rejected_modes:
    - mode: "direct_answer"
      reason: "problema aberto demais"
    - mode: "single_agent_execution"
      reason: "alto risco de viés por perspectiva única"
    - mode: "tool_forge"
      reason: "capacidades necessárias já existem"
  budget:
    depth: "medium"
    max_iterations: 4
    stop_when: "deliverables_validated"
```

### Modos Cognitivos

```text
Direct Answer
  responder sem criar organização.

Deterministic Function
  usar código, parser, cálculo ou regra.

Known Workflow
  executar processo já conhecido.

Single Specialist
  criar um agente especialista.

Parallel Exploration
  criar múltiplos agentes independentes.

Adversarial Debate
  colocar tese e antítese em conflito.

Market Of Strategies
  criar times concorrentes e escolher o melhor.

Simulation
  testar consequências e cenários.

Tool Forge
  criar nova capacidade.

Human Checkpoint
  pedir decisão, aprovação ou julgamento subjetivo.

Refusal Or Deferral
  recusar, pausar ou pedir mais informação quando necessário.
```

### Política De Profundidade

Nem toda tarefa merece a mesma profundidade. O sistema deve calibrar esforço:

```yaml
depth_policy:
  shallow:
    when:
      - "baixo risco"
      - "tarefa reversível"
      - "resposta simples"
    behavior:
      - "evitar multiagente"
      - "usar resposta direta ou função"
  standard:
    when:
      - "alguma ambiguidade"
      - "entregável útil"
      - "risco moderado"
    behavior:
      - "usar agente especialista ou workflow curto"
      - "validar schema"
  deep:
    when:
      - "alto impacto"
      - "decisão estratégica"
      - "muita incerteza"
    behavior:
      - "usar exploração paralela"
      - "usar revisão adversarial"
      - "exigir evidência"
      - "simular cenários"
```

### Stop Conditions

Um sistema eficiente precisa saber parar.

```yaml
stop_conditions:
  - "critérios de sucesso atingidos"
  - "custo marginal maior que ganho esperado"
  - "bloqueio depende de aprovação humana"
  - "falta capacidade essencial"
  - "risco excede política"
  - "incerteza residual foi explicitamente marcada"
```

Essa camada é uma das chaves para o Arnaldo parecer moderno: ele não desperdiça inteligência. Ele aplica inteligência no formato certo.

---

## Fluxo De Execução

### 1. Receber pedido

O usuário declara um objetivo em linguagem natural:

```text
Arnaldo, quero criar uma automação para clínicas que reduza faltas em consultas.
Valide o nicho, proponha o produto, gere a landing page e monte o plano de aquisição.
```

### 2. Compilar intenção

O Intent Compiler extrai:

- objetivo;
- contexto;
- restrições;
- prazos;
- recursos disponíveis;
- riscos;
- critérios de sucesso;
- nível de autonomia permitido.

### 3. Criar Task IR

O pedido vira uma representação intermediária:

```yaml
task:
  id: "task_2026_05_03_001"
  goal: "validar e estruturar produto de automação para clínicas"
  domain: "b2b_saas"
  expected_deliverables:
    - market_validation_report
    - product_positioning
    - landing_page_copy
    - acquisition_plan
    - experiment_backlog
  constraints:
    budget: "low"
    market: "Brazil"
    execution_style: "lean"
  success_criteria:
    - "identificar nicho inicial com justificativa"
    - "mapear principais dores e objeções"
    - "propor oferta testável"
    - "definir métricas de validação"
  autonomy:
    max_level: 3
    require_approval_for:
      - external_messages
      - paid_tools
      - public_publishing
```

### 4. Decidir modo cognitivo

O Cognitive Control Plane decide a profundidade e a forma de execução:

```yaml
cognitive_decision:
  selected_modes:
    - "research"
    - "parallel_exploration"
    - "adversarial_review"
  depth: "standard"
  reason: "tarefa aberta, com incerteza de mercado e entregáveis estratégicos"
  avoid:
    - mode: "direct_answer"
      reason: "resposta única geraria plano sem validação"
```

### 5. Consultar Capability Graph

O sistema identifica quais capacidades são necessárias:

- pesquisa web;
- análise de concorrentes;
- síntese estratégica;
- copywriting;
- análise de risco;
- criação de experimentos;
- geração de artefatos.

### 6. Gerar organização

O Organization Generator escolhe uma topologia:

```text
Research Squad
  -> Market Researcher
  -> Competitor Analyst
  -> Customer Pain Mapper

Strategy Squad
  -> Positioning Strategist
  -> Offer Designer
  -> Pricing Analyst

Execution Squad
  -> Landing Page Copywriter
  -> Acquisition Planner
  -> Experiment Designer

Validation Squad
  -> Skeptic Agent
  -> Evidence Auditor
  -> Reality Gap Detector
```

### 7. Executar com políticas

Cada agente recebe:

- objetivo próprio;
- ferramentas permitidas;
- escopo de memória;
- orçamento;
- contrato de saída;
- regras de segurança;
- critérios de conclusão.

### 8. Validar

O resultado passa por:

- validação de schema;
- revisão adversarial;
- checagem de evidência;
- checagem de lacunas de realidade;
- checagem de política;
- consolidação.

### 9. Entregar

O usuário recebe artefatos prontos e um resumo executivo.

### 10. Aprender

O sistema registra:

- quais agentes funcionaram;
- quais ferramentas foram úteis;
- quais hipóteses ficaram incertas;
- quais padrões devem ser reutilizados;
- quais falhas foram detectadas.

---

## Intent Compiler

O Intent Compiler é o componente que transforma pedido humano em contrato executável.

Ele deve lidar com pedidos vagos, incompletos ou ambíguos. Em vez de interromper sempre para fazer perguntas, ele deve inferir o que puder, marcar incertezas e pedir esclarecimento apenas quando a execução depender criticamente da resposta.

### Entrada

```text
Quero criar um agente que faça qualquer tarefa de negócio e tecnologia.
Ele precisa gerar outros agentes e usar ferramentas conforme a necessidade.
```

### Saída

```yaml
intent:
  desired_state: "plataforma generica de execução agentica"
  primary_goal: "criar arquitetura para meta-agente declarativo"
  user_preference:
    ambition_level: "disruptive"
    detail_level: "high"
    style: "strategic_and_architectural"
  constraints:
    genericity: "high"
    declarative_processing: true
    tool_count_expected: "hundreds"
  open_questions:
    - "qual runtime inicial será usado?"
    - "qual domínio do MVP?"
  inferred_requirements:
    - "sistema deve criar agentes dinamicamente"
    - "ferramentas devem ser catalogadas por capacidade"
    - "execuções devem ser auditáveis"
```

### Responsabilidades

- extrair objetivo;
- separar objetivo de restrições;
- identificar entregáveis;
- detectar ambiguidade;
- inferir contexto;
- definir nível inicial de autonomia;
- converter conversa em contrato declarativo.

---

## Task IR

Task IR é a representação intermediária de trabalho.

Ela é a espinha dorsal do Arnaldo. Sem uma IR, o sistema fica dependente de prompts e conversas. Com uma IR, o sistema pode validar, versionar, testar, reproduzir e otimizar execuções.

### Por Que Uma IR É Necessária

Prompts são frágeis:

- misturam intenção, contexto e instrução;
- são difíceis de testar;
- são difíceis de comparar;
- mudam sem controle;
- escondem decisões;
- dificultam auditoria.

A IR resolve isso criando uma estrutura estável:

```text
Linguagem humana
  -> Intent IR
  -> Task IR
  -> Organization IR
  -> Workflow IR
  -> Execution IR
  -> Evidence IR
  -> Artifact IR
```

### Exemplo De Task IR

```yaml
task_ir:
  version: "0.1"
  id: "task_001"
  goal:
    statement: "criar estratégia de aquisição para produto B2B"
    type: "strategic_execution"
  context:
    market: "Brazil"
    company_stage: "idea"
    available_budget: "low"
  constraints:
    deadline_days: 14
    avoid:
      - "ações pagas sem aprovação"
      - "uso de dados pessoais sem consentimento"
  deliverables:
    - id: "market_report"
      schema: "market_validation_report"
    - id: "outbound_sequence"
      schema: "email_sequence"
    - id: "experiment_plan"
      schema: "experiment_backlog"
  success_criteria:
    - id: "evidence_based"
      description: "decisões principais devem ter evidência"
    - id: "actionable"
      description: "entrega deve permitir execução imediata"
  autonomy:
    max_level: 3
  risk:
    domain_risk: "medium"
    data_sensitivity: "low"
```

---

## Capability Graph

O Capability Graph é o mapa de tudo que o Arnaldo consegue fazer.

Ele não deve ser uma lista plana de ferramentas. Deve ser um grafo tipado de capacidades, ferramentas, agentes, dados, políticas, custos e riscos.

### Problema Que Ele Resolve

Se o agente principal recebe centenas de ferramentas no prompt, ele fica confuso, caro e arriscado. Além disso, ferramentas com nomes parecidos podem ser escolhidas de forma errada.

O Arnaldo deve escolher ferramentas por capacidade:

```text
Preciso "extrair texto de PDF escaneado"
  -> capacidade: document.ocr.extract_text
  -> ferramentas candidatas:
       - azure_document_intelligence
       - tesseract_ocr
       - pdf_image_pipeline
  -> seleção por custo, precisão, disponibilidade e política
```

### Exemplo De Ferramenta

```yaml
tool:
  id: "web_research"
  name: "Web Research"
  capabilities:
    - "search.public_web"
    - "extract.sources"
    - "summarize.web_pages"
  inputs:
    query:
      type: "string"
      required: true
    recency_days:
      type: "integer"
      required: false
  outputs:
    findings:
      type: "array"
    sources:
      type: "array"
  risk:
    level: "medium"
    reasons:
      - "external_network"
      - "source_reliability_varies"
  cost:
    token_cost: "medium"
    money_cost: "low"
  policies:
    requires_approval: false
    allowed_data_classes:
      - "public"
```

### Exemplo De Capacidade Ausente

```yaml
missing_capability:
  id: "semantic_contract_diff"
  needed_for_task: "compare two legal contracts and identify obligation changes"
  available_alternatives:
    - "generic_pdf_text_extraction"
    - "text_diff"
  gap:
    reason: "generic diff does not understand legal clauses"
    severity: "high"
  recommended_action: "propose_new_tool"
```

---

## Agent Genome

Agent Genome é a especificação declarativa que define como um agente temporário deve existir.

Em vez de criar agentes com prompts livres, o Arnaldo cria agentes a partir de genomas.

### Exemplo

```yaml
agent_genome:
  id: "genome_market_researcher_v1"
  species: "analyst"
  role: "market_researcher"
  objective: "mapear mercado, concorrentes e sinais de demanda"
  epistemic_style: "evidence_first"
  behavioral_style:
    tone: "direct"
    risk_posture: "conservative"
    creativity: "medium"
  tools:
    required_capabilities:
      - "search.public_web"
      - "extract.sources"
      - "summarize.web_pages"
    forbidden_capabilities:
      - "send.external_message"
      - "spend.money"
  memory:
    scope: "task"
    can_read:
      - "project_context"
      - "user_preferences"
    can_write:
      - "task_findings"
  output_contract:
    schema: "market_research_report"
    required_sections:
      - "market_overview"
      - "competitors"
      - "customer_pains"
      - "evidence"
      - "uncertainties"
  validation:
    minimum_sources_per_major_claim: 2
    require_counter_evidence: true
  lifecycle:
    max_iterations: 5
    expires_after_task: true
```

### Genes Possíveis

- papel;
- objetivo;
- estilo epistemológico;
- ferramentas permitidas;
- ferramentas proibidas;
- política de memória;
- autonomia;
- orçamento;
- formato de saída;
- política de evidência;
- comportamento em caso de incerteza;
- limite de iterações;
- relação com outros agentes.

### Por Que Isso Importa

Prompts criam personagens. Genomas criam unidades operacionais.

Um agente não deve ser apenas "um pesquisador". Ele deve ser:

```text
um pesquisador conservador,
com permissão apenas para fontes públicas,
obrigado a citar evidência,
proibido de enviar mensagens externas,
com memória limitada à tarefa,
e saída em schema validável.
```

---

## Organization Generator

O Organization Generator cria a estrutura temporária que executará a tarefa.

Ele decide:

- quantos agentes são necessários;
- quais papéis devem existir;
- qual topologia usar;
- quais agentes podem se comunicar;
- quais ferramentas cada agente recebe;
- quais entregáveis cada agente produz;
- quais validações serão feitas;
- quando pedir aprovação humana.

### Topologias Possíveis

#### Pipeline

Boa para tarefas lineares.

```text
Researcher -> Writer -> Editor -> Reviewer
```

#### Paralelo Com Consolidação

Boa para coletar perspectivas independentes.

```text
Researcher A ┐
Researcher B ├─> Synthesizer -> Reviewer
Researcher C ┘
```

#### Debate Adversarial

Boa para decisões estratégicas.

```text
Proponent -> Judge
Opponent  -> Judge
```

#### Comitê

Boa para decisões de alto impacto.

```text
Finance Analyst  ┐
Legal Analyst    ├─> Decision Chair
Market Analyst   │
Technical Lead   ┘
```

#### Laboratório

Boa para descoberta e experimentação.

```text
Hypothesis Generator -> Experiment Designer -> Executor -> Statistician -> Skeptic
```

#### Estúdio

Boa para criação.

```text
Creative Director -> Copywriter -> Designer -> Editor -> Brand Critic
```

#### Fábrica

Boa para engenharia e entrega técnica.

```text
Architect -> Implementer -> Tester -> Reviewer -> Release Manager
```

#### Mercado Interno

Boa para gerar alternativas concorrentes.

```text
Team A: low-cost strategy
Team B: premium strategy
Team C: partnership strategy
         ↓
Evaluation Council
         ↓
Hybrid Plan
```

### Seleção De Topologia

O sistema deve escolher a topologia com base em:

- ambiguidade da tarefa;
- risco;
- necessidade de criatividade;
- necessidade de precisão;
- custo permitido;
- prazo;
- volume de ferramentas;
- impacto de erro;
- necessidade de evidência.

---

## Agent Runtime

O Agent Runtime executa as organizações geradas.

O Arnaldo deve ser desacoplado do runtime. Um adaptador deve compilar a Organization IR para a tecnologia escolhida.

### Runtime Inicial Recomendado

O Microsoft Agent Framework é uma boa escolha inicial por oferecer:

- agentes;
- workflows;
- suporte declarativo;
- ferramentas;
- integrações com MCP;
- interoperabilidade via A2A;
- observabilidade;
- suporte a Python e .NET;
- bom encaixe com Azure AI Foundry.

Mas o Arnaldo não deve depender exclusivamente dele.

### Adaptadores Possíveis

```text
Arnaldo Organization IR
  -> Microsoft Agent Framework
  -> OpenAI Agents SDK
  -> LangGraph
  -> Google ADK
  -> runtime próprio
```

### Contrato Do Runtime

Qualquer runtime deve suportar:

- criar agentes dinamicamente;
- injetar ferramentas;
- controlar estado;
- executar workflows;
- registrar tool calls;
- pausar para aprovação humana;
- retomar execuções;
- transmitir eventos;
- expor logs;
- validar saídas estruturadas.

---

## Tool Forge

Tool Forge é o sistema que cria novas ferramentas quando o Capability Graph detecta uma lacuna.

Essa é uma das partes mais importantes do projeto.

O Arnaldo não deve depender eternamente de ferramentas pré-criadas. Ele deve conseguir expandir suas capacidades de forma controlada.

### Fluxo

```text
Tarefa exige capacidade
  -> Capability Graph não encontra ferramenta adequada
  -> Missing Capability é registrada
  -> Tool Forge propõe ferramenta
  -> Policy Engine avalia risco
  -> humano aprova se necessário
  -> Toolsmith Agent implementa
  -> Test Agent cria testes
  -> Security Agent revisa
  -> ferramenta é publicada no registry
  -> Capability Graph é atualizado
```

### Exemplo De Proposta

```yaml
tool_proposal:
  id: "contract_diff_analyzer"
  missing_capability: "semantic_contract_diff"
  purpose: "comparar contratos e detectar mudanças de obrigação, prazo, multa e responsabilidade"
  inputs:
    old_contract:
      type: "file"
      formats:
        - "pdf"
        - "docx"
    new_contract:
      type: "file"
      formats:
        - "pdf"
        - "docx"
  outputs:
    changes:
      type: "array"
    risk_summary:
      type: "string"
    obligations_added:
      type: "array"
    obligations_removed:
      type: "array"
  tests_required:
    - "contratos com cláusulas renumeradas"
    - "contratos com texto escaneado"
    - "contratos com alterações sutis"
    - "arquivo inválido"
  risk:
    level: "high"
    reasons:
      - "legal_domain"
      - "document_sensitivity"
  approval:
    required: true
```

### Regras

- ferramenta nova nunca entra direto em produção;
- toda ferramenta precisa de manifesto;
- toda ferramenta precisa de testes;
- toda ferramenta precisa de política;
- toda ferramenta precisa de versão;
- ferramentas sensíveis exigem aprovação humana;
- ferramentas ruins podem ser desativadas pelo Evolution Engine.

---

## Evidence Ledger

Evidence Ledger é o registro de evidência, decisões e execução.

Um sistema agentico sem evidência vira uma máquina de texto plausível. O Arnaldo deve ser uma máquina de trabalho verificável.

### O Que Registrar

- pedido original;
- intenção compilada;
- Task IR;
- agentes criados;
- ferramentas usadas;
- entradas e saídas;
- fontes;
- premissas;
- incertezas;
- aprovações humanas;
- decisões intermediárias;
- validações;
- erros;
- custos;
- tempo;
- artefatos finais.

### Exemplo

```yaml
evidence_record:
  id: "evidence_001"
  task_id: "task_001"
  claim: "clínicas odontológicas pequenas sofrem com faltas em consultas"
  confidence: 0.81
  evidence:
    - type: "web_source"
      title: "relatório sobre absenteísmo em clínicas"
      url: "https://example.com/report"
      extracted_at: "2026-05-03T14:30:00Z"
    - type: "competitor_signal"
      description: "múltiplos produtos vendem lembretes automatizados para clínicas"
  counter_evidence:
    - "algumas clínicas já usam WhatsApp manualmente com secretárias"
  assumptions:
    - "o mercado-alvo inicial é Brasil"
    - "a solução proposta terá integração simples com WhatsApp"
  validation:
    reviewed_by: "evidence_auditor"
    schema_valid: true
    uncertainty_marked: true
```

### Proof-Carrying Work

Todo agente deve entregar trabalho com prova:

```yaml
agent_output:
  result:
    summary: "nicho recomendado: clínicas odontológicas independentes"
  evidence:
    sources:
      - "source_1"
      - "source_2"
    assumptions:
      - "ticket precisa suportar assinatura mensal"
    uncertainties:
      - "CAC real ainda não foi medido"
  validation:
    critic_review: "passed"
    reality_gap_review: "passed_with_warnings"
```

---

## Policy Engine

Policy Engine controla autonomia, segurança, permissões, custos e risco.

Quanto mais poderoso o sistema, mais forte deve ser sua camada de governança.

### Políticas Fundamentais

```yaml
policy:
  data:
    private_data_access: "explicit_permission_required"
    cross_task_memory_sharing: "restricted"
  actions:
    send_external_message: "approval_required"
    spend_money: "approval_required"
    publish_content: "approval_required"
    delete_data: "approval_required"
  budget:
    max_tokens_per_task: 500000
    max_money_per_task: "R$ 50"
  tools:
    allow_network_tools: true
    allow_code_execution: "sandbox_only"
  risk:
    legal_advice: "must_include_disclaimer_and_human_review"
    medical_advice: "must_include_disclaimer_and_human_review"
    financial_advice: "must_include_disclaimer_and_human_review"
```

### Sistema Imunológico

O Arnaldo deve ter agentes e monitores defensivos:

- Prompt Injection Sentinel;
- Data Boundary Guardian;
- Tool Abuse Monitor;
- Hallucination Auditor;
- Budget Controller;
- Policy Judge;
- Regression Memory;
- Security Reviewer.

Esses componentes não são acessórios. Eles são parte do sistema nervoso central.

---

## Memory System

A memória do Arnaldo deve ser muito mais rica do que um banco vetorial.

### Tipos De Memória

#### Memória episódica

Registra o que aconteceu em execuções anteriores.

```text
"Na tarefa X, usamos estratégia Y, que falhou porque faltavam dados de leads."
```

#### Memória semântica

Registra fatos estáveis.

```text
"O usuário está construindo o Arnaldo como um sistema genérico e declarativo de agentes."
```

#### Memória procedimental

Registra como fazer coisas.

```text
"Para criar uma landing page de validação, usar fluxo: público -> dor -> promessa -> prova -> CTA -> experimento."
```

#### Memória social

Registra pessoas, papéis, relações e estilos.

```text
"O usuário prefere pensamento ambicioso, mas com arquitetura executável."
```

#### Memória institucional

Registra políticas, padrões e decisões do projeto.

```text
"Toda ferramenta nova precisa de manifesto, testes e política antes de entrar no Capability Graph."
```

#### Memória negativa

Registra erros, falsos caminhos e armadilhas.

```text
"Não despejar centenas de ferramentas no prompt principal; isso degrada seleção e segurança."
```

#### Memória prospectiva

Registra compromissos futuros e hipóteses a revisar.

```text
"Revisar se Microsoft Agent Framework continua sendo o melhor runtime após MVP."
```

### Crenças Versionadas

O sistema deve representar crenças explicitamente:

```yaml
belief:
  id: "belief_project_001"
  statement: "o Arnaldo deve ser um compilador de organizações cognitivas"
  confidence: 0.94
  evidence:
    - "usuário pediu sistema genérico, declarativo e disruptivo"
    - "multiagente simples já é commodity"
  implications:
    - "criar Task IR"
    - "criar Agent Genome"
    - "criar Capability Graph"
  last_updated: "2026-05-03"
  decay_policy: "slow"
```

---

## Evolution Engine

Evolution Engine permite que o Arnaldo melhore com o uso.

Ele mede quais agentes, ferramentas, topologias e estratégias funcionam melhor.

### Métricas

```yaml
agent_reputation:
  agent_genome_id: "genome_market_researcher_v1"
  task_type: "market_research"
  runs: 42
  average_quality_score: 0.83
  evidence_failure_rate: 0.07
  human_acceptance_rate: 0.76
  cost_efficiency: 0.68
  best_contexts:
    - "B2B SaaS"
    - "early stage validation"
  weak_contexts:
    - "regulated finance"
```

### Evolução Operacional

O sistema deve:

- promover genomas bons;
- aposentar genomas ruins;
- detectar ferramentas instáveis;
- sugerir novos templates;
- aprender padrões de decomposição;
- registrar falhas recorrentes;
- comparar topologias;
- ajustar políticas de custo;
- melhorar validações.

### Mercado Interno De Soluções

Para tarefas importantes, o Arnaldo pode criar times concorrentes:

```text
Equipe A: estratégia barata e rápida
Equipe B: estratégia premium
Equipe C: estratégia via parcerias
          ↓
Conselho Avaliador
          ↓
Plano híbrido
```

Isso cria diversidade cognitiva e reduz dependência de uma única linha de raciocínio.

---

## Reality Gap Detector

O Reality Gap Detector procura a distância entre o plano e o mundo real.

Muitos sistemas de IA criam planos elegantes, mas inviáveis. O Arnaldo deve atacar esse problema diretamente.

### Perguntas Que Ele Deve Fazer

- O plano assume dinheiro que o usuário não tem?
- O plano assume equipe inexistente?
- O plano assume dados que ainda não foram coletados?
- O plano assume autoridade que o usuário não possui?
- O prazo é realista?
- As integrações existem?
- Há dependência de terceiros?
- Alguém precisa responder mensagens?
- Há risco regulatório?
- A métrica de sucesso é mensurável?
- A execução pode começar hoje?

### Exemplo De Saída

```yaml
reality_gap_report:
  overall_status: "passed_with_warnings"
  gaps:
    - issue: "plano depende de lista de leads ainda inexistente"
      severity: "medium"
      mitigation: "adicionar etapa de construção de lista antes da campanha"
    - issue: "proposta assume integração com WhatsApp"
      severity: "high"
      mitigation: "validar API e custos antes de prometer automação completa"
  recommendation: "executar experimento manual antes de desenvolver integração"
```

---

## Simulation Engine

O Arnaldo deve simular antes de executar quando o risco for alto.

### Simulação De Organizações

Antes de escolher uma estratégia, o sistema pode comparar organizações:

```yaml
simulation:
  alternatives:
    - id: "pipeline_low_cost"
      estimated_cost: "low"
      estimated_speed: "high"
      robustness: "medium"
    - id: "adversarial_committee"
      estimated_cost: "medium"
      estimated_speed: "low"
      robustness: "high"
    - id: "parallel_marketplace"
      estimated_cost: "high"
      estimated_speed: "medium"
      robustness: "high"
  selected: "adversarial_committee"
  reason: "tarefa estratégica com alto risco de premissas frágeis"
```

### Simulação De Mundos

Para decisões estratégicas:

```text
Mundo 1: mercado cresce rápido
Mundo 2: concorrente grande entra
Mundo 3: CAC dobra
Mundo 4: canal orgânico funciona
Mundo 5: canal pago falha
```

O objetivo não é prever o futuro. É descobrir sob quais condições o plano quebra.

---

## Modos De Interface

O chat é insuficiente para um sistema desse tipo.

O Arnaldo deve ter modos diferentes.

### Chat Mode

Interface conversacional para entrada rápida.

### Command Mode

Entrada direta de comandos e contratos.

```text
/run create-startup-validation --market=clinics --budget=low --deadline=30d
```

### Design Mode

Visualização de intenção, agentes, ferramentas, riscos e artefatos.

### Ops Mode

Painel operacional:

- execuções em andamento;
- agentes ativos;
- custos;
- bloqueios;
- aprovações pendentes;
- logs;
- erros.

### Evidence Mode

Inspeção de fontes, provas, tool calls, premissas e validações.

### Memory Mode

Visualização e edição do que o Arnaldo sabe:

- sobre o usuário;
- sobre projetos;
- sobre preferências;
- sobre políticas;
- sobre erros antigos.

### Tool Forge Mode

Painel de capacidades:

- ferramentas disponíveis;
- ferramentas quebradas;
- capacidades ausentes;
- propostas de novas ferramentas;
- testes;
- versões.

### Simulation Mode

Comparação de cenários, estratégias e organizações possíveis.

---

## Autonomia Graduada

O Arnaldo deve operar em níveis de autonomia.

```text
Nível 0: responder
Nível 1: planejar
Nível 2: executar localmente
Nível 3: usar ferramentas externas
Nível 4: criar ferramentas em sandbox
Nível 5: agir em nome do usuário com aprovação
Nível 6: agir autonomamente dentro de políticas
Nível 7: criar organizações recorrentes
```

### Exemplo

```yaml
autonomy:
  max_level: 4
  require_approval_for:
    - "spend.money"
    - "send.external_message"
    - "publish.public_content"
    - "delete.user_data"
    - "access.private_documents"
  allow_without_approval:
    - "search.public_web"
    - "create.local_draft"
    - "run.sandbox_tests"
```

Autonomia não é binária. Ela deve ser granular por ação, ferramenta, dado, custo e risco.

---

## Exemplo Completo

### Pedido

```text
Arnaldo, quero criar uma startup lucrativa em 90 dias usando minhas habilidades atuais.
Quero algo enxuto, B2B, com chance real de conseguir os primeiros clientes rápido.
```

### Intent IR

```yaml
intent:
  desired_state: "startup validada com primeiros clientes ou pipeline real"
  deadline: "90 days"
  constraints:
    business_model: "B2B"
    budget: "low"
    execution_style: "lean"
    team: "solo_or_small"
  success_criteria:
    - "identificar nicho com dor urgente"
    - "criar oferta testável"
    - "executar experimentos de aquisição"
    - "obter sinais reais de demanda"
  uncertainty:
    - "habilidades atuais do usuário precisam ser mapeadas"
    - "tempo semanal disponível não informado"
```

### Organização Gerada

```yaml
organization:
  topology: "marketplace_with_adversarial_review"
  squads:
    - id: "asset_mapping"
      agents:
        - "skill_mapper"
        - "constraint_mapper"
    - id: "opportunity_discovery"
      agents:
        - "market_researcher"
        - "pain_detector"
        - "competitor_mapper"
    - id: "business_design"
      agents:
        - "offer_designer"
        - "pricing_strategist"
        - "distribution_planner"
    - id: "validation"
      agents:
        - "experiment_designer"
        - "reality_gap_detector"
        - "skeptic_agent"
    - id: "synthesis"
      agents:
        - "executive_synthesizer"
```

### Entregáveis

```yaml
deliverables:
  - "mapa de habilidades e vantagens do usuário"
  - "ranking de oportunidades"
  - "nicho inicial recomendado"
  - "oferta inicial"
  - "landing page"
  - "roteiro de venda"
  - "lista de experimentos"
  - "métricas de validação"
  - "riscos e premissas"
  - "plano de 7, 30 e 90 dias"
```

### Validação

```yaml
validation:
  required:
    - "evidence_audit"
    - "reality_gap_review"
    - "skeptic_review"
    - "schema_validation"
  approval_points:
    - "antes de enviar mensagens externas"
    - "antes de gastar dinheiro"
    - "antes de publicar conteúdo"
```

---

## MVP Proposto

O MVP deve provar a arquitetura sem tentar resolver o mundo inteiro no primeiro dia.

### Escopo Inicial

Três domínios:

```text
1. Software Builder
2. Business / Research Strategist
3. Personal Operations Executor
```

### Componentes Do MVP

- Intent Compiler básico;
- Task IR versionada;
- Cognitive Control Plane inicial;
- Capability Registry;
- Agent Genome;
- Organization Generator com poucas topologias;
- Runtime Adapter para Microsoft Agent Framework;
- Evidence Ledger;
- Policy Engine simples;
- Memory System inicial;
- Critic Agent;
- Reality Gap Detector;
- interface CLI ou web simples.

### Topologias Do MVP

- pipeline;
- paralelo com síntese;
- debate adversarial;
- fábrica de software;
- laboratório de experimentos.

### Ferramentas Iniciais

- busca web;
- leitura de documentos;
- escrita de arquivos;
- execução de código em sandbox;
- análise de repositório;
- geração de artefatos;
- validação de schema;
- registro de evidência.

### Resultado Esperado Do MVP

O usuário deve conseguir pedir:

```text
Crie um plano e protótipo inicial para uma ferramenta B2B de automação.
```

E o sistema deve:

- decompor a tarefa;
- gerar agentes específicos;
- selecionar ferramentas;
- executar pesquisa;
- criar artefatos;
- validar lacunas;
- entregar evidências;
- registrar aprendizado.

---

## Roadmap

### Fase 0: Fundação Conceitual

- definir manifesto;
- definir vocabulário;
- definir arquitetura;
- definir Task IR;
- definir Agent Genome;
- definir Capability Manifest;
- definir Evidence Schema.

### Fase 1: Núcleo Executável

- implementar Intent Compiler;
- implementar Cognitive Control Plane inicial;
- implementar Capability Registry;
- implementar Agent Genome parser;
- implementar Organization Generator simples;
- implementar Runtime Adapter inicial;
- implementar logs estruturados;
- implementar execução de workflow simples.

### Fase 2: Evidência E Validação

- criar Evidence Ledger;
- adicionar validação de schema;
- adicionar Critic Agent;
- adicionar Reality Gap Detector;
- adicionar Policy Engine inicial;
- adicionar checkpoints humanos.

### Fase 3: Tool Forge

- detectar capacidades ausentes;
- propor ferramentas;
- criar manifesto de ferramentas;
- executar testes em sandbox;
- publicar ferramentas no registry;
- criar reputação de ferramentas.

### Fase 4: Memória E Evolução

- implementar memória episódica;
- implementar memória semântica;
- implementar memória procedimental;
- implementar memória negativa;
- criar reputação de agentes;
- promover templates;
- aposentar genomas ruins.

### Fase 5: Interface Operacional

- criar Ops Mode;
- criar Evidence Mode;
- criar Memory Mode;
- criar Tool Forge Mode;
- criar visualização de organizações;
- criar replay de execuções.

### Fase 6: Autonomia Avançada

- organizações recorrentes;
- simulação de cenários;
- mercado interno de soluções;
- criação autônoma de ferramentas com aprovação;
- execução contínua de objetivos;
- monitoramento de métricas reais.

---

## Glossário

### Arnaldo

O sistema completo. Um kernel cognitivo que transforma intenções em organizações de execução.

### Intent Compiler

Componente que transforma linguagem humana em intenção estruturada.

### Task IR

Representação intermediária de trabalho. Estrutura versionada que descreve o objetivo, restrições, entregáveis, autonomia e critérios de sucesso.

### Cognitive Control Plane

Camada que decide o modo cognitivo adequado para a tarefa: resposta direta, função determinística, workflow, agente especialista, exploração paralela, debate adversarial, simulação, Tool Forge, checkpoint humano ou recusa.

### Capability Graph

Grafo de capacidades, ferramentas, agentes, dados, custos, riscos e políticas.

### Agent Genome

Especificação declarativa de um agente temporário.

### Organization Generator

Componente que cria a organização temporária de agentes para uma tarefa.

### Agent Runtime

Camada que executa agentes e workflows.

### Tool Forge

Sistema que propõe, cria, testa e registra novas ferramentas.

### Evidence Ledger

Registro auditável de evidências, decisões, tool calls e validações.

### Policy Engine

Camada de permissões, riscos, aprovações e orçamento.

### Evolution Engine

Sistema que mede desempenho e melhora agentes, ferramentas e topologias com o tempo.

### Reality Gap Detector

Componente que identifica lacunas entre planos gerados e condições reais de execução.

### Organização Temporária

Conjunto efêmero de agentes, ferramentas e contratos criado para resolver uma tarefa específica.

---

## Frase Guia

> O Arnaldo não é um agente.  
> É um compilador de organizações cognitivas.

Essa frase deve orientar todas as decisões técnicas do projeto.

Sempre que uma decisão aparecer, a pergunta correta é:

```text
Isso deixa o Arnaldo mais capaz de transformar intenção em execução verificável?
```

Se a resposta for não, provavelmente é ruído.
