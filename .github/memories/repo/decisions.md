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

---

## ADR-002: Clarificação — Fallback SILENCIOSO vs. Degradação Graceful [2026-05]

**Contexto:** ADR-001 proíbe fallback, mas na prática existem cenários legítimos de degradação graceful — e.g., LLM indisponível, capability offline, grafo vazio no bootstrap.

**Decisão:** "Fallback proibido" refere-se a fallback **silencioso** — código que engole erros e finge que funciona. Fallback **explícito** com logging é PERMITIDO como degradação graceful intencional, desde que:

1. **Logado:** `logger.warning` ou superior registra que degradação ocorreu
2. **Intencional:** Há comentário ou docstring explicando o fallback
3. **Rastreável:** O resultado indica que veio de path degradado (e.g., campo `degraded=True`)
4. **Reversível:** Quando o recurso volta, o sistema retoma o path normal automaticamente

**Trade-off:** Permite que o sistema continue operando em condições adversas sem esconder problemas. A diferença entre fallback proibido e degradação graceful é **visibilidade**: se o operador sabe que aconteceu, é degradação; se não sabe, é bug.

---

## ADR-003: Implementação completa dos 12 gaps (Eixos A/B/C) [2025-07]

**Contexto:** Análise profunda identificou 14 gaps em 3 eixos — A (Grafo/Plasticidade), B (Memory Store), C (Episteme). 12 implementáveis, 2 dependem de infra futura.

**Decisão:**
- Eixo A: ExecutionSynapseCandidate rastreia padrões → materializa SynapseNodes. Agent memory via GraphRef.OWNED. Recursive plasticity wired.
- Eixo B: Negative memory auto-creation em falhas. Prospective lifecycle (create→resolve). Consolidação episodic→semantic via jaccard clustering.
- Eixo C: Prioridade contextual (domain_relevance*0.5 + urgency*0.3 + staleness*0.2). Entity extraction (backtick, URL, proper nouns, tech terms). Forager governance (blocked domains, token limits). Stale domain + contradiction detection.

**Trade-off:** Complexidade incremental (~800 linhas de código novo, ~50 testes novos), mas cada módulo é independente e ≤300 linhas. Todos os invariantes preservados.
