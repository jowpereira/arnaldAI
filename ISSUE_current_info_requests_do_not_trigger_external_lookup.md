# Bug: pedidos de informacao atual nao acionam busca externa nem tooling

## Resumo

Consultas que dependem de dado externo e atual, como cotacao do dolar, ficam presas no `medium_path` conversacional e nunca chegam a um fluxo com capability/tooling. Mesmo quando o texto explicita "web" ou "internet", o sistema:

1. classifica o pedido como `intermediate` e faz bypass do pipeline completo;
2. ignora `capability_hints` porque o `medium_path` nao passa pelo `AdaptivePlanner`;
3. nao tem runtime para executar `search.public_web` mesmo quando essa capability existe no registry com `module_path`.

Resultado: o Arnaldo responde com texto defensivo ("nao sei em tempo real", "te ensino a consultar") em vez de buscar.

## Severidade

Alta.

Isso quebra um caso central de assistente: responder consultas factuais correntes quando o usuario manda explicitamente buscar.

## Reproducao real

Sessao real observada:

1. `queria saber o preco do dolar`
2. `o dolar comercial mesmo`
3. `busque vc`

Comportamento atual:

- o Arnaldo nao consulta nada;
- responde que nao tem acesso garantido a cotacao em tempo real;
- passa a empurrar o usuario para consulta manual ou script.

## Reproducao minima

### 1. Classificacao errada para pedidos correntes

`classify_request()` trata consultas como estas como `intermediate`:

- `queria saber o preco do dolar`
- `o dolar comercial mesmo`
- `busque vc`
- `busque na web o preco do dolar comercial`

Evidencia local:

```python
from arnaldo.kernel.classify import classify_request

for text in [
    "queria saber o preco do dolar",
    "o dolar comercial mesmo",
    "busque vc",
    "busque na web o preco do dolar comercial",
]:
    print(text, classify_request(text).to_dict())
```

Resultado observado:

- todos caem em `{'level': 'intermediate', 'skip_full_pipeline': True, 'suggested_tier': 'fast'}`

### 2. Hint de busca externa existe, mas nao e usado

O planner sabe inferir `search.public_web` quando o texto contem `web` ou `internet`:

- [arnaldo/components/adaptive_planner.py](arnaldo/components/adaptive_planner.py)

Trecho relevante:

- `infer_capability_hints()` adiciona `search.public_web`

Mas o `medium_path` nao usa `AdaptivePlanner`, entao esse hint nunca entra no fluxo para consultas curtas.

### 3. Mesmo no pipeline completo, `search.public_web` nao vira tooling executavel

Quando `search.public_web` existe no registry com `module_path`, o runtime ainda ignora a capability.

Evidencia estrutural:

- [arnaldo/runtime/graph_runtime/capabilities.py](arnaldo/runtime/graph_runtime/capabilities.py)

Hoje:

- `_collect_tooling_targets()` considera so prefixes `connector.` e `tool.`
- `_collect_tool_execution_targets()` considera so prefixes `connector.` e `tool.`

Ou seja:

- `search.public_web` nunca gera `design_tooling`
- `search.public_web` nunca gera `execute_tooling`
- `search.public_web` nunca entra no workflow materializado

## Causa raiz

O bug e composto por duas falhas de arquitetura que se somam:

### A. Roteamento curto demais para consultas que exigem mundo externo

`classify_request()` privilegia `medium_path` para requests curtos e nao diferencia:

- pergunta opinativa/explicativa;
- pergunta factual dependente de dado atual;
- comando explicito para buscar/consultar.

Assim, queries de cotacao entram em `medium_response()`, que so faz:

- retrieval local;
- 1 chamada LLM;
- zero capability resolution;
- zero tool execution.

### B. `search.public_web` e uma capability fantasma

O sistema tem sinais de design para busca externa:

- `infer_capability_hints()` reconhece `search.public_web`
- `graph_ops.sync_capabilities_from_graph()` aceita prefixo `search.`
- ha teste de `CapabilityNode.tool("search.public_web")`

Mas o runtime de tooling nao a materializa nem executa.

Na pratica:

- o planner sugere a capability;
- o registry pode ate guardar a capability;
- o runtime nunca a usa.

## Impacto

- pedidos como "busque vc", "pesquise agora", "consulte na internet" nao funcionam;
- o usuario recebe respostas evasivas em vez de execucao;
- a arquitetura parece suportar `search.public_web`, mas isso e enganoso;
- casos de dado atual (preco, cotacao, clima, status, agenda) ficam estruturalmente capados.

## Comportamento esperado

Quando o usuario pedir informacao atual ou mandar buscar, o sistema deve:

1. identificar que o pedido depende de dado externo e atual;
2. sair do `medium_path` puro;
3. resolver capability de busca/consulta externa;
4. executar uma capability real ou, se indisponivel, falhar de forma honesta e estruturada;
5. citar a fonte usada no resultado final.

## Comportamento atual

O sistema:

1. classifica como `intermediate`;
2. responde so com LLM;
3. nao consulta fonte nenhuma;
4. finge limitação operacional em linguagem natural.

## Correcao recomendada

### 1. Introduzir detecao explicita de "current info / external lookup"

No classificador de request, detectar sinais como:

- `preco`, `cotacao`, `agora`, `hoje`, `tempo real`, `atual`
- `busque`, `pesquise`, `consulte`, `veja`, `procure`
- entidades tipicas de dado externo: moeda, clima, bolsa, voo, agenda, noticia

Esses pedidos nao devem ir para `medium_path` puro.

### 2. Fazer `medium_path` escalar para pipeline quando houver dependencia externa

Opcoes aceitaveis:

- reclassificar como `complex`;
- ou criar um `intermediate_with_tooling`;
- ou passar `AdaptivePlanner` e capability resolution tambem no caminho curto.

Mas o estado atual nao pode continuar.

### 3. Tornar `search.public_web` uma capability real do runtime

No minimo:

- incluir `search.` em `_collect_tooling_targets()`
- incluir `search.` em `_collect_tool_execution_targets()`
- mapear `search.public_web` para workflow/tool execution

Se nao houver implementacao real de busca, entao remover a promessa implicita e nao inferir essa capability ainda.

### 4. Cobrir com testes de regressao

Adicionar testes para:

- `classify_request("busque na web o preco do dolar")` nao cair em `medium_path` puro;
- `AdaptivePlanner` + capability resolution com `search.public_web`;
- workflow materializado conter `execute_tooling` ou equivalente para `search.public_web`;
- turno real com comando de busca nao responder com texto evasivo sem tentar capability.

## Criterios de aceite

- `busque na web o preco do dolar comercial` nao pode terminar em `medium_response()` puro.
- `search.public_web` deve participar de capability resolution e workflow executavel.
- Se houver module_path para `search.public_web`, o runtime deve tentar executar.
- Se a capability estiver ausente, a falha precisa aparecer como capability/tooling gap, nao como resposta genrica de chat.
- Deve haver teste automatizado cobrindo o caso.

## Observacoes secundarias

Nao sao a causa principal desta issue, mas apareceram no mesmo transcript:

- `infer_objectives()` e permissivo demais e extrai objetivos de clausulas hesitantes, gerando proatividade estranha.
- mensagens proativas ficaram com texto ruim e duplicacao de `?`.

Esses pontos merecem issue separada.
