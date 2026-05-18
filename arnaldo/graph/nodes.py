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

    MEMORY = "memory"          # Fatos, episódios, conceitos (declarativo)
    SYNAPSE = "synapse"        # Agentes especializados persistentes (procedural)
    CAPABILITY = "capability"  # Ferramentas executáveis (instrumental)


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

    CANDIDATE = "candidate"          # recém-criado, ainda não validado
    ACTIVE = "active"                # em uso normal
    CONSOLIDATED = "consolidated"    # uso frequente confirmado (peso alto)
    STALE = "stale"                  # decaído, precisa re-foragem
    ARCHIVED = "archived"            # esquecido (cold storage, fora de retrieval)


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
        total = self.successes + self.failures
        if total == 0:
            return 0.5  # prior neutro
        return (self.successes + 1) / (total + 2)

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
    source: SourceRecord = field(
        default_factory=lambda: SourceRecord.from_bootstrap("graph/init")
    )

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
        * source não-vazia (fallback bootstrap)
        """
        if cls.DEFAULT_KIND is None and "kind" not in fields:
            raise TypeError(
                f"{cls.__name__} sem DEFAULT_KIND deve passar kind=... explicitamente"
            )
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


# ────────────────────────────────────────────────────────────────────────────
# Especializações
# ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class MemoryNode(GraphNode):
    """Memória declarativa — fato, episódio ou conceito.

    Sub-classes semânticas em ``payload["memory_type"]``:

    * **episodic**   — interação com timestamp ("o que aconteceu na sessão X")
    * **semantic**   — fato estável ("X é Y")
    * **procedural** — padrão de uso ("para X normalmente fazemos Y")
    * **negative**   — anti-padrão ("não tentar X com input Y")
    * **prospective**— intenção futura ("aprender X no próximo turno")

    A escolha do subtipo afeta a half-life em ``DecayPolicy`` (cf. ``plasticity.py``).
    """

    DEFAULT_KIND: ClassVar[NodeKind] = NodeKind.MEMORY

    @classmethod
    def episodic(cls, label: str, *, run_id: str, **fields: Any) -> MemoryNode:
        payload = fields.pop("payload", {})
        payload["memory_type"] = "episodic"
        payload["run_id"] = run_id
        return cls.new(
            label=label,
            payload=payload,
            source=SourceRecord.from_run(run_id),
            domain=fields.pop("domain", "episodic"),
            **fields,
        )

    @classmethod
    def semantic(cls, label: str, *, source: SourceRecord, **fields: Any) -> MemoryNode:
        payload = fields.pop("payload", {})
        payload["memory_type"] = "semantic"
        return cls.new(
            label=label,
            payload=payload,
            source=source,
            domain=fields.pop("domain", "semantic_stable"),
            **fields,
        )

    @classmethod
    def procedural(cls, label: str, *, pattern: str, **fields: Any) -> MemoryNode:
        payload = fields.pop("payload", {})
        payload["memory_type"] = "procedural"
        payload["pattern"] = pattern
        return cls.new(
            label=label,
            payload=payload,
            domain=fields.pop("domain", "procedural"),
            **fields,
        )


@dataclass(slots=True)
class SynapseNode(GraphNode):
    """Agente especializado persistente — "função aprendida" reutilizável.

    Diferente de ``AgentGenome`` (do design v1 que era efêmero), um
    ``SynapseNode`` **persiste no grafo** após sua primeira utilização. Cada
    ativação refina seu peso via Hebbian update.

    Campos semânticos esperados em ``payload``:

    * ``role``                   — papel cognitivo (ex.: "framer", "critic")
    * ``epistemic_style``        — estratégia ("evidence_first", "exploratory")
    * ``required_capabilities``  — IDs de ``CapabilityNode`` necessários
    * ``forbidden_capabilities`` — IDs explicitamente bloqueados
    * ``prompt_template``        — template para o LLM (opcional)
    * ``tier_preference``        — sugestão de tier (god/expert/fast/codex)
    """

    DEFAULT_KIND: ClassVar[NodeKind] = NodeKind.SYNAPSE

    @classmethod
    def specialist(
        cls,
        label: str,
        *,
        role: str,
        objective: str,
        epistemic_style: str = "evidence_first",
        required_capabilities: list[str] | None = None,
        forbidden_capabilities: list[str] | None = None,
        input_contract: dict[str, Any] | None = None,
        output_contract: dict[str, Any] | None = None,
        output_contract_model: type[Any] | None = None,
        activation_triggers: dict[str, Any] | None = None,
        tier_preference: str = "expert",
        **fields: Any,
    ) -> SynapseNode:
        payload = fields.pop("payload", {})
        payload.update(
            role=role,
            objective=objective,
            epistemic_style=epistemic_style,
            required_capabilities=required_capabilities or [],
            forbidden_capabilities=forbidden_capabilities
            or ["send.external_message", "spend.money", "delete.user_data"],
            tier_preference=tier_preference,
        )

        if input_contract is not None:
            payload["input_contract"] = dict(input_contract)
        if output_contract is not None:
            payload["output_contract"] = dict(output_contract)
        if activation_triggers is not None:
            payload["activation_triggers"] = dict(activation_triggers)
        if output_contract_model is not None:
            from arnaldo.llm.structured import dataclass_to_schema

            payload["output_contract_model"] = output_contract_model.__name__
            payload["output_schema"] = dataclass_to_schema(output_contract_model)

        graph_node_field_names = {
            "id",
            "kind",
            "embedding",
            "weight",
            "status",
            "bitemp",
            "source",
            "stats",
            "tags",
            "domain",
            "subgraph_refs",
        }
        payload_extras = {
            key: fields.pop(key)
            for key in list(fields.keys())
            if key not in graph_node_field_names
        }
        payload.update(payload_extras)

        return cls.new(label=label, payload=payload, domain="procedural", **fields)

    @property
    def role(self) -> str:
        return str(self.payload.get("role", "generic"))

    @property
    def required_capabilities(self) -> list[str]:
        return list(self.payload.get("required_capabilities", []))


@dataclass(slots=True)
class CapabilityNode(GraphNode):
    """Ferramenta executável — função pura ou conector externo.

    Distingue-se de ``SynapseNode`` por **não fazer raciocínio**: é puramente
    instrumental (ex.: ``connector.http.generic``, ``search.public_web``).

    O ciclo de maturidade reside aqui: ``draft → tested → trusted → deprecated``,
    rastreado em ``payload["maturity"]``.
    """

    DEFAULT_KIND: ClassVar[NodeKind] = NodeKind.CAPABILITY

    MATURITY_LEVELS: ClassVar[tuple[str, ...]] = (
        "scaffolded",
        "draft",
        "tested",
        "trusted",
        "deprecated",
    )

    @classmethod
    def tool(
        cls,
        capability_id: str,
        *,
        description: str,
        module_path: str | None = None,
        maturity: str = "draft",
        risk_level: str = "medium",
        **fields: Any,
    ) -> CapabilityNode:
        if maturity not in cls.MATURITY_LEVELS:
            raise ValueError(
                f"maturity inválido: {maturity}. Use: {cls.MATURITY_LEVELS}"
            )
        payload = fields.pop("payload", {})
        payload.update(
            capability_id=capability_id,
            description=description,
            module_path=module_path,
            maturity=maturity,
            risk_level=risk_level,
        )
        # Peso inicial cresce com a maturidade
        weight = {
            "scaffolded": 0.10,
            "draft": 0.25,
            "tested": 0.55,
            "trusted": 0.85,
            "deprecated": 0.05,
        }[maturity]
        return cls.new(
            id=fields.pop("id", f"cap_{capability_id.replace('.', '_')}"),
            label=capability_id,
            payload=payload,
            weight=fields.pop("weight", weight),
            domain="capability",
            **fields,
        )

    @property
    def maturity(self) -> str:
        return str(self.payload.get("maturity", "draft"))

    def promote(self) -> CapabilityNode:
        """Avança um nível de maturidade. Idempotente em ``trusted``."""
        current_idx = self.MATURITY_LEVELS.index(self.maturity)
        if self.maturity == "trusted":
            return self
        if self.maturity == "deprecated":
            raise ValueError("Capability deprecated não pode ser promovida")
        new_maturity = self.MATURITY_LEVELS[current_idx + 1]
        return self.with_payload_merge(maturity=new_maturity)
