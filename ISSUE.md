# Investigacao forense: fluxo conversa/executa desconectado e resposta final corrompida

## Resumo executivo

O comportamento observado no transcript nao e um erro isolado de prompt. Ele resulta da combinacao de pelo menos 5 problemas de arquitetura/encadeamento:

1. O entrypoint usado no teste (`python -m arnaldo --chat-stream`) nao habilita `llm_classify`, ao contrario de `arnaldo/chat.py`.
2. O sistema nao possui capability nativa para shell/filesystem local. Hoje ele so tem execucao builtin para `search.public_web` e `connector.http.generic`.
3. O pedido "ache a pasta" foi classificado como `open_ended_execution`, mas o runtime o rebaixou para `conversational_cli` e reduziu o workflow para 1 unico `draft_artifact`.
4. A resposta final ao usuario foi sintetizada usando `step.output` (`primary_artifact`) em vez do `step.result`, o que explica a frase falsa "Encontrei o arquivo/pasta principal chamado primary_artifact".
5. Mesmo depois de detectar `deliverables_missing`, o pipeline ainda gravou a resposta errada na sessao, memoria e contexto dos turnos seguintes, contaminando o resto da conversa.

Impacto pratico:

- O sistema afirma ter executado/descoberto algo que nao executou.
- A memoria de sessao aprende uma resposta errada e a reutiliza.
- O turno seguinte herda contexto poluido e continua preso em fluxo de artefato textual.
- Quando o usuario pede "rode os comandos e descubra", o sistema continua num circuito quase todo-LLM e morre por timeout sem executar tooling real.

## Reproducao observada

Transcript analisado:

- `tenho o mt5 instalado ache a pasta`
- `win`
- `rode os comandos e descubra`

Runs correspondentes:

- `runs/run_48f0bfc91963`
- `runs/run_7be2000bd5e0`
- `runs/run_9d7081135b39`

## Revalidacao posterior com `uv run python -m arnaldo.chat --autonomy autonomo`

Depois da primeira investigacao, foi feita uma segunda reproducao via:

- `uv run python -m arnaldo.chat --autonomy autonomo`

Novas runs geradas:

- `runs/run_bb5a8e75e49c`
- `runs/run_f928f9fe182d`
- `runs/run_e35541e16eff`
- `runs/run_6ff48a798bf6`
- `runs/run_a25f6d5e8f2f`
- `runs/run_50a6ad8d3982`

Resultado da reverificacao:

- O bug de resposta com `primary_artifact` **nao** reproduziu nessa segunda sessao.
- O sistema respondeu diferente porque **nao entrou no full pipeline**.
- As novas runs contem apenas:
  - `response.md`
  - `learning.json`
- Isso caracteriza `fast_response` ou `medium_response`, nao `run_full_pipeline`.

Evidencia:

- `runs/run_50a6ad8d3982/learning.json`
  - `path = "medium"`
- `runs/run_bb5a8e75e49c/learning.json`
  - `path = "medium"`
- As runs novas nao possuem:
  - `trace.jsonl`
  - `evidence.jsonl`
  - `artifact.md`
  - `graph-workflow-materialized.json`

Conclusao:

- O `issue` original continua valido para o caminho que entra em full pipeline.
- Mas ele precisa ser **reescopado**: a segunda reproducao caiu em outro motor de resposta.

### O que realmente mudou

Minha leitura anterior estava incompleta se interpretada como "usar `arnaldo.chat` resolve porque ativa LLM classify".

Tecnicamente:

- `arnaldo/chat.py` realmente chama `kernel.run(..., llm_classify=True)`
- mas isso **nao foi o fator decisivo** nesta segunda reproducao
- o `kernel.run(...)` primeiro chama `brain_activate(...)`
- se a confianca do brain passa do threshold, ele **nem entra** na classificacao LLM

Medicao no estado atual do grafo:

- para `ache onde esta instalado, quero ver se sabe shell`
  - `primary_synapse = synmem_449ebb80e44a`
  - `complexity = intermediate`
  - `skip_full_pipeline = True`
  - `confidence = 0.302...`
- para `tenho o mt5 instalado ache a pasta`
  - `primary_synapse = synmem_449ebb80e44a`
  - `complexity = intermediate`
  - `skip_full_pipeline = True`
  - `confidence = 0.376...`
- para `oi`
  - `primary_synapse = synmem_449ebb80e44a`
  - `complexity = intermediate`
  - `skip_full_pipeline = True`
  - `confidence = 0.561...`

Interpretacao:

- O grafo aprendeu um atalho forte de conversa/continuidade (`synmem_449ebb80e44a`).
- Esse atalho agora desvia varios pedidos para `medium_response`.
- Portanto a diferenca entre a primeira e a segunda reproducao veio principalmente do **estado aprendido do grafo**, nao apenas do entrypoint.

### O que isso nao resolve

Mesmo no `arnaldo.chat`, o sistema **ainda nao executou shell real**.

Evidencia:

- `runs/run_50a6ad8d3982/response.md` respondeu:
  - "Nao tenho como achar no seu PC..."
  - e apenas sugeriu comandos PowerShell
- `arnaldo/kernel/fast_path.py`
  - `fast_response(...)` faz 1 chamada LLM
  - `medium_response(...)` faz retrieval + routing + 1 chamada LLM
  - nenhum dos dois executa tooling local

Conclusao adicional:

- A segunda reproducao nao invalida o diagnostico "o sistema nao fecha a ponte para shell local".
- Ela so mostra que, no estado atual do grafo, o pedido esta sendo interceptado antes de chegar no full pipeline bugado.

### Ajuste no escopo do issue

Escopo revisado do problema:

1. **Bug A: full pipeline + sintese final**
   - quando o pedido chega ao full pipeline, a sintese pode vazar `primary_artifact` para a resposta final
2. **Bug B: ausencia de capability de shell/filesystem local**
   - mesmo fora do full pipeline, o sistema nao executa descoberta local real
3. **Bug C: desvio excessivo para medium path por memoria associativa**
   - o grafo atual esta promovendo `synmem_449ebb80e44a` cedo demais, ate para inputs como `oi`

## Linha do tempo forense

### 1. O primeiro pedido foi tratado como conversa curta, nao como descoberta local

Evidencia:

- `runs/run_48f0bfc91963/request-classification.json`:
  - `level = complex`
  - `reason = graph_classified`
  - `needs_external_data = false`
  - `capability_needs = []`
- `runs/run_48f0bfc91963/graph-workflow-materialized.json`:
  - `step_count = 1`
  - unico step = `draft_artifact`

Interpretacao:

- O pedido nao virou "execucao local".
- O runtime considerou o turno "conversational_cli" e colapsou o workflow para resposta direta via `draft_artifact`.

Codigo envolvido:

- `arnaldo/runtime/graph_runtime/classify.py:102-175`
  - `_is_conversational_cli_turn(...)` aceita qualquer `open_ended_execution` curto de CLI se nao detectar intencao estruturada.
  - `_contains_structured_execution_intent(...)` nao cobre verbos como `achar`, `encontrar`, `localizar`, `rodar comando`, `PowerShell`, `pasta`, `filesystem`.
- `arnaldo/runtime/graph_runtime/workflow.py:200-221`
  - quando `conversational_cli == True`, o workflow vira apenas `draft_artifact`.

### 2. O entrypoint do teste nao usou classificacao LLM

Evidencia:

- O usuario rodou `python -m arnaldo --chat-stream --autonomy autonomo`.
- `arnaldo/cli/main.py:165-185` chama `kernel.run(...)` sem `llm_classify=True`.
- `arnaldo/chat.py:132-138` chama `kernel.run(..., llm_classify=True)`.
- O arquivo `runs/run_48f0bfc91963/request-classification.json` mostra `reason = graph_classified`, nao `llm_classified`.

Interpretacao:

- O caminho de CLI usado no teste e semanticamente mais fraco do que o REPL de `arnaldo/chat.py`.
- Isso reduz a chance de inferir `capability_needs` mais ricos.

### 3. Nao existe capability nativa para shell/filesystem local

Evidencia de codigo:

- `arnaldo/capabilities/registry.py:14-17`
  - builtins executaveis: apenas `search.public_web` e `connector.http.generic`
- `arnaldo/components/capability_registry.py:105-123`
  - registry default nao inclui nenhuma capability de shell, PowerShell, filesystem ou descoberta local
- Busca textual no codigo nao encontrou capability dedicada a shell/filesystem local

Interpretacao:

- Mesmo com policy liberando rede e escrita em workspace, o sistema nao tem uma ferramenta nativa para cumprir "ache a pasta" no Windows.
- O maximo que ele pode fazer hoje e responder por heuristica textual, buscar web, chamar HTTP, ou executar modulo dinamico de ToolForge.

### 4. O adaptive planner tambem nao infere capability para execucao local

Evidencia:

- `arnaldo/components/adaptive_planner.py:135-182`
  - reconhece apenas:
    - `connector.http.generic`
    - `connector.github`
    - `connector.crm`
    - `tool.dynamic.build`
    - `search.public_web`
- Execucao local manual:
  - `infer_capability_hints('tenho o mt5 instalado ache a pasta') -> []`
  - `infer_capability_hints('rode os comandos e descubra') -> []`
  - `infer_capability_hints('rode comandos powershell para achar a pasta do mt5') -> []`

Interpretacao:

- O planner nao tem nenhum caminho de inferencia para `filesystem.local.search`, `shell.local.readonly` ou equivalente.

### 5. Mesmo que a classificacao detecte capabilities, o full pipeline quase nao usa esse sinal

Evidencia:

- `arnaldo/kernel/classify.py:91-101`
  - `RequestComplexity` carrega `capability_needs`
- `arnaldo/kernel/kernel.py:73`
  - quando vem do brain, `decision.capability_needs` entra em `RequestComplexity`
- `arnaldo/components/task_compiler.py:57` e `:94-102`
  - `TaskCompiler` ignora esse sinal e cria sempre o mesmo conjunto fixo de capabilities genericas
- `arnaldo/kernel/pipeline.py:47-58`
  - o pipeline so faz merge com `adaptive_plan.capability_hints`
  - ele nao incorpora `complexity.capability_needs`

Interpretacao:

- Mesmo se a camada de classificacao descobrir tooling necessario, esse sinal nao esta encadeado de forma consistente ate `task.capability_needs`.

### 6. O sistema sabia que nao tinha entregue tudo, mas mesmo assim respondeu como se tivesse dado conta

Evidencia:

- `runs/run_48f0bfc91963/evidence.jsonl`
  - `reality_gap_detected | deliverables_missing`
  - `hebbian_post_run | run_success = false`
- `runs/run_48f0bfc91963/result.md`
  - mostra ciclo generico executado
- `runs/run_48f0bfc91963/artifact.md`
  - Step Outputs: apenas `draft_artifact: primary_artifact`

Interpretacao:

- O detector de gap percebeu o erro.
- Mesmo assim, o pipeline continuou para sintese de resposta, gravacao em sessao e proatividade.

### 7. A frase "primary_artifact" saiu da etapa de sintese final, nao da execucao real

Evidencia de dados:

- `runs/run_48f0bfc91963/trace.jsonl`
  - `step_completed.payload.output = "primary_artifact"`
  - `step_completed.payload.result.sections[0]` contem a resposta textual correta do planner
- Reconstrucao do prompt de sintese:
  - `build_synthesis_messages(step_results=[step], original_request='tenho o mt5 instalado ache a pasta')`
  - gerou literalmente:
    - `[Step 1 (OK)]: primary_artifact`
- `storage/sessions/session_ac00763565d7.history.jsonl`
  - a resposta persistida foi:
    - `Encontrei o arquivo/pasta principal chamado "primary_artifact"...`

Codigo causador:

- `arnaldo/prompts/context.py:67-72`
  - a sintese usa `step.get("output", step.get("summary", ""))`
  - isso consome o nome do deliverable, nao o conteudo real do step
- `arnaldo/kernel/fast_path.py:192-215`
  - `synthesize_response(...)` usa esse prompt e tambem, no fallback sem LLM, concatena `step["output"]`

Interpretacao:

- O nome interno do deliverable vazou para a resposta em linguagem natural.
- Esta e a causa direta da resposta absurda "achei a pasta primary_artifact".

### 8. A resposta errada contaminou memoria, sessao e contexto dos turnos seguintes

Evidencia de dados persistidos:

- `storage/sessions/session_ac00763565d7.history.jsonl`
  - a resposta errada foi gravada como `system_summary`
- `storage/sessions/session_ac00763565d7.json`
  - a resposta errada entrou em `message_history`
- `storage/memory/procedural.jsonl`
  - a run persistiu apenas `action = draft_artifact`
- `storage/memory/prospective.jsonl`
  - o sistema so guardou perguntas pendentes, nao um resultado de descoberta local
- `storage/proactivity/session_ac00763565d7.jsonl`
  - agendou mensagem proativa baseada em incerteza:
    - `Você usa qual sistema operacional...?`
- `runs/run_9d7081135b39/prompts.jsonl`
  - o prompt do turno seguinte inclui `Contexto prévio (últimos outputs)` com o output textual da run anterior

Interpretacao:

- O erro nao ficou restrito a um turno.
- Ele foi promovido a memoria de sessao e reutilizado como contexto "relevante".

### 9. A segunda run continuou sem tooling real e terminou em timeout de LLM

Evidencia:

- `runs/run_9d7081135b39/task-ir.json`
  - `goal.type = execute_or_automate`
- `runs/run_9d7081135b39/capability-resolution.json`
  - apenas capabilities genericas locais
  - `missing = []`
  - `degraded = []`
- `runs/run_9d7081135b39/graph-workflow-materialized.json`
  - 5 steps: `frame_intent`, `clarify_uncertainties`, `decompose_work`, `draft_artifact`, `critic_review`
  - nenhum `execute_tooling`
- `runs/run_9d7081135b39/trace.jsonl`
  - apenas `prompt_prepared`
  - nenhum `step_completed`
- `storage/sandboxes/run_9d7081135b39/artifacts`
  - vazio
- `runs/run_9d7081135b39` nao contem:
  - `artifact.md`
  - `result.md`
  - `execution-graph.msgpack`
  - `graph-capability-sync.json`
  - `request-classification.json`

Erro final:

- `strict_real habilitado: chamada LLM falhou no synapse 'syn_planner_draft_artifact_primary_artifact': Azure OpenAI timeout após 25.0s`

Interpretacao:

- O pedido "rode os comandos e descubra" ainda nao virou execucao real.
- O sistema apenas empilhou mais 3 prompts de planejamento + 1 prompt de `draft_artifact`.
- Quando o ultimo prompt estourou timeout, a run morreu antes de produzir qualquer artefato util.

### 10. Policy nao bloqueou a acao; o problema e de planejamento/capability

Evidencia:

- `runs/run_48f0bfc91963/policy-decision.json`
- `runs/run_9d7081135b39/policy-decision.json`

Dados:

- `allowed = true`
- `approval_required = false`
- `network = read_write`
- `filesystem = workspace_write`
- `external_messages = allowed`
- `notes = governance bypass ativo no modo graph`

Interpretacao:

- O runtime tinha permissao para agir dentro do sandbox.
- Ele nao agiu porque o workflow nunca pediu execucao local real.

## Evidencia adicional dos dados gerados

### Sandbox da run 48

- `storage/sandboxes/run_48f0bfc91963/artifacts/step-01-draft_artifact.json`
  - confirma que o unico artefato real da run foi o JSON do step `draft_artifact`
- `storage/sandboxes/run_48f0bfc91963/tmp/runtime-finished.txt`
  - `completed=true`

Conclusao:

- A run terminou "normalmente", mas terminou sem fazer descoberta local.

### Grafo da run 48

Inspecao do `runs/run_48f0bfc91963/execution-graph.msgpack`:

- 22 nos
- 26 arestas
- synapses incluem `syn_planner_draft_artifact_primary_artifact`
- capabilities incluem:
  - `cap-search-web`
  - `cap-http-generic`
  - capacidades genericas de pipeline
- a synapse `syn_planner_draft_artifact_primary_artifact` possui:
  - `requires -> cap_artifact_draft`
  - `derived_from -> synwf_org_e50e7965cd20_task_df2df122e86a`
  - `mentions -> mem_run_48f0...`
- ela nao possui edge para `cap-search-web` ou `cap-http-generic`

Conclusao:

- As capabilities dinamicas existem no grafo, mas nao participaram do workflow desta run.

### Grafo de memoria apos a run 48

Inspecao do `storage/memory/memory-graph.msgpack`:

- 21 nos
- 89 arestas
- 9 memórias
- synapse materializada: `synmem_449ebb80e44a`

Conclusao:

- O sistema aprendeu padrao de conversa/continuidade a partir de um turno que ja estava errado.
- Isso ajuda a explicar o `memory_hints.json` da run 9:
  - `preferred_actions = ["conversa", "draft_artifact"]`

## Causa raiz consolidada

### Causa raiz primaria

O sistema nao fecha o circuito entre "pedido que exige observacao do mundo real" e "capability que efetivamente executa algo no mundo real".

Hoje o encadeamento esta assim:

- classificacao fraca no entrypoint usado pelo usuario
- nenhuma capability nativa de shell/filesystem
- inferencia de capability local inexistente
- workflow conversational pode colapsar para 1 step textual
- sintese final usa nome de output em vez do conteudo real

### Causas contribuintes

- inconsistencia entre `arnaldo/chat.py` e `arnaldo/cli/main.py`
- `TaskCompiler` fixa `capability_needs` genericos
- `complexity.capability_needs` nao chega de forma clara ao `task`
- `reality_gap_detected` nao impede persistencia de resposta/sessao
- memoria e proatividade sao alimentadas mesmo quando a entrega nao fechou

## Recomendacoes priorizadas

### P0

- Unificar os entrypoints de chat para sempre decidir explicitamente se `llm_classify` deve estar ligado.
- Corrigir a sintese final para usar `step.result` e/ou `result.sections[0]`, nunca `step.output`.
- Impedir que uma run com `deliverables_missing` grave resposta "normal" na sessao sem marcar falha.

### P1

- Adicionar capability builtin de descoberta local read-only, por exemplo:
  - `filesystem.local.search`
  - `shell.local.readonly`
- Ensinar o planner/classificador a inferir essa capability para verbos como:
  - `ache`, `localize`, `encontre`, `procure`
  - `rode os comandos`, `PowerShell`, `terminal`, `pasta`, `arquivo`, `instalado`
- Fazer `execute_or_automate` com contexto de CLI local preferir tooling/local discovery antes de cair em `draft_artifact`.

### P2

- Fazer `TaskCompiler` aceitar capabilities vindas de classificacao/brain, nao apenas o conjunto fixo generico.
- Revisar a heuristica de `conversational_cli` para nao capturar pedidos de descoberta local.
- Bloquear a promocao de outputs incorretos para memoria/proatividade quando `gap_report.status != ok`.

### P3

- Revisar se `policy-decision` deve continuar com `governance bypass ativo no modo graph` quando `terms_accepted = false`.

## Cobertura de teste faltante

Hoje nao encontrei teste cobrindo:

- `build_synthesis_messages(...)`
- `synthesize_response(...)`
- o caso natural-language "ache a pasta" / "rode os comandos"
- a diferenca de comportamento entre `arnaldo/chat.py` e `arnaldo/cli/main.py`
- persistencia de sessao/memoria apos `deliverables_missing`

Ja existe cobertura para o atalho conversacional:

- `tests/test_graph_runtime_integration.py:251-280`
- `tests/test_graph_runtime_integration.py:712-733`

Mas essa cobertura nao valida se o atalho foi escolhido corretamente para pedidos que exigem descoberta local real.

## Hipoteses descartadas

- "A policy bloqueou a execucao": falso. A policy estava `allowed=true`.
- "O sandbox nao foi criado": falso. Os sandboxes das runs 48 e 9 foram provisionados.
- "O sistema executou comandos e so respondeu mal": falso. Nao ha step `execute_tooling`, nao ha artefato de tooling, e a run 48 so persistiu `draft_artifact`.
- "O problema foi apenas timeout Azure": falso. O timeout explica a run 9 morrer, mas a run 48 ja estava conceitualmente errada antes disso.

## Diagnostico final

O sistema esta bom em produzir artefato textual e rastreabilidade interna, mas ainda nao esta fechando a ponte entre intencao operacional e execucao local real. No caso analisado, ele:

- simplificou um pedido operacional para conversa,
- respondeu com texto generico,
- sintetizou o nome do deliverable como se fosse achado real,
- gravou isso como memoria valida,
- e depois reaproveitou esse historico poluido no turno seguinte.

Esse e um bug de confiabilidade de primeira ordem, porque o assistente aparenta ter executado algo que nao executou.
