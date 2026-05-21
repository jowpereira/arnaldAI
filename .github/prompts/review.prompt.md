---
name: review
description: 'Revisão de código multi-perspectiva: segurança, qualidade, performance, arquitetura.'
agent: Arnaldo
tools: ['search/codebase', 'search/fileSearch', 'search/textSearch', 'search/listDirectory', 'search/searchSubagent', 'search/usages', 'search/changes', 'read/readFile', 'read/problems', 'agent/runSubagent']
---

Delegue ao subagente **reviewer** para revisar as mudanças recentes do workspace. Analise de múltiplas perspectivas:

1. **Segurança** — Validação de input, injection, exposição de dados, auth
2. **Qualidade** — Legibilidade, naming, duplicação, type safety, error handling
3. **Performance** — Queries N+1, loops pesados, memory leaks, bloqueio async
4. **Arquitetura** — Padrões do projeto, separação de responsabilidades, acoplamento

Apresente um relatório priorizado:
- 🔴 Crítico (bloqueia merge)
- 🟡 Importante (deveria corrigir)
- 🟢 Sugestão (nice-to-have)

Inclua sugestão de fix para cada issue encontrada.
