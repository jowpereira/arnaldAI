---
name: knowledge-capture
description: 'Captura fatos, decisões e gotchas descobertos na sessão atual e registra na memória do repo.'
agent: Arnaldo
tools: ['vscode/memory', 'search/codebase', 'read/readFile']
argument-hint: 'Descreva o que foi descoberto ou deixe vazio para scan automático'
---

Revise a sessão atual e capture conhecimento novo na memória do repo.

## Processo

1. **Identifique** o que foi descoberto nesta sessão:
   - Bugs resolvidos e suas causas raiz
   - Decisões técnicas tomadas (explícitas ou implícitas)
   - Workarounds ou padrões que funcionaram
   - Armadilhas evitadas ou encontradas
   - Mudanças estruturais no código

2. **Verifique** se já está registrado:
   - Leia `/memories/repo/gotchas.md` para evitar duplicação
   - Leia `/memories/repo/decisions.md` para verificar ADRs existentes

3. **Registre** nos arquivos corretos:
   - Gotcha/lição → `/memories/repo/gotchas.md`
   - Decisão técnica → `/memories/repo/decisions.md`
   - Mudança estrutural → `/memories/repo/architecture.md`
   - Novo módulo/arquivo importante → `/memories/repo/navigation.md`

4. **Confirme** o que foi registrado com um resumo

## Formato
- Sempre prefixar com `[YYYY-MM]`
- Uma linha por fato, máximo 2 linhas se precisar de contexto
- Seção correta dentro do arquivo (Redis, Frontend, Azure, etc.)

${input:contexto}
