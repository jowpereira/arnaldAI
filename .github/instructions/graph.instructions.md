---
applyTo: "arnaldo/graph/**/*.py"
description: "Invariantes e padrões do grafo cognitivo — core do ArnaldAI"
---

# Grafo Cognitivo — Padrões Obrigatórios

Este é o **core absoluto** do ArnaldAI. Toda edição em `arnaldo/graph/` deve respeitar os 7 invariantes sem exceção.

## Os Sete Invariantes

Toda mutação DEVE preservar:

1. **I1 Tipagem** — Todo nó tem `kind ∈ NodeKind`; toda aresta tem `kind ∈ EdgeKind`. Nunca criar nó/aresta sem tipo.
2. **I2 Proveniência** — Todo nó e toda aresta carregam `SourceRecord` não-vazio. Sem origem → rejeitar inserção.
3. **I3 Bi-temporal** — Toda relação carrega `(T, T′)` — quando vigorou e quando o sistema soube. Nunca omitir timestamps.
4. **I4 Plasticidade** — Pesos `∈ [floor, ceiling] ⊂ [0,1]`. `|Δw| ≤ cap_per_step`. Nunca ultrapassar bounds.
5. **I5 Decay tipado** — `half_life` é por domain, nunca uniforme. Usar o domínio correto do `MemoryNode`.
6. **I6 Auditabilidade** — Toda mutação no grafo gera `GraphEvent` persistível. Sem evento silencioso.
7. **I7 DAG hierarquia** — `GraphRef` forma DAG. Ciclos são rejeitados com `GraphCycleError`.

## Tipos de Nó

```python
# Sempre usar o enum NodeKind — nunca strings literais
from arnaldo.graph.nodes import NodeKind

# Tipos principais:
# NodeKind.MEMORY     — MemoryNode (declarative, episodic, procedural, negative)
# NodeKind.SYNAPSE    — SynapseNode (habilidades que fortalecem/enfraquecem)
# NodeKind.CAPABILITY — CapabilityNode (ferramentas: scaffolded → tested → trusted → deprecated)
```

## Tipos de Aresta

```python
from arnaldo.graph.edges import EdgeKind

# 14 tipos — usar sempre o enum, nunca string
# EdgeKind.ACTIVATES, INHIBITS, MODULATES, REQUIRES, etc.
```

## SourceRecord

```python
from arnaldo.graph.provenance import SourceRecord, SourceKind

# NUNCA criar nó sem SourceRecord
# Confidence mínima por tipo:
# BOOTSTRAP        → 0.99
# DIRECT_OBSERVATION → 0.90
# SYSTEM_ARTIFACT  → 0.75
# EXTERNAL_AUTHORITY → 0.70
# INFERENCE        → 0.65
```

## Plasticidade

```python
# HebbianRule — fórmula: Δw = η · (success_rate − ½) · 2
# SEMPRE respeitar:
# - cap_per_step (máximo |Δw| por atualização)
# - floor / ceiling (bounds absolutos do peso)
# - Laplace smoothing: (s+1)/(s+f+2) para evitar overconfidence

# NUNCA: atribuir peso diretamente sem HebbianRule
# NUNCA: ignorar bounds — catastrophic plasticity é bug, não feature
```

## sweep_decay

```python
# Decay é POR DOMÍNIO — half_life varia:
# tech_news:  3 dias
# episodic:   7 dias
# negative:   30 dias
# procedural: 365 dias

# NUNCA aplicar decay uniforme
# NUNCA decrementar abaixo de forget_threshold sem ARCHIVED
```

## Padrões de Teste

- Todo novo tipo de nó/aresta → teste que verifica tipagem (I1)
- Toda inserção → teste que verifica SourceRecord (I2)
- Toda mutação → teste que verifica GraphEvent gerado (I6)
- Todo GraphRef → teste que verifica rejeição de ciclo (I7)
- Toda atualização de peso → teste que verifica bounds (I4)

## Erros Comuns

- Criar `MemoryNode` sem `memory_type` → viola I1
- Inserir aresta sem `SourceRecord` → viola I2
- Atualizar peso sem checar `cap_per_step` → viola I4
- Aplicar `half_life` errado para o domain → viola I5
- Mutar grafo sem emitir `GraphEvent` → viola I6
- Criar referência circular entre subgrafos → viola I7, gera `GraphCycleError`
