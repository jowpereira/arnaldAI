---
applyTo: "**"
description: "Diretrizes técnicas gerais do ArnaldAI — stack, workflow, documentação e referências"
---

# ArnaldAI — Diretrizes Técnicas

## Missão & Princípios

- **Substrate cognitivo simbólico:** Grafo único, vivo e auditável onde memórias, agentes e ferramentas co-existem como nós persistentes
- **Plasticidade Hebbian:** Arestas tipadas com pesos adaptativos que evoluem com uso
- **Auditabilidade total:** Proveniência epistêmica obrigatória — sem origem, sem inserção
- **Estrutura antes de LLM:** LLM eleva qualidade, mas a estrutura nunca depende dele

## Modo de Operar

1. **Contextualizar:** Leia `.github/instructions/*.md` e entenda o problema antes de codar
2. **Pesquisar:** Confirme APIs atuais — confiar em memória é coisa de amador
3. **Planejar:** Estruture a solução antes de implementar
4. **Executar:** Gere código completo e funcional
5. **Validar:** Inclua testes ou comandos de verificação — código sem teste é sugestão, não solução

**Evite:** Otimização prematura, tipos `any`, segredos hardcoded e ignorar linting.

## Stack Tecnológico

| Área | Preferência |
|------|-------------|
| **Runtime** | Python 3.12+ (uv como gerenciador) |
| **Grafo cognitivo** | NetworkX (multidigrafo tipado) |
| **Vetorização** | NumPy (embeddings, similaridade) |
| **Serialização** | msgpack (binário, compacto) |
| **LLM** | Azure OpenAI (4 tiers: GOD/EXPERT/FAST/CODEX, stdlib-only) |
| **CLI** | stdlib argparse |
| **QA** | Ruff (lint/format), mypy (types), pytest (testes) |
| **Embeddings** | sentence-transformers (opcional, Fase 2+) |
| **Graph backends** | neo4j, falkordb (opcional, Fase 4+) |

**Mantenha dependências mínimas e estritas** — a camada LLM é stdlib-only (urllib + json). Sem SDKs desnecessários.

## Diretivas de Documentação

- Documentação, comentários e mensagens de commit devem ser em **Português**
- Docstrings e variáveis em **inglês**
- Utilize **estritamente** o **Semantic Versioning** ([semver.org](https://semver.org) — formato: MAJOR.MINOR.PATCH) no `CHANGELOG`

## Os Sete Invariantes (nunca violar)

```
I1. Tipagem.       Todo nó tem kind ∈ NodeKind; toda aresta tem kind ∈ EdgeKind.
I2. Proveniência.  Todo nó e toda aresta carregam SourceRecord não-vazio.
I3. Bi-temporal.   Toda relação carrega (T, T′) — quando vigorou e quando o sistema soube.
I4. Plasticidade.  Pesos ∈ [floor, ceiling] ⊂ [0,1]. |Δw| ≤ cap_per_step.
I5. Decay tipado.  Half-life por domain, nunca uniforme.
I6. Auditabilidade. Toda mutação no grafo gera GraphEvent persistível.
I7. DAG hierarquia. GraphRef forma um DAG — ciclos são rejeitados (GraphCycleError).
```

Violar qualquer invariante ⇒ exceção na operação (não falha silenciosa).

## Execução

```bash
# Testes
rtk uv run pytest -x -v

# Linting
rtk uv run ruff check arnaldo/ tests/
rtk uv run ruff format arnaldo/ tests/

# Type checking
rtk uv run mypy arnaldo/

# Run única
rtk uv run python -m arnaldo "Crie um plano para um SaaS B2B"

# Run com autonomia
rtk uv run python -m arnaldo "Analise o mercado" --autonomy autonomo
```

# RTK — Token-Optimized CLI

**rtk** is a CLI proxy that filters and compresses command outputs, saving 60-90% tokens.

## Rule

Always prefix shell commands with `rtk`:

```bash
# Instead of:              Use:
git status                 rtk git status
git log -10                rtk git log -10
cargo test                 rtk cargo test
docker ps                  rtk docker ps
kubectl get pods           rtk kubectl pods
```

## Meta commands (use directly)

```bash
rtk gain              # Token savings dashboard
rtk gain --history    # Per-command savings history
rtk discover          # Find missed rtk opportunities
rtk proxy <cmd>       # Run raw (no filtering) but track usage
```

