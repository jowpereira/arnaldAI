# Issue: tornar roteamento de capabilities e perfis de execucao genericos para consultas com dado externo

## Resumo

O sistema hoje trata perguntas simples que exigem dado externo atual como se fossem tarefas complexas de pipeline completo. Isso empurra consultas do tipo "preco do dolar hoje", "como esta o clima agora", "qual o preco do bitcoin", "status do servico X", "qual a cotacao atual" para o planner/graph runtime, onde uma falha transitora de rede ou LLM derruba o turno inteiro.

O problema nao e "dolar". O problema e estrutural:

- classificacao semantica produz hints genericos como `search.*`, `connector.*` e `tool.*`
- resolucao de capability funciona por IDs concretos
- roteamento de execucao mistura "tipo de tarefa", "fonte de dados", "mutabilidade" e "complexidade"
- `strict_real` transforma falha transitora de LLM em erro fatal, inclusive para pedidos que deveriam poder responder por lookup simples

O sistema precisa de uma modelagem generica de capabilities e de um roteador de execucao baseado em perfil, nao em um conjunto crescente de `if` por caso de uso.

## Status atual em 2026-05-27

### O que ja foi feito

- Foi introduzida uma camada semantica centralizada para capabilities, com `CapabilityTraits`, `CapabilitySummary` e enriquecimento generico de `capability_needs`.
- Foi introduzido `ExecutionProfile` para separar `inline_capability`, `fast_response`, `medium_response` e `full_pipeline` sem depender apenas de `needs_external_data`.
- `needs_external_data` deixou de empurrar automaticamente lookup remoto simples para pipeline completo quando existe capability read-only inline.
- O kernel passou a forcar classificacao semantica quando o `brain` nao identifica corretamente comandos locais explicitos ou sinais claros de live lookup.
- O caminho inline passou a suportar `search.public_web`, `filesystem.local.search` e `shell.local.readonly` de forma deterministica, sem depender da sintese por LLM para responder quando a execucao real ja ocorreu.
- `search.public_web` foi endurecida com fallback de provider, retry e suporte a Bing RSS/HTML quando DuckDuckGo falha ou retorna vazio.
- Follow-up generico de busca, como "pesquise no google" ou variantes proximas, passou a reutilizar o topico substantivo anterior em vez de consultar a frase literal.
- O grafo/runtime passou a bloquear o atalho conversacional quando tooling relevante esta presente em `available`, `missing` ou `degraded`.
- O executor de tooling foi ajustado para montar payloads validos para capabilities locais read-only, inclusive mapeando `ls` para `dir` no Windows.
- O runtime sequencial passou a seguir a `path` materializada e o pos-processamento deixou de marcar `deliverables_missing` em runs validas quando `execution_evidence` e `next_actions` sao derivaveis.
- A resposta final deixou de depender do ultimo step cego: `primary_artifact` passou a ser priorizado e `critic_review` ficou restrita a riscos/proximos passos, com tier e budget menores.

### Validacao executada

- Suite focada de live lookup/web/roteamento: `23 passed`
  - `tests/test_web_search.py`
  - `tests/test_live_data_shortcut.py`
  - `tests/test_execution_profile.py`
- Suite focada de render/sintese/estado dinamico: `38 passed`
  - `tests/test_local_render.py`
  - `tests/test_synthesis.py`
  - `tests/test_dynamic_features.py`
- Testes focados de graph runtime: `3 passed`
  - `tests/test_graph_runtime_classify.py`
  - `tests/test_graph_runtime_integration.py -k "available_shell_capability or includes_primary_user_request"`
- Testes focados de graph execution: `2 passed`
  - `tests/test_graph_execution.py -k "uses_user_request_for_web_queries or maps_ls_to_safe_shell_command"`
- Durante a investigacao tambem foram reproduzidos smokes reais para:
  - `qual o valor do dolar hoje`
  - follow-up generico de busca web
  - `ls`
  - pedido de listagem da pasta `WorkSpace` no Windows

### O que ainda falta

- Unificar de verdade a fonte de verdade entre taxonomia semantica, registry de capabilities e executor real; hoje ainda existe separacao entre capabilities cognitivas/orquestradoras e capabilities executaveis.
- Parar de considerar `search.*` como candidato natural a auto-forge; busca generica e lookup comum devem continuar sendo nativos, nao scaffolds `draft`.
- Ampliar a superficie de capabilities nativas para dominios comuns de lookup read-only, como `fx.rate`, `weather.current`, `time.current`, `news.latest`, `finance.quote` e um primitive remoto estruturado equivalente a `http.readonly.fetch_json`.
- Reduzir ainda mais a dependencia do `brain` como primeira decisao em pedidos com sinal operacional forte; os guard-rails atuais resolvem a regressao, mas ainda sao uma camada de contencao.
- Reexecutar uma suite mais ampla de regressao do projeto apos consolidar essas mudancas; nesta rodada a validacao foi focada nas areas alteradas.

### Estado da issue

Esta issue nao esta concluida. A regressao principal foi contida e boa parte da arquitetura de roteamento passou a ser generica, mas a definicao de pronto ainda nao foi atingida porque:

- a superficie nativa de capabilities continua estreita para live lookup comum;
- ainda ha acoplamento entre catalogo semantico e executor concreto;
- auto-forge continua amplo demais para familias centrais;
- a cobertura de regressao foi focada, nao total.

## Contexto e reproducao

### Fluxo reproduzido

```powershell
uv run python -m arnaldo.chat --autonomy autonomo
```

Sequencia observada:

```text
-> oi
  ✓ 4.2s

Oi.

Diz o que voce quer resolver: problema, objetivo e restricoes.

-> seu nome qual e?
  ✓ 4.1s

Arnaldo.

-> meu e jonathan
  ✓ 9.5s

Fechado, Jonathan.

-> sabe me dizer o preco do dolar hoje?
  ✗ erro (60.1s)

  [erro] RuntimeError: strict_real habilitado: chamada LLM falhou no synapse
  'syn_planner_decompose_work_work_plan': Azure OpenAI network error:
  [WinError 10054] An existing connection was forcibly closed by the remote host
```

### Comportamento observado

- perguntas conversacionais simples funcionam
- memoria de sessao funciona
- consulta simples com dado externo atual cai no pipeline longo
- a falha final nao ocorre na busca web, ocorre em uma etapa de planner com LLM tipado
- o erro final e de rede/transiente, mas o impacto e fatal por causa do caminho de execucao errado

### Comportamento esperado

Pedidos read-only, curtos, de lookup externo atual, devem:

- ser classificados como consultas de "live lookup"
- resolver capability remota concreta antes de montar pipeline complexo
- responder mesmo quando a sintese por LLM falhar, usando fallback textual com evidencias obtidas
- nunca depender do planner completo para perguntas triviais de lookup

## Causa raiz

### 1. O classificador LLM emite familias genericas, nao capabilities concretas

Em `arnaldo/kernel/intent_signals_llm.py`, o prompt orienta o modelo a retornar:

- `search.*` para busca web
- `connector.*` para APIs
- `tool.*` para ferramentas

Esse desenho e util como ontologia de alto nivel, mas entra em choque com o resto do sistema porque o runtime real precisa de capacidades concretas executaveis.

Problema:

- a camada semantica fala em familias
- a camada de execucao fala em IDs concretos
- nao existe uma fase explicita de resolucao `family -> capability concreta`

Consequencia:

- o sistema recebe hints validos semanticamente, mas inexecutaveis operacionalmente
- o roteamento perde precisao
- surgem correcoes oportunistas e condicionais locais

### 2. A resolucao de capability e por ID exato

Em `arnaldo/components/capability_registry.py`, `resolve()` procura `need["id"]` diretamente em um mapa de capabilities registradas.

Problema:

- `search.*` e `connector.*` nao batem com `search.public_web`
- a semantica do pedido nao e traduzida para uma capability concreta
- a resolucao nao usa metadata como `requires_network`, `read_only`, `supports_live_lookup`, `side_effects`, `family`

Consequencia:

- hints genericos nao conseguem dirigir o fluxo de execucao
- o kernel recorre ao planner completo para compensar a falta de precisao

### 3. A classificacao acopla "dado externo" a "complexidade"

Hoje, se `needs_external_data=true`, o request vira `complex`.

Problema:

- "preciso de dado externo" nao implica "preciso de pipeline complexo"
- lookup remoto read-only pode ser simples
- obtencao de dado e orquestracao multi-step sao dimensoes diferentes

Exemplos de lookup simples:

- cotacao atual
- clima agora
- horario atual em um fuso
- status de um servico
- preco atual de um ativo
- noticia mais recente sobre um tema

Exemplos de trabalho realmente complexo:

- montar relatorio com multiplas fontes
- comparar series historicas
- produzir artefato persistente
- acionar ferramentas locais
- integrar connector + transformacao + validacao

Consequencia:

- o sistema promove consultas simples para um caminho mais fragil e mais caro

### 4. `strict_real` torna a falha transitora fatal no lugar errado

Em `arnaldo/graph/execution/engine.py`, erros de LLM em synapses do pipeline completo geram `RuntimeError` fatal quando `strict_real=True`.

Problema:

- isso e aceitavel para etapas realmente obrigatorias de trabalho complexo
- isso e excessivo para lookup remoto simples, onde deve existir fallback de resposta

Consequencia:

- qualquer reset de socket, timeout, 429 ou indisponibilidade transitora do Azure pode matar um pedido simples de consulta

## Problema arquitetural

Hoje, o sistema mistura quatro coisas que deveriam ser independentes:

- semantica do pedido
- tipo de capability necessaria
- perfil de execucao
- politica de falha/fallback

Essas dimensoes precisam ser desacopladas.

## Requisito principal

A solucao precisa ser generica. Nao deve depender de `if` por dominio, como:

- se for dolar, use caminho A
- se for clima, use caminho B
- se for noticia, use caminho C

Tambem nao deve depender de normalizacoes oportunistas como:

- `connector.* -> search.public_web`
- `search.* -> search.public_web`
- `tool.*` ignorado por ser ruido

Essas regras podem existir como contingencia temporaria, mas nao sao desenho final.

## Proposta de arquitetura

### 1. Introduzir um modelo tipado para necessidade de capability

Substituir `capability_needs: list[str]` por uma estrutura tipada. Exemplo conceitual:

```python
@dataclass
class CapabilityNeed:
    family: str
    intent: str
    freshness: str
    side_effects: str
    execution_mode: str
    preferred_sources: list[str]
    constraints: dict[str, Any]
```

Campos minimos sugeridos:

- `family`: `search`, `connector`, `filesystem`, `shell`, `tooling`, `llm`
- `intent`: `lookup`, `retrieve`, `transform`, `mutate`, `synthesize`, `execute`
- `freshness`: `static`, `recent`, `live`
- `side_effects`: `none`, `local`, `remote`
- `execution_mode`: `single_step`, `multi_step`, `streaming`, `batch`
- `requires_network`: bool
- `read_only`: bool
- `requires_llm`: bool
- `preferred_capabilities`: lista de IDs concretos candidatos

Beneficios:

- a classificacao deixa de emitir pseudo-IDs
- o roteador passa a operar com metadados coerentes
- a escolha da capability concreta passa a ser uma fase explicita

### 2. Unificar ontologia, registry e executor

Hoje existem pelo menos tres camadas conceituais separadas:

- taxonomia semantica do classificador
- registry de capabilities registradas
- executor real de builtins

Essas camadas precisam convergir para uma unica fonte de verdade.

Cada capability concreta deve expor metadata de roteamento, por exemplo:

- `id`
- `family`
- `requires_network`
- `read_only`
- `supports_live_lookup`
- `supports_batch`
- `supports_streaming`
- `supports_artifact_generation`
- `degrades_gracefully`
- `preferred_for_intents`
- `cost_profile`
- `latency_profile`

Com isso, a selecao concreta deixa de depender de nome hardcoded.

### 3. Criar uma fase explicita de resolucao semantica para capability concreta

Fluxo proposto:

1. classificador produz `CapabilityNeed`
2. resolvedor consulta o catalogo de capabilities
3. resolvedor escolhe uma capability concreta ou conjunto candidato
4. roteador decide o perfil de execucao com base no need resolvido

Exemplo:

- necessidade semantica: `family=search`, `intent=lookup`, `freshness=live`, `read_only=true`
- capability concreta escolhida: `search.public_web`
- perfil de execucao escolhido: `live_lookup`

### 4. Introduzir perfis de execucao, nao condicionais por dominio

Adicionar um roteador unico, por exemplo `select_execution_profile(request, classification, resolved_capabilities)`.

Perfis sugeridos:

- `conversational_fast`
- `retrieval_augmented`
- `live_lookup`
- `tool_execution_local`
- `structured_multistep`
- `artifact_pipeline`
- `connector_workflow`

Regra generica:

- `read_only + requires_network + freshness=live + sem artefato + sem side effects` => `live_lookup`
- `local tooling` => `tool_execution_local`
- `artifact generation or orchestration` => `structured_multistep` ou `artifact_pipeline`
- `connector + mutation + side effects` => `connector_workflow`

Isso remove a necessidade de ifs por dominio e preserva a semantica.

### 5. Desacoplar complexidade de origem do dado

`needs_external_data` nao deve, por si so, promover o pedido para pipeline complexo.

A complexidade deve considerar:

- numero de passos
- necessidade de artefato
- transformacao
- mutacao
- side effects
- acoplamento entre ferramentas
- necessidade de validacao adicional

`external data` deve influenciar:

- perfil de execucao
- politica de resiliencia
- estrategia de caching
- estrategia de fallback

Nao deve determinar sozinho a complexidade.

### 6. Tornar a politica de falha dependente do perfil

Para `live_lookup`, a politica correta e:

- buscar dados
- sintetizar com LLM se disponivel
- se LLM falhar, responder com fallback textual estruturado
- nunca explodir o turno inteiro se a fonte de dados ja foi obtida

Para `structured_multistep`, a politica pode continuar estrita.

Ou seja:

- `strict_real` nao deve ser binario no sistema inteiro
- ele deve ser aplicado por perfil de execucao e por tipo de etapa

## Escopo desta issue

### Inclui

- redesenho generico de modelagem de capability need
- unificacao de metadata de roteamento em capabilities concretas
- fase explicita de resolucao `need -> concrete capability`
- criacao de um roteador por perfil de execucao
- politica de fallback por perfil
- remocao de dependencias em pseudo-IDs genericos no runtime

### Nao inclui

- tuning de prompts por dominio especifico
- troca do provider de busca web
- troca do provider Azure OpenAI
- redesign de UI/CLI

## Entregaveis esperados

- novo modelo tipado para necessidade de capability
- catalogo unificado de capabilities com metadata operacional
- resolvedor generico de capabilities concretas
- roteador de perfis de execucao
- migracao de `needs_external_data => complex` para logica mais granular
- fallback estruturado para `live_lookup`
- remocao de normalizacoes oportunistas locais
- testes unitarios e de integracao para os perfis principais

## Criterios de aceite

- pergunta simples com dado externo atual nao entra no planner multi-step por default
- o sistema nao depende de `if` por dominio para escolher o caminho
- `search.*`, `connector.*` e similares nao vazam como pseudo-IDs diretamente para a execucao
- capabilities concretas sao escolhidas via resolucao generica
- falha transitora de LLM nao derruba `live_lookup` se o dado externo ja foi obtido
- falha de busca remota gera resposta explicita e controlada, nao stack trace fatal
- requests realmente complexos continuam indo para pipeline completo
- testes cobrem lookup simples, tooling local, connector mutating e artifact pipeline

## Casos que devem funcionar apos a correcao

- "sabe me dizer o preco do dolar hoje?"
- "como esta o clima agora em Sao Paulo?"
- "qual o preco do bitcoin agora?"
- "tem noticia recente sobre OpenAI?"
- "qual o status do servico X?"
- "gere um relatorio comparando cotacao do dolar com euro nos ultimos 30 dias"
- "leia este arquivo local e resuma"
- "rode um comando read-only local"

Os quatro primeiros devem cair em `live_lookup`.
Os demais nao.

## Plano de implementacao sugerido

### Fase 1. Modelagem

- introduzir `CapabilityNeed` tipado
- ajustar `IntentSignals` e classificacao para produzir estrutura semantica, nao pseudo-IDs

### Fase 2. Catalogo de capabilities

- unificar registry e executor em uma fonte de verdade
- adicionar metadata operacional por capability concreta

### Fase 3. Resolucao

- implementar resolvedor `CapabilityNeed -> capability concreta`
- suportar ranking por adequacao, custo, latencia e confiabilidade

### Fase 4. Roteador de perfis

- introduzir `ExecutionProfile`
- implementar `select_execution_profile(...)`
- migrar o kernel para usar o perfil, nao condicionais ad hoc

### Fase 5. Resiliencia

- definir politica de fallback por perfil
- manter `strict_real` apenas onde faz sentido

### Fase 6. Testes

- testes unitarios do resolvedor
- testes unitarios do roteador de perfil
- testes de integracao para consultas simples remotas
- testes de falha de LLM e falha de busca

## Testes minimos necessarios

- consulta remota simples com provider funcionando
- consulta remota simples com provider funcionando e LLM falhando
- consulta remota simples com provider falhando
- workflow local com tooling
- workflow multi-step com artifact
- workflow mutating com connector
- request ambiguo com multiplos candidatos de capability

## Riscos atuais se nada for feito

- regressao recorrente em qualquer consulta de dado externo
- proliferacao de patches locais e `if`s por dominio
- custo operacional maior por mandar lookup simples para pipeline completo
- UX instavel por erro fatal em perguntas triviais
- dificuldade crescente de manter coerencia entre classificador, registry e runtime

## Observacao importante

Ja existe um patch local de contencao para desviar alguns requests de lookup externo do pipeline pesado. Esse patch resolve a dor imediata, mas nao deve ser considerado a solucao final. A solucao final desta issue e arquitetural e precisa eliminar a necessidade de heuristicas oportunistas baseadas em pseudo-IDs ou listas especiais.

## Definicao de pronto

Esta issue so pode ser considerada concluida quando:

- o roteamento de consultas remotas simples for decidido por perfil generico
- a escolha de capability concreta for sistematica
- o runtime nao depender de mapeamentos ad hoc para familias genericas
- o sistema responder de forma robusta a falhas transitorias em perfis read-only
- o comportamento estiver coberto por testes automatizados suficientes
