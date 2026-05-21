---
name: refactor
description: 'Refatoração guiada com preservação de testes e funcionalidade.'
tools: ['edit/createFile', 'edit/editFiles', 'edit/rename', 'search/codebase', 'search/fileSearch', 'search/textSearch', 'search/listDirectory', 'search/searchSubagent', 'search/usages', 'read/readFile', 'read/problems', 'read/terminalLastCommand', 'read/terminalSelection', 'execute/runInTerminal', 'execute/getTerminalOutput', 'execute/runTests']
argument-hint: 'Descreva o que quer refatorar ou selecione o código'
---

Refatore o código indicado seguindo este processo:

1. **Rode testes existentes** — Confirme que passam ANTES de qualquer mudança
2. **Analise dependências** — Use `usages` para encontrar todos os call sites
3. **Aplique refatoração** — Mudanças incrementais, uma de cada vez
4. **Rode testes após cada mudança** — Se quebrarem, reverta e tente outra abordagem
5. **Valide linting** — `uv run ruff check --fix arnaldo/ tests/`

## Princípios
- **Preserve a API pública** — Assinaturas externas não mudam sem acordo
- **Incremental** — Commits pequenos e verificáveis
- **Sem mudança de comportamento** — Refactor ≠ feature
- **Nomeação clara** — Se o novo nome não é melhor, não renomeie
