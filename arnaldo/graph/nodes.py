"""Nós do grafo cognitivo — GraphNode (abstrato) + 3 especializações.

Topologia tipada::

           GraphNode (abstrato)
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   MemoryNode  SynapseNode  CapabilityNode
   (o quê)     (quem sabe)  (como executar)

Princípio de design: **um único objeto base**, com campos genéricos suficientes
para suportar plasticidade, decaimento, embedding e proveniência. Especializações
adicionam apenas semântica de domínio. Isso permite que o ``CognitiveGraph``
trate qualquer nó uniformemente em operações de matching/retrieval/decay.

Notação formal::

    n = ⟨ id, kind, payload, weight, embedding,
          bitemp, source, stats, tags ⟩

Onde ``stats`` carrega contadores de acesso/uso (para plasticidade Hebbian) e
``tags`` permite indexação flexível por domínio sem reformular schema.

Especializações concretas em ``node_types.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Self
import uuid

import numpy as np
from numpy.typing import NDArray

from .provenance import SourceKind, SourceRecord
from .refs import GraphRef
from .temporal import BiTemporal, utc_now


# ────────────────────────────────────────────────────────────────────────────
# Enums
# ────────────────────────────────────────────────────────────────────────────


class NodeKind(str, Enum):
    """Classes ortogonais de nó no grafo cognitivo.

    A escolha de 3 classes é deliberada — corresponde à tripartição cognitiva
    de Tulving (1972): memória declarativa, procedural, e ferramental. Mais
    classes seriam redundantes; menos perderiam discriminação útil.
    """

    # fmt: off
    MEMORY = "memory"          # Fatos, episódios, conceitos (declarativo)
    SYNAPSE = "synapse"        # Agentes especializados persistentes (procedural)
    CAPABILITY = "capability"  # Ferramentas executáveis (instrumental)
    # fmt: on


class NodeStatus(str, Enum):
    """Estado no ciclo de vida.

    Transições válidas::

        CANDIDATE ──validate──► ACTIVE ──consolidate──► CONSOLIDATED
            │                     │                          │
            │                     │                          │
            └─────────────────────┴──┐  ┌──────────────────┐
                                     ▼  ▼                  │
                                  STALE ──refresh──► ACTIVE│
                                     │                     │
                                     └──forget──► ARCHIVED ┘
    """

    # fmt: off
    CANDIDATE = "candidate"          # recém-criado, ainda não validado
    ACTIVE = "active"                # em uso normal
    CONSOLIDATED = "consolidated"    # uso frequente confirmado (peso alto)
    STALE = "stale"                  # decaído, precisa re-foragem
    ARCHIVED = "archived"            # esquecido (cold storage, fora de retrieval)
    # fmt: on


# ────────────────────────────────────────────────────────────────────────────
# Estatísticas de uso (suporte a plasticidade)
# ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class NodeStats:
    """Contadores de acesso/uso, usados pelo motor de plasticidade.

    Hebbian-like: nós ativados com sucesso ganham peso; ativados com falha
    perdem peso; não-ativados decaem por tempo.

    Atributos:
        activations:        Quantas vezes o nó foi ativado por queries.
        successes:          Ativações que levaram a outcome positivo.
        failures:           Ativações que levaram a outcome negativo.
        last_activated_at:  Última ativação (event time).
        last_refreshed_at:  Última verificação ativa (T′) da validade.
    """

    activations: int = 0
    successes: int = 0
    failures: int = 0
    last_activated_at: datetime | None = None
    last_refreshed_at: datetime | None = None

    @property
    def success_rate(self) -> float:
        """Razão de sucesso (Laplace smoothing para evitar 0/0)."""
        from .plasticity import laplace_success_rate

        return laplace_success_rate(self.successes, self.failures)

    def register_activation(self, at: datetime | None = None) -> None:
        """Incrementa contador de ativação e atualiza timestamp."""
        self.activations += 1
        self.last_activated_at = at or utc_now()

    def register_outcome(self, success: bool) -> None:
        """Registra resultado da ativação para fins de Hebbian update."""
        if success:
            self.successes += 1
        else:
            self.failures += 1


# ────────────────────────────────────────────────────────────────────────────
# Base abstrata
# ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class GraphNode:
    """Nó base do grafo cognitivo — abstrato (use subclasses).

    Composição:

    * **Identidade**       — ``id``, ``kind``, ``label``
    * **Conteúdo**         — ``payload`` (dict livre, schema controlado por subclasse)
    * **Representação**    — ``embedding`` (∈ ℝᵈ, opcional)
    * **Peso sináptico**   — ``weight`` ∈ [0,1] (sujeito a plasticidade)
    * **Vigência**         — ``bitemp`` (janelas de validade + transação)
    * **Origem**           — ``source`` (proveniência epistêmica)
    * **Estado**           — ``status`` (ciclo de vida)
    * **Estatísticas**     — ``stats`` (contadores para Hebbian)
    * **Indexação livre**  — ``tags`` (set de strings para filtro rápido)
    * **Domínio**          — ``domain`` (rótulo para half-life adaptativa)

    Subclasses não devem sobrescrever campos — apenas adicionar semântica em
    ``payload`` via factory methods (princípio de open-closed).
    """

    # Identidade
    id: str
    kind: NodeKind
    label: str

    # Conteúdo + representação
    payload: dict[str, Any] = field(default_factory=dict)
    embedding: NDArray[np.float32] | None = None

    # Dinâmica
    weight: float = 0.5
    status: NodeStatus = NodeStatus.CANDIDATE

    # Temporal & epistemológico
    bitemp: BiTemporal = field(default_factory=BiTemporal.now)
    source: SourceRecord = field(default_factory=lambda: SourceRecord.from_bootstrap("graph/init"))

    # Plasticidade
    stats: NodeStats = field(default_factory=NodeStats)

    # Indexação
    tags: set[str] = field(default_factory=set)
    domain: str = "generic"

    # Composicional: sub-grafos referenciados
    subgraph_refs: list[GraphRef] = field(default_factory=list)

    # Default kind para subclasses
    DEFAULT_KIND: ClassVar[NodeKind | None] = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight deve ∈ [0,1], recebido {self.weight}")
        if not self.label:
            raise ValueError("label não pode ser vazio")

    # ── Construtores ──────────────────────────────────────────────────────

    @classmethod
    def new(cls, label: str, *, source: SourceRecord | None = None, **fields: Any) -> Self:
        """Factory canônico — gera id, aplica DEFAULT_KIND e validação.

        Use sempre este método em produção em vez do construtor direto. Garante:

        * id único e prefixado pelo tipo
        * kind correto (cada subclasse define DEFAULT_KIND)
        * source não-vazia (default bootstrap)
        """
        if cls.DEFAULT_KIND is None and "kind" not in fields:
            raise TypeError(f"{cls.__name__} sem DEFAULT_KIND deve passar kind=... explicitamente")
        kind = fields.pop("kind", cls.DEFAULT_KIND)
        assert kind is not None
        node_id = fields.pop("id", _make_id(kind))
        node_source = source or SourceRecord.from_bootstrap(f"{cls.__name__}.new")
        return cls(id=node_id, kind=kind, label=label, source=node_source, **fields)

    # ── Operações imutáveis ───────────────────────────────────────────────

    def with_weight(self, new_weight: float) -> GraphNode:
        """Retorna cópia com peso atualizado (clipado em [0,1])."""
        clipped = float(np.clip(new_weight, 0.0, 1.0))
        return replace(self, weight=clipped)

    def with_status(self, new_status: NodeStatus) -> GraphNode:
        return replace(self, status=new_status)

    def with_payload_merge(self, **updates: Any) -> GraphNode:
        merged = dict(self.payload)
        merged.update(updates)
        return replace(self, payload=merged)

    # ── Operações mutáveis (estatísticas/tags) ────────────────────────────

    def activate(self, at: datetime | None = None) -> None:
        """Registra ativação (incrementa contador, atualiza timestamp).

        **Não** ajusta peso — isso é responsabilidade do ``PlasticityEngine``.
        """
        self.stats.register_activation(at)

    def record_outcome(self, success: bool) -> None:
        """Registra resultado da última ativação (sucesso ou falha)."""
        self.stats.register_outcome(success)

    def add_tags(self, *tags: str) -> None:
        self.tags.update(tags)

    # ── Sub-graph references ─────────────────────────────────────────────

    def attach_ref(self, ref: GraphRef) -> None:
        """Anexa uma referência de sub-grafo a este nó.

        Não cria/registra o sub-grafo — apenas associa a ``GraphRef``.
        A criação e registro são responsabilidade do ``CognitiveGraph``
        ``attach_subgraph()``.
        """
        # Evita duplicatas exatas (mesmo graph_id + mesmo kind)
        for existing in self.subgraph_refs:
            if existing.graph_id == ref.graph_id and existing.kind == ref.kind:
                return
        self.subgraph_refs.append(ref)

    def detach_ref(self, graph_id: str) -> GraphRef | None:
        """Remove referência ao sub-grafo ``graph_id``, retorna o ref removido."""
        for i, ref in enumerate(self.subgraph_refs):
            if ref.graph_id == graph_id:
                return self.subgraph_refs.pop(i)
        return None

    def find_ref(self, graph_id: str) -> GraphRef | None:
        for ref in self.subgraph_refs:
            if ref.graph_id == graph_id:
                return ref
        return None

    @property
    def has_subgraphs(self) -> bool:
        return len(self.subgraph_refs) > 0

    # ── Conveniências ────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """Nó está vigente (bitemp + status)."""
        return self.bitemp.is_active and self.status not in {NodeStatus.ARCHIVED}

    @property
    def age_seconds(self) -> float:
        return self.bitemp.age_seconds()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        emb = "yes" if self.embedding is not None else "no"
        return (
            f"<{self.__class__.__name__} {self.id} "
            f"label='{self.label[:30]}' w={self.weight:.2f} "
            f"status={self.status.value} emb={emb}>"
        )


def _make_id(kind: NodeKind) -> str:
    """Gera id estável e prefixado por tipo (ex.: ``syn_8c2af1...``)."""
    prefix = {
        NodeKind.MEMORY: "mem",
        NodeKind.SYNAPSE: "syn",
        NodeKind.CAPABILITY: "cap",
    }[kind]
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# Re-export para compatibilidade
from .node_types import CapabilityNode, MemoryNode, SynapseNode  # noqa: F401
