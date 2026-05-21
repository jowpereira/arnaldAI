# Gotchas & Lições Aprendidas

> Arquivo vivo. Consultar ANTES de investigar problemas.
> Formato: `- [YYYY-MM] Descrição — contexto`

---

## LLM / Azure OpenAI

<!-- Registrar gotchas de chamadas LLM, tiers, structured outputs, etc. -->

## Grafo Cognitivo

<!-- Registrar gotchas de nós, arestas, plasticidade, decay, serialização, etc. -->

## Runtime / Execução

<!-- Registrar gotchas de runtime, sandbox, workflows, etc. -->

## Kernel / Pipeline

- [2026-05] LEI: fallback e else catch-all são PROIBIDOS — fallback é degradação silenciosa que esconde bugs
- [2026-05] `_heuristic_fast_response` era fallback quando LLM não configurado — removido, agora raise RuntimeError
- [2026-05] `except Exception: pass` em synthesize_response, _try_spawn — substituídos por logging.warning + raise

<!-- Registrar gotchas do pipeline compile → match → execute, heurísticas, etc. -->

## Infra / Tooling

<!-- Registrar gotchas de uv, pytest, ruff, mypy, etc. -->
