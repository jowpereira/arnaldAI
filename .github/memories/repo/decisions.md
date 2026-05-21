# Decisões Técnicas (ADR)

> Arquivo vivo. Cada decisão segue formato: título, contexto, decisão, trade-off.
> Formato de data: `[YYYY-MM]`
> Regra: decisão registrada aqui NÃO é re-debatida sem evidência nova.

---

<!-- Registrar ADRs aqui conforme decisões são tomadas -->

## ADR-001: Fallback e Else Catch-All São PROIBIDOS [2026-05]

**Contexto:** Padrões de fallback (if/else genérico, except pass, heurística quando LLM falta) escondem a causa raiz de problemas. O sistema finge funcionar quando na verdade está degradado.

**Decisão:** Fallback e else catch-all são proibidos em TODO o codebase. Cada path de código deve ser explícito. Se algo falha, falha alto com logging e raise.

**Trade-off:** Código pode falhar mais em desenvolvimento quando dependências não estão configuradas. Isso é INTENCIONAL — melhor falhar cedo do que fingir que funciona.

**Regras concretas:**
- Sem `except Exception: pass` — sempre log + raise ou tratar caso específico
- Sem `_heuristic_fallback()` — se precisa de LLM, exija LLM
- Sem "retorna qualquer coisa quando não acha" — retorna vazio explícito
- Sem `else` genérico — cada condição tratada explicitamente
