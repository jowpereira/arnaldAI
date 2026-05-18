"""Arestas tipadas do grafo cognitivo.

**Princípio:** o significado de uma conexão é função do *tipo* da aresta, não
de uma label livre. Tipos discretos permitem:

* traversal direcionado por intenção da query (cf. Jiang et al., 2026 — MAGMA);
* aplicação seletiva de regras de plasticidade por tipo;
* auditoria estatística (quantas arestas CAUSAL existem? quantas DERIVED_FROM?).

Categorias de aresta::

    ┌─────────────────────┬───────────────────────────────────────────────┐
    │  Categoria          │  Função                                       │
    ├─────────────────────┼───────────────────────────────────────────────┤
    │  Semântica          │  SEMANTIC                                     │
    │  Temporal           │  TEMPORAL_BEFORE                              │
    │  Causal             │  CAUSAL, DERIVED_FROM                         │
    │  Entidade           │  MENTIONS, IS_A, PART_OF                      │
    │  Sináptica          │  ACTIVATES, COLLABORATED_WITH, INHIBITS       │
    │  Instrumental       │  REQUIRES, FORBIDS, FORGED_BY                 │
    └─────────────────────┴───────────────────────────────────────────────┘

Multi-grafo: o ``CognitiveGraph`` permite múltiplas arestas (de tipos
diferentes) entre o mesmo par de nós. Não há upper bound formal — é equivalente
a um hypergraph onde cada aresta-tipo define uma sub-relação.

Formalmente, ``CognitiveGraph`` é uma tripla ``G = ⟨V, E, τ⟩`` onde::

    V    : conjunto de nós tipados
    E    : conjunto de arestas
    τ    : E → EdgeKind  (função de tipagem)

E o grafo total é a união disjunta dos sub-grafos por tipo::

    G    = ⋃_{k ∈ EdgeKind} G_k, com G_k = ⟨V, {e ∈ E | τ(e) = k}⟩
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any
import uuid

import numpy as np

from .provenance import SourceRecord
from .temporal import BiTemporal, utc_now


class EdgeKind(str, Enum):
    """Tipos canônicos de aresta. Estritamente fechado — extensões precisam
    de mudança de spec (cf. ``docs/grafo.md``)."""

    # ── Categoria: Semântica ─────────────────────────────────────────────
    SEMANTIC = "semantic"
    """Similaridade de conteúdo. Não-direcional (mas armazenado como par)."""

    # ── Categoria: Temporal ──────────────────────────────────────────────
    TEMPORAL_BEFORE = "temporal_before"
    """A precede B no event-time. Estritamente direcional, antissimétrica."""

    # ── Categoria: Causal ────────────────────────────────────────────────
    CAUSAL = "causal"
    """A causou B (ou B é consequência de A). Direcional."""

    DERIVED_FROM = "derived_from"
    """B foi derivado de A por inferência do sistema. Cadeia de proveniência."""

    # ── Categoria: Entidade ──────────────────────────────────────────────
    MENTIONS = "mentions"
    """Episódio menciona entidade. Direcional: episode → entity."""

    IS_A = "is_a"
    """A é instância/subclasse de B. Direcional, transitiva."""

    PART_OF = "part_of"
    """A é parte/componente de B. Direcional, transitiva."""

    # ── Categoria: Sináptica (entre SynapseNode) ─────────────────────────
    ACTIVATES = "activates"
    """Padrão de ativação: synapse A frequentemente ativa synapse B.

    Sujeito a plasticidade Hebbian — reforça com co-ativação bem-sucedida."""

    COLLABORATED_WITH = "collaborated_with"
    """A e B foram ativados juntos com sucesso na mesma run."""

    INHIBITS = "inhibits"
    """A inibe B (LTD inverso) — ativar A reduz prob de ativar B."""

    # ── Categoria: Instrumental (envolvendo CapabilityNode) ──────────────
    REQUIRES = "requires"
    """Synapse A requer Capability B para funcionar."""

    FORBIDS = "forbids"
    """Synapse A não pode usar Capability B (policy enforcement)."""

    FORGED_BY = "forged_by"
    """Capability A foi forjada durante run B (proveniência)."""

    # ── Categoria: Composicional (intra-grafo) ───────────────────────────
    INCLUDES = "includes"
    """A inclui hierarquicamente B no mesmo grafo (composição estrutural).

    Diferente de :class:`GraphRef` (que aponta para *outro* grafo), ``INCLUDES``
    é uma relação dentro do mesmo grafo, expressando "A é um agregado que
    contém B como componente". Usado para clusters coesos de nós que devem
    ser tratados como unidade em retrieval.
    """

    # ── Helpers de classificação ─────────────────────────────────────────

    @property
    def is_directed(self) -> bool:
        """SEMANTIC é simétrico; demais são direcionais."""
        return self != EdgeKind.SEMANTIC

    @property
    def is_synaptic(self) -> bool:
        """Aresta cuja força é refinada por plasticidade Hebbian."""
        return self in {
            EdgeKind.ACTIVATES,
            EdgeKind.COLLABORATED_WITH,
            EdgeKind.INHIBITS,
        }

    @property
    def is_provenance(self) -> bool:
        """Aresta usada para reconstruir cadeia causal de origem."""
        return self in {
            EdgeKind.DERIVED_FROM,
            EdgeKind.FORGED_BY,
        }

    @property
    def is_transitive(self) -> bool:
        """Suporta fechamento transitivo (A→B→C implica A→C)."""
        return self in {
            EdgeKind.IS_A,
            EdgeKind.PART_OF,
            EdgeKind.TEMPORAL_BEFORE,
            EdgeKind.INCLUDES,
        }

    @property
    def is_compositional(self) -> bool:
        """Relação de agregação/composição estrutural."""
        return self in {EdgeKind.INCLUDES, EdgeKind.PART_OF}


# ────────────────────────────────────────────────────────────────────────────
# GraphEdge
# ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class GraphEdge:
    """Aresta tipada entre dois nós, com peso e janela temporal.

    Modelo formal::

        e = ⟨ id, source_id, target_id, kind, weight, bitemp, source, payload, stats ⟩

    Onde:
        * ``weight ∈ [0,1]`` — força da conexão (sujeita a plasticidade quando
          ``kind.is_synaptic``).
        * ``bitemp`` — quando a relação é válida (event time) e quando o
          sistema soube dela (transaction time).
        * ``stats`` — contadores de uso (analogamente a ``NodeStats``).

    Operações imutáveis em ``with_*`` retornam novas instâncias; operações
    mutáveis em ``activate``/``register_outcome`` modificam ``stats`` in-place
    (consistente com a semântica do nó).
    """

    id: str
    source_id: str
    target_id: str
    kind: EdgeKind
    weight: float = 0.5
    bitemp: BiTemporal = field(default_factory=BiTemporal.now)
    source: SourceRecord = field(
        default_factory=lambda: SourceRecord.from_bootstrap("graph/edge")
    )
    payload: dict[str, Any] = field(default_factory=dict)

    # Contadores (subset menor que NodeStats — arestas são mais simples)
    activations: int = 0
    successes: int = 0
    failures: int = 0
    last_activated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight deve ∈ [0,1], recebido {self.weight}")
        if self.source_id == self.target_id and self.kind != EdgeKind.SEMANTIC:
            # Self-loops permitidos apenas em SEMANTIC (auto-similaridade)
            raise ValueError(
                f"Self-loop em aresta {self.kind} (source={self.source_id})"
            )

    # ── Construtor canônico ──────────────────────────────────────────────

    @classmethod
    def connect(
        cls,
        source_id: str,
        target_id: str,
        kind: EdgeKind,
        *,
        weight: float | None = None,
        source: SourceRecord | None = None,
        **fields: Any,
    ) -> GraphEdge:
        """Factory canônico — gera id, aplica peso default por tipo."""
        edge_weight = weight if weight is not None else _default_weight_for(kind)
        edge_source = source or SourceRecord.from_bootstrap(f"edge/{kind.value}")
        return cls(
            id=f"edg_{uuid.uuid4().hex[:12]}",
            source_id=source_id,
            target_id=target_id,
            kind=kind,
            weight=edge_weight,
            source=edge_source,
            **fields,
        )

    # ── Operações imutáveis ──────────────────────────────────────────────

    def with_weight(self, new_weight: float) -> GraphEdge:
        clipped = float(np.clip(new_weight, 0.0, 1.0))
        return replace(self, weight=clipped)

    def invalidate(self, at: datetime | None = None) -> GraphEdge:
        """Marca a aresta como invalidada no transaction time."""
        return replace(self, bitemp=self.bitemp.invalidate(at))

    # ── Operações mutáveis ───────────────────────────────────────────────

    def activate(self, at: datetime | None = None) -> None:
        self.activations += 1
        self.last_activated_at = at or utc_now()

    def register_outcome(self, success: bool) -> None:
        if success:
            self.successes += 1
        else:
            self.failures += 1

    # ── Propriedades ─────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self.bitemp.is_active

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        if total == 0:
            return 0.5
        return (self.successes + 1) / (total + 2)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<GraphEdge {self.kind.value} {self.source_id}→{self.target_id} "
            f"w={self.weight:.2f}>"
        )


def _default_weight_for(kind: EdgeKind) -> float:
    """Peso inicial sugerido por tipo. Conservador por padrão."""
    return {
        EdgeKind.SEMANTIC: 0.50,
        EdgeKind.TEMPORAL_BEFORE: 1.00,  # fato temporal — força máxima
        EdgeKind.CAUSAL: 0.70,
        EdgeKind.DERIVED_FROM: 0.85,
        EdgeKind.MENTIONS: 0.60,
        EdgeKind.IS_A: 0.95,
        EdgeKind.PART_OF: 0.90,
        EdgeKind.ACTIVATES: 0.30,  # baixa — precisa de evidência para crescer
        EdgeKind.COLLABORATED_WITH: 0.40,
        EdgeKind.INHIBITS: 0.30,
        EdgeKind.REQUIRES: 0.95,
        EdgeKind.FORBIDS: 1.00,  # constraint hard
        EdgeKind.FORGED_BY: 1.00,  # proveniência — força máxima
        EdgeKind.INCLUDES: 0.85,  # composição estrutural — alta
    }[kind]
