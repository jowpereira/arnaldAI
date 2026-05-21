---
name: test
description: 'Gera testes pytest para o módulo indicado. Roda e corrige até passar.'
agent: Arnaldo
tools: ['edit/createFile', 'edit/editFiles', 'search/codebase', 'search/fileSearch', 'search/textSearch', 'search/listDirectory', 'search/searchSubagent', 'read/readFile', 'read/problems', 'read/terminalLastCommand', 'read/terminalSelection', 'execute/runInTerminal', 'execute/getTerminalOutput', 'execute/runTests']
argument-hint: 'Selecione um arquivo para testar ou digite o caminho'
---

Delegue ao subagente **tdd** para o arquivo ${file}:

1. **Analise** as funções/classes e identifique cenários de teste:
   - Happy path (fluxo normal)
   - Edge cases (limites, vazios, nulos)
   - Error cases (inputs inválidos, exceções esperadas)

2. **Gere testes** em `tests/test_<módulo>.py` usando pytest

3. **Rode os testes:** `uv run pytest -x -v --tb=short`

4. **Se falharem**, corrija e rode novamente até todos passarem

5. **Garanta cobertura** de edge cases e erros esperados
