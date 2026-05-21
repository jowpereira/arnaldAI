---
applyTo: "**"
description: "Protocolo de captura de conhecimento — memória viva que evolui a cada sessão"
---

# Protocolo de Captura de Conhecimento

## Princípio

A memória do projeto é **viva**. Cada sessão de trabalho pode descobrir fatos novos, gotchas, decisões ou padrões. O agente DEVE registrar conhecimento novo quando relevante.

## Memória Repo (persistente entre sessões)

| Arquivo | Conteúdo | Quando atualizar |
|---------|----------|-----------------|
| `/memories/repo/architecture.md` | Stack, fluxos, estrutura principal | Mudança estrutural (novo módulo, nova integração) |
| `/memories/repo/decisions.md` | Decisões técnicas (ADR) | Decisão tomada que muda padrão/arquitetura |
| `/memories/repo/gotchas.md` | Erros que já aconteceram, lições | Bug resolvido, workaround descoberto, armadilha encontrada |
| `/memories/repo/navigation.md` | "Onde acho X?" — busca rápida | Novo módulo criado, arquivo importante movido |
| `.github/memories/repo/infrastructure.md` | Constraints de infra Azure | Mudança de serviço, constraint nova |

## Quando Registrar (obrigatório)

1. **Bug resolvido com causa raiz não-óbvia** → Adicionar em `gotchas.md` com data e contexto
2. **Decisão técnica tomada** → Adicionar ADR em `decisions.md` (formato: título, contexto, decisão, trade-off)
3. **Workaround descoberto** → `gotchas.md` na seção do domínio relevante
4. **Novo módulo/serviço criado** → Atualizar `architecture.md` e `navigation.md`
5. **Constraint de infra descoberta** → `gotchas.md` ou `infrastructure.md`

## Quando NÃO Registrar

- Mudanças triviais (typo, formatação)
- Informação que já está registrada (verificar ANTES)
- Fatos temporários de sessão (usar session memory para isso)

## Formato de Registro

Prefixar com data: `- [YYYY-MM] Descrição concisa — contexto mínimo necessário`

## Regra de Ouro

> Se você gastou > 15 minutos investigando algo, o resultado DEVE ser registrado.
> A próxima sessão não deve re-investigar o mesmo problema.
