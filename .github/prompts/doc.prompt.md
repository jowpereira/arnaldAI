---
name: doc
description: 'Gera documentação (docstrings, README, API docs) para o módulo selecionado.'
tools: ['edit/createFile', 'edit/editFiles', 'search/codebase', 'search/fileSearch', 'search/textSearch', 'search/listDirectory', 'read/readFile']
argument-hint: 'Selecione um arquivo ou digite o caminho do módulo'
---

Para o arquivo ou módulo ${file}:

1. **Analise** o código e identifique funções/classes sem documentação
2. **Gere docstrings** seguindo o padrão do projeto:
   - Python: Google-style docstrings com type hints
3. **Documente em Português** — Seguindo as diretrizes do projeto
4. **Inclua:**
   - Descrição do propósito
   - Parâmetros e tipos
   - Retorno e exceções
   - Exemplos de uso quando não trivial
5. **Atualize README** do módulo se existir
