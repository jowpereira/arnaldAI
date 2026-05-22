"""Especializações de nó: MemoryNode, SynapseNode, CapabilityNode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from .nodes import GraphNode, NodeKind
from .provenance import SourceRecord


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

    @classmethod
    def fact(cls, label: str, *, source: SourceRecord, **fields: Any) -> MemoryNode:
        """Fato verificável e estável."""
        payload = fields.pop("payload", {})
        payload.setdefault("memory_type", "fact")
        return cls.new(
            label=label,
            payload=payload,
            source=source,
            domain=fields.pop("domain", "factual"),
            **fields,
        )

    @classmethod
    def lesson(cls, label: str, *, source: SourceRecord, pattern: str = "", **fields: Any) -> MemoryNode:
        """Lição aprendida de erro ou sucesso."""
        payload = fields.pop("payload", {})
        payload.setdefault("memory_type", "lesson")
        if pattern:
            payload["pattern"] = pattern
        return cls.new(
            label=label,
            payload=payload,
            source=source,
            domain=fields.pop("domain", "procedural"),
            **fields,
        )

    @classmethod
    def execution(cls, label: str, *, source: SourceRecord, run_id: str = "", **fields: Any) -> MemoryNode:
        """Log de execução/resultado de run."""
        payload = fields.pop("payload", {})
        payload.setdefault("memory_type", "execution")
        if run_id:
            payload["run_id"] = run_id
        return cls.new(
            label=label,
            payload=payload,
            source=source,
            domain=fields.pop("domain", "operational"),
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
        activation_pattern: dict[str, Any] | None = None,
        inhibition_targets: list[str] | None = None,
        specialization_depth: int = 0,
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
        if activation_pattern is not None:
            payload["activation_pattern"] = dict(activation_pattern)
        if inhibition_targets is not None:
            payload["inhibition_targets"] = list(inhibition_targets)
        if specialization_depth > 0:
            payload["specialization_depth"] = specialization_depth
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
            key: fields.pop(key) for key in list(fields.keys()) if key not in graph_node_field_names
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
        requires_network: bool = False,
        **fields: Any,
    ) -> CapabilityNode:
        if maturity not in cls.MATURITY_LEVELS:
            raise ValueError(f"maturity inválido: {maturity}. Use: {cls.MATURITY_LEVELS}")
        payload = fields.pop("payload", {})
        payload.update(
            capability_id=capability_id,
            description=description,
            module_path=module_path,
            maturity=maturity,
            risk_level=risk_level,
            requires_network=requires_network,
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

    @property
    def requires_network(self) -> bool:
        """Whether this capability requires network access."""
        return bool(self.payload.get("requires_network", False))

    def promote(self) -> CapabilityNode:
        """Avança um nível de maturidade. Idempotente em ``trusted``."""
        current_idx = self.MATURITY_LEVELS.index(self.maturity)
        if self.maturity == "trusted":
            return self
        if self.maturity == "deprecated":
            raise ValueError("Capability deprecated não pode ser promovida")
        new_maturity = self.MATURITY_LEVELS[current_idx + 1]
        return self.with_payload_merge(maturity=new_maturity)
