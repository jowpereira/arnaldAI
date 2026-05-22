# Auditoria: cerebro artificial vs estado real do codigo

## Pergunta

Os documentos descrevem o Arnaldo como um "cerebro artificial" feito de grafos
de agentes, apoiado por grafos de dados/memorias, com plasticidade e evolucao
de politica de decisao. O codigo atual ja entrega isso de forma operacional?

## Resposta curta

Parcialmente.

O repositorio ja tem um **substrato cognitivo real**: `CognitiveGraph`,
`GraphRef`, plasticidade Hebb, hierarquia de grafos, workflow composicional e
runtime em grafo.

Mas o comportamento de "cerebro artificial" ainda **nao e a unidade dominante
de operacao do produto**. O kernel ainda depende bastante de IRs efemeros,
organizacao gerada em lista, heuristicas e componentes de Fase 4 nao
implementados.

Em uma frase:

> o projeto **ja tem o substrato do cerebro**, mas **ainda nao opera como esse
> cerebro de ponta a ponta**.

---

## Tese declarada pelos docs

### 1. O sistema seria um substrate cognitivo simbolico

Evidencia:

- `README.md:9`
- `docs/architecture.md:40`

Declaracao:

- memorias, agentes e ferramentas coexistem no mesmo grafo;
- o grafo e persistente, auditavel e plastico;
- agentes nao sao o centro, o substrato e.

### 2. O sistema seria um grafo de grafos

Evidencia:

- `README.md:174`
- `docs/architecture.md:105`
- `docs/architecture.md:872`

Declaracao:

- cada no pode referenciar outros `CognitiveGraph`s via `GraphRef`;
- isso permite composicao hierarquica;
- a ideia lembra Society of Mind aplicada a engenharia de agentes.

### 3. O sistema seria composto por agentes especializados

Evidencia:

- `docs/architecture.md:1064`

Declaracao:

- agente especializado > agente generalista;
- workflow de agentes > agente que faz tudo;
- workflow-of-workflows > workflow monolitico.

### 4. O sistema deveria evoluir a politica de decisao

Evidencia:

- `docs/architecture.md:1544`

Declaracao:

- cold-start: `epsilon-greedy`
- depois: `contextual bandit`
- depois: `RL hierarquico`

### 5. O sistema deveria ter episteme

Evidencia:

- `README.md:184`
- `docs/architecture.md:2079`

Declaracao:

- detectar lacunas de conhecimento;
- acionar curiosidade;
- forragear na web;
- ingerir conhecimento no grafo.

---

## O que o codigo entrega de verdade

### A. Substrato cognitivo: real

Evidencia:

- `arnaldo/graph/*`
- `docs/architecture.md:2762`

O proprio documento de arquitetura reconhece que essa e a parte mais madura do
projeto. O grafo tipado, a proveniencia, a bitemporalidade e a plasticidade
existem de fato.

Veredito: **entregue**

### B. Hierarquia de grafos (`GraphRef`): real

Evidencia:

- `arnaldo/graph/refs.py:1`

O codigo implementa:

- `OWNED`
- `SHARED`
- `FEDERATED`
- `SNAPSHOT`

Com resolucao lazy e semantica clara.

Veredito: **entregue**

### C. Workflow composicional no grafo: real

Evidencia:

- `arnaldo/graph/workflows.py:52`
- `arnaldo/graph/workflows.py:140`

Ja existe infraestrutura para:

- materializar workflow como `SynapseNode` orquestrador + subgrafo;
- compor workflows entre si;
- compartilhar subgrafos entre composicoes.

Veredito: **entregue como infraestrutura**

### D. Plasticidade transitiva entre niveis: real

Evidencia:

- `arnaldo/graph/hierarchy.py:145`

`record_outcome_recursive()` propaga reward pela hierarquia de subgrafos e
atualiza `ref_strength`.

Veredito: **entregue**

### E. Retrieval hibrido e BFS no grafo: real

Evidencia:

- `README.md:173`
- `docs/architecture.md:800`

O desenho de retrieval por vetor + `graph BFS` + plasticidade existe e esta
ancorado no substrato.

Veredito: **substancialmente entregue**

### F. Runtime em grafo: real, mas adaptado

Evidencia:

- `arnaldo/graph/execution/engine.py:18`
- `arnaldo/runtime/graph_runtime/workflow.py:1`
- `arnaldo/runtime/graph_runtime/evolution.py:18`

Ja existe runtime em grafo com:

- execucao de synapses;
- materializacao de workflow;
- execucao de tooling;
- evolucao de capability.

Mas esse runtime ainda recebe muito do mundo exterior via `organization.workflow`
em forma de lista efemera.

Veredito: **entregue, porem ainda mediado por IR efemero**

---

## Onde a promessa ainda nao virou realidade operacional

### 1. O kernel ainda nasce de organizacao efemera, nao do cerebro

Evidencia:

- `arnaldo/components/organization_generator.py:16`
- `arnaldo/kernel/pipeline.py:1`

Hoje o kernel:

- compila intent/task;
- resolve capability;
- gera `OrganizationIR`;
- gera `organization.workflow` como lista;
- so depois materializa isso no runtime de grafo.

Isso significa que o grafo ainda nao e a fonte primaria de orquestracao.

Veredito: **parcial**

### 2. Os "agentes especializados" ainda sao mais tese do que estado dominante

Evidencia:

- `arnaldo/components/organization_generator.py:36`

O gerador ainda instancia `generic_worker` e papeis genericos como:

- `operator`
- `critic`
- `explorer`

Isso funciona, mas ainda esta distante de uma sociedade persistente de agentes
residentes e especializados pelo proprio substrato.

Veredito: **parcial**

### 3. A politica `greedy -> bandit -> RL` nao esta implementada no controle geral

Evidencia:

- docs: `docs/architecture.md:1544`
- codigo: `arnaldo/memory/models.py:20`
- codigo: `arnaldo/memory/graph_bridge.py:130`

O que existe hoje e um `greedy_score` local para materializacao de associacoes
de memoria. Isso **nao** equivale a:

- epsilon-greedy global;
- bandit contextual no roteamento;
- RL hierarquico.

Veredito: **muito parcial**

### 4. A episteme nao esta entregue

Evidencia:

- `docs/architecture.md:2079`

Os proprios docs marcam como nao implementados:

- `EpistemicGapAnalyzer`
- `CuriosityEngine`
- `WebForager`
- `KnowledgeIngester`

Isso e decisivo: sem isso, o "cerebro" ainda nao fecha o ciclo de detectar
lacuna -> buscar mundo -> incorporar aprendizado.

Veredito: **nao entregue**

### 5. Policy/governanca ainda esta frouxa

Evidencia:

- `arnaldo/components/policy_engine.py:50`

O `PolicyEngine` retorna `allowed=True` por default. Ou seja, a estrutura de
governanca existe, mas o enforcement real ainda esta aquem da tese.

Veredito: **parcial / cosmetico em alguns fluxos**

### 6. Ainda ha stubs relevantes no caminho principal

Evidencia:

- `arnaldo/components/intent_heuristics.py:13`
- `arnaldo/runtime/local_render.py:8`
- `docs/architecture.md:2793`

Exemplos:

- `derive_desired_state` ainda e heuristica rasa;
- `execute_step` local retorna dicts hardcoded por acao;
- `render_artifact` ainda usa template fixo;
- parte da memoria ainda nao migrou integralmente para o grafo.

Veredito: **incompleto**

---

## Conclusao honesta

### O que ja seria incorreto dizer

Seria incorreto dizer que o projeto e "so um wrapper de LLM".

Nao e. Ha trabalho estrutural real no substrato: grafo, plasticidade,
hierarquia, workflows composicionais e runtime em grafo.

### O que tambem seria incorreto dizer

Seria incorreto dizer que o projeto **ja opera** como um cerebro artificial
pleno, com:

- sociedade persistente de agentes especializados;
- politica adaptativa madura;
- episteme operacional;
- loop completo de curiosidade e foragem;
- o grafo como fonte unica e dominante de decisao.

Ainda nao.

### Formulação precisa

O estado atual e este:

1. **substrato do cerebro:** ja existe
2. **mecanica de composicao cerebral:** ja existe em boa parte
3. **controle cognitivo de ponta a ponta pelo proprio grafo:** parcial
4. **episteme / curiosidade / foragem:** ausente
5. **politica greedy/bandit/RL de verdade:** ausente fora de nicho local

---

## Julgamento final

Se a pergunta for:

> "pelos documentos, era para existir um cerebro artificial de grafos de
> agentes sobre grafos de dados?"

A resposta e:

**sim.**

Se a pergunta for:

> "o codigo atual ja opera integralmente nesse modo?"

A resposta e:

**nao.**

O projeto esta no ponto em que o **substrato e real**, mas o **comportamento
global prometido pelos docs ainda e parcialmente blueprint**.

---

## Gap principal resumido

O maior gap nao e "falta de grafo".

O maior gap e:

> o kernel ainda **consulta** o cerebro, mas ainda nao **vive dele** como
> mecanismo primario de organizacao, decisao, exploracao epistemica e
> aprendizado adaptativo.
