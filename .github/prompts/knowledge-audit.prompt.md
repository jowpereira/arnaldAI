---
name: knowledge-audit
description: 'Audita a memória do repo — verifica fatos desatualizados, gaps, duplicações e saúde geral.'
agent: Arnaldo
tools: ['vscode/memory', 'search/codebase', 'search/fileSearch', 'read/readFile', 'search/textSearch']
argument-hint: 'Foco em algum domínio específico? (backend, frontend, infra, ou vazio para tudo)'
---

Faça uma auditoria da memória do repositório e proponha atualizações.

## Checklist de Auditoria

### 1. Verificar Frescor
- Leia cada arquivo em `/memories/repo/`
- Para cada fato com data, verifique se ainda é verdade consultando o código atual
- Marque fatos obsoletos para remoção/atualização

### 2. Verificar Gaps
- Compare `architecture.md` com a estrutura real do workspace (arquivos, módulos)
- Identifique módulos/serviços que existem no código mas não estão documentados
- Verifique se `navigation.md` tem paths corretos

### 3. Verificar Duplicações
- Cruze `gotchas.md` com `decisions.md` — informação duplicada?
- Cruze `architecture.md` com `.github/instructions/project.instructions.md`

### 4. Propor Atualizações
- Liste fatos para remover (obsoletos)
- Liste fatos para adicionar (gaps)
- Liste fatos para corrigir (desatualizados)
- Peça confirmação antes de aplicar

### 5. Métricas de Saúde
Reporte:
- Total de fatos registrados por arquivo
- Fatos sem data (não rastreáveis)
- Fatos > 6 meses sem verificação
- Gaps identificados

${input:foco}
