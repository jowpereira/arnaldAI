# ISSUE-001 - Divergencia entre comportamento documentado e runtime de chat

## Status
Aberta

## Contexto
O modo chat em runtime graph esta operando em strict_real e com streaming de trace/evidence/prompts, mas ainda existem divergencias de execucao em relacao ao comportamento esperado nos docs operacionais.

## Problema
Para turnos curtos de analise em CLI (ex: "analise a acao bradesco"), o runtime deveria materializar workflow compacto de 1 etapa `draft_artifact` no tier `fast`.

Na pratica, em alguns cenarios de sessao, o runtime materializa pipeline longa (6 etapas) e pode herdar parametros antigos de synapse (`max_tokens`, `timeout`) do grafo persistido, causando latencia alta e falhas de parse estruturado no fim da cadeia.

## Evidencias
- `runs/run_489a67f31b40/graph-workflow-materialized.json` mostra `step_count=6` para turno curto de analise em CLI.
- `runs/run_489a67f31b40/task-ir.json` mostra `context.original_request` enriquecido com contexto de sessao, aumentando contagem de palavras e impedindo heuristica de latencia.
- `arnaldo/runtime/graph_runtime.py` reaproveita synapse com merge de payload; campos nao atualizados podem permanecer de runs anteriores.

## Impacto
- Latencia muito acima do esperado para chat interativo.
- Possivel timeout/falha de validacao JSON em cadeias longas.
- Comportamento percebido pelo usuario diverge do contrato operacional descrito na documentacao.

## Causa raiz (hipotese forte)
1. Heuristica de "latency sensitive cli turn" usa `original_request`, mas esse campo recebe request compilado com contexto adicional do adaptive planner.
2. Upsert de synapse com merge de payload preserva campos operacionais antigos quando o workflow atual nao reescreve explicitamente esses campos.

## Escopo de correcao
1. Separar no pipeline:
   - `raw_user_request` (texto cru do usuario)
   - `compiled_request` (texto enriquecido para contexto)
2. Basear heuristica de latencia em `raw_user_request`.
3. Garantir limpeza/normalizacao de campos volateis no upsert de synapse (`max_tokens`, `timeout`, `reasoning_effort`, `reasoning_summary`) para evitar heranca indevida entre runs.
4. Alinhar docs para remover contradicoes entre "strict_real sem fallback" e descricoes antigas de fallback heuristico.

## Criterios de aceite
- Turno curto de analise/decisao em CLI materializa exatamente 1 step (`draft_artifact`, `fast`) quando nao houver lacuna de tooling dinamico.
- Parametros de step no prompt (`max_tokens`, `timeout`) refletem o workflow atual, sem vazamento de runs anteriores.
- Reproducao local do caso "analise a acao bradesco" conclui sem pipeline longa inesperada.
- Testes automatizados cobrindo os dois pontos (heuristica de latencia + higiene de payload em upsert).

## Prioridade
Alta (impacto direto em UX do chat real)
