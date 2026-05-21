---
name: deploy
description: 'Prepara e valida o pacote ArnaldAI para publicação. Roda checks de qualidade.'
agent: Arnaldo
tools: ['search/codebase', 'search/fileSearch', 'search/textSearch', 'search/listDirectory', 'read/readFile', 'read/problems', 'read/terminalLastCommand', 'read/terminalSelection', 'execute/runInTerminal', 'execute/getTerminalOutput']
---

Execute o pipeline de validação pré-release do ArnaldAI:

## Checklist de Validação

1. **Testes** — Rode `uv run pytest -x -v` e confirme que passam
2. **Linting** — Rode `uv run ruff check arnaldo/ tests/` e confirme limpo
3. **Formatting** — Rode `uv run ruff format --check arnaldo/ tests/`
4. **Type checking** — Rode `uv run mypy arnaldo/` e confirme sem erros
5. **Secrets** — Verifique que NÃO há secrets hardcoded (busque por patterns: API_KEY, SECRET, PASSWORD, TOKEN em arnaldo/)
6. **CHANGELOG** — Verifique que a versão atual está documentada no CHANGELOG.md
7. **pyproject.toml** — Verifique que a versão está correta e dependências atualizadas
8. **Build** — Rode `uv build` e confirme que o pacote compila

## Em caso de problemas
- Reporte cada issue com severidade e sugestão de fix
- NÃO publique se houver issues críticas
