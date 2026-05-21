---
name: plan
description: 'Cria plano de implementação detalhado para nova feature ou bugfix.'
agent: Arnaldo
tools: ['search/codebase', 'search/fileSearch', 'search/textSearch', 'search/listDirectory', 'search/searchSubagent', 'search/usages', 'read/readFile', 'read/problems', 'web/fetch']
argument-hint: 'Descreva a feature ou issue a ser planejada'
---

Delegue ao subagente **planner** para analisar o codebase e criar um plano de implementação detalhado para: ${input:tarefa}

## O plano DEVE conter:

### 1. Contexto
- Arquivos relevantes encontrados (com paths e linhas)
- Padrões existentes que devem ser seguidos
- Dependências afetadas

### 2. Tarefas (checklist ordenado)
- Cada tarefa com: arquivo alvo, mudança, critério de done
- Ordenadas por dependência

### 3. Decisões de Design
- Trade-offs e alternativas
- Riscos identificados

### 4. Critérios de Aceitação
- Testes que devem existir
- Comportamento esperado
- Edge cases
