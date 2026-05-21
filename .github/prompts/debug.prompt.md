---
name: debug
description: 'Diagnóstico sistemático de bugs com análise de logs, stack traces e reprodução.'
agent: Arnaldo
tools: ['edit/createFile', 'edit/editFiles', 'search/codebase', 'search/fileSearch', 'search/textSearch', 'search/listDirectory', 'search/searchSubagent', 'search/usages', 'read/readFile', 'read/problems', 'read/terminalLastCommand', 'read/terminalSelection', 'execute/runInTerminal', 'execute/getTerminalOutput']
argument-hint: 'Descreva o bug ou cole o stack trace'
---

Diagnostique e corrija o bug: ${input:bug}

## Processo de Diagnóstico

1. **Parse o erro** — Extraia arquivo, linha, tipo de exceção, mensagem
2. **Contextualize** — Leia o código ao redor do erro + callers
3. **Hipóteses** — Liste as 3 causas mais prováveis, ordenadas por probabilidade
4. **Verifique** — Para cada hipótese, busque evidência no código
5. **Corrija** — Aplique o fix para a causa raiz confirmada
6. **Valide** — Rode `uv run pytest -x -v` e confirme que passou
7. **Previna** — Se aplicável, adicione teste que pegaria este bug

## Armadilhas Comuns do ArnaldAI

- **Invariante violado silenciosamente** — Verifique se nós/arestas estão com `SourceRecord` válido, tipagem correta e timestamps bi-temporais
- **Plasticidade fora de bounds** — Pesos devem estar em `[floor, ceiling] ⊂ [0,1]`, com `|Δw| ≤ cap_per_step`
- **Ciclo em GraphRef** — Referências entre grafos formam DAG obrigatório; ciclos geram `GraphCycleError`
- **LLM fallback heurístico** — Se LLM falha, o pipeline usa heurística determinística; verifique se a heurística está retornando IR válido
- **Decay tipado vs uniforme** — Half-life é por domain, nunca uniforme; verificar se `sweep_decay` respeita domínio
- **Serialização msgpack** — Grafo serializado pode ter tipos incompatíveis se schema mudou entre versões
- **Import circular** — `arnaldo/components/`, `arnaldo/graph/`, `arnaldo/llm/` têm fronteiras estritas
- **Tier de LLM errado** — Verificar `arnaldo/llm/router.py:TASK_TIER_MAP` se a task está mapeada para o tier correto
- **structured output strict** — JSON Schema strict do Azure OpenAI rejeita campos opcionais sem default; verificar dataclass em `arnaldo/llm/structured.py`
- **`.env` não carregado** — O cliente LLM carrega `.env` com precedência sobre env vars do shell por padrão
