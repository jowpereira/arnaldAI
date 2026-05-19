# ISSUE-001 - Gap de comportamento agentivo em pedidos de analise

## Status
Aberta

## Problema real
O runtime responde, mas nao esta se comportando como agente executor em pedidos como:
- "analise a acao bradesco"
- "analise a acao do bradesco nos ultimos anos"

Em vez de investigar, montar workflow de aquisicao de evidencia e usar/forjar ferramenta quando necessario, ele segue majoritariamente por synapses textuais genericas e entrega saidas pouco operacionais.

## Divergencia com os docs
Os docs prometem:
1. agentes especializados com responsabilidade clara e composicao real de workflows;
2. enriquecimento dinamico do workflow no runtime;
3. uso de tooling dinamico (`design_tooling`, `stabilize_tooling`, `execute_tooling`, `compose_tooling`) quando pertinente;
4. execucao orientada a evidencia, nao apenas texto generico.

Hoje, no caso de analise de ativo, esse comportamento esperado nao esta aparecendo de forma confiavel no fluxo principal.

## Comportamento observado
Em reproducoes reais de chat:
- o plano materializado pode cair em pipeline textual longa (ex.: 6 steps) sem acionar tooling;
- nao houve tentativa efetiva de criar/rodar funcao para coletar dados do ativo;
- a resposta final fica em tom de "aguardando objetivo" ou perguntas abertas, distante de uma analise executada.

## Evidencias objetivas
- `runs/run_489a67f31b40/graph-workflow-materialized.json`: workflow sem `execute_tooling`, com cadeia textual.
- `runs/run_489a67f31b40/prompts.jsonl`: prompts de `frame_intent`/`clarify_uncertainties`/`decompose_work`/`draft_artifact` sem fase concreta de aquisicao de dados.
- `runs/run_489a67f31b40/evidence.jsonl`: nao registra execucao de tooling para o caso.

## Causas provaveis
1. Heuristica de capability hints insuficiente para dominio financeiro
- Pedido "analise acao bradesco" nao injeta automaticamente capability de dados externos/mercado.

2. Contrato do fluxo de analise ainda generico
- `analyze_or_evaluate` nao exige por contrato uma etapa de evidencia observavel (tool call, fonte, janela temporal).

3. Materializacao favorece pipeline textual
- Mesmo com componentes dinamicos existentes, o caminho default ainda consegue "resolver" sem tentar ferramenta quando deveria.

4. Reuso de synapse pode carregar estado operacional antigo
- Parametros de payload podem vazar entre runs e degradar previsibilidade do comportamento.

## Escopo de correcao
1. Roteamento semantico para analise de ativos
- Ao detectar entidades de mercado (acao, ticker, empresa listada, bolsa), adicionar capability needs de dados de mercado/public web por padrao.

2. Obrigatoriedade de fase de evidencia em `analyze_or_evaluate`
- Workflow de analise deve incluir etapa de coleta/validacao de dados antes da sintese final.

3. Forja/execucao dinamica quando faltar capability
- Se nao houver modulo disponivel, acionar `design_tooling` -> `execute_tooling` (ou `stabilize_tooling`) e registrar no trace/evidence.

4. Higiene de payload no upsert de synapse
- Evitar heranca indevida de `max_tokens`, `timeout`, `reasoning_*` entre runs.

5. Resposta final orientada a tarefa
- Para pedidos de analise, retornar analise concreta com premissas e limites, em vez de apenas pedir objetivo novamente.

## Criterios de aceite
1. Caso: "analise a acao bradesco"
- Run precisa registrar tentativa concreta de aquisicao de evidencia:
  - `execute_tooling` bem-sucedido, ou
  - cadeia `design_tooling`/`stabilize_tooling`/`execute_tooling` com erro explicito e rastreavel.

2. Artifact final
- Deve conter analise do ativo (nao apenas placeholders), com:
  - periodo analisado,
  - premissas,
  - incertezas reais,
  - proximos passos acionaveis.

3. Observabilidade
- `trace.jsonl` e `evidence.jsonl` devem refletir claramente a etapa de evidencia (tooling ou falha explicita de tooling).

4. Testes
- Cobertura automatizada para:
  - detecao de intents financeiras e injecao de capabilities,
  - materializacao de workflow com fase de evidencia,
  - comportamento quando ferramenta nao existe,
  - ausencia de vazamento de payload entre runs.

## Prioridade
Alta (quebra expectativa central do produto: agir como agente executor, nao apenas responder texto)
