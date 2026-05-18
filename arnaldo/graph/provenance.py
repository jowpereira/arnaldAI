"""Proveniência epistêmica para nós e arestas do grafo cognitivo.

**Invariante S1 do grafo (rastreabilidade):** todo nó e toda aresta carregam um
:class:`SourceRecord` declarando *como* aquela informação chegou ao sistema.

Sem proveniência:

* não há como retroceder a cadeia causal de uma decisão (viola auditoria);
* não há como reavaliar conhecimento quando a fonte é desacreditada;
* não há como aplicar decaimento adaptativo (que depende do tipo de fonte).

Cinco classes de fonte foram identificadas suficientes para cobrir os casos do
sistema. A taxonomia segue convenção de epistemologia computacional (cf.
Loizou & Marriot, 2017; Schreiber et al., 2024):

* **Direct observation**  — leitura do mundo (ex.: resposta do usuário, status
  HTTP de uma chamada de tool).
* **Inference**           — derivada por raciocínio do sistema sobre outros
  fatos.
* **External authority**  — buscada em fonte externa autoritativa (paper, blog,
  doc oficial).
* **System artifact**     — gerada pelo próprio Arnaldo (artefato de uma run,
  resumo, embedding).
* **Bootstrap**           — codificada em design (capabilities default,
  ontologia inicial).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .temporal import utc_now


class SourceKind(str, Enum):
    """Taxonomia de origem epistêmica."""

    DIRECT_OBSERVATION = "direct_observation"
    INFERENCE = "inference"
    EXTERNAL_AUTHORITY = "external_authority"
    SYSTEM_ARTIFACT = "system_artifact"
    BOOTSTRAP = "bootstrap"

    @property
    def baseline_confidence(self) -> float:
        """Confiança inicial sugerida por tipo de fonte (∈ [0,1]).

        Pode ser substituída no construtor de ``SourceRecord`` quando há sinal
        adicional (ex.: paper revisado por pares vs. blog post anônimo, ambos
        ``EXTERNAL_AUTHORITY``).
        """
        return {
            SourceKind.DIRECT_OBSERVATION: 0.95,
            SourceKind.INFERENCE: 0.65,
            SourceKind.EXTERNAL_AUTHORITY: 0.80,
            SourceKind.SYSTEM_ARTIFACT: 0.75,
            SourceKind.BOOTSTRAP: 0.99,
        }[self]


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Registro completo de origem de um nó ou aresta.

    Atributos:
        kind:        Classe taxonômica da fonte.
        identifier:  ID estável (URL, run_id, agent_id, "system").
        captured_at: Quando o sistema observou esta fonte (T′).
        confidence:  Confiança subjetiva no fato derivado dessa fonte ∈ [0,1].
        author:      Autor/agente responsável, quando identificável.
        version:     Versão da fonte (ex.: revisão do paper, commit do repo).
        metadata:    Campos auxiliares específicos do tipo (rate-limit, etc).

    Exemplos::

        # 1) Resposta direta do usuário
        SourceRecord(
            kind=SourceKind.DIRECT_OBSERVATION,
            identifier="cli:session_3fa67d",
            author="user",
        )

        # 2) Fato extraído de paper acadêmico
        SourceRecord(
            kind=SourceKind.EXTERNAL_AUTHORITY,
            identifier="arxiv:2601.03236",
            author="Jiang et al.",
            version="v3",
            confidence=0.92,
        )

        # 3) Inferência produzida pelo CognitiveControlPlane
        SourceRecord(
            kind=SourceKind.INFERENCE,
            identifier="run_e8a932f32298",
            author="agent:cognitive_control",
            confidence=0.55,
            metadata={"derived_from": ["intent_3f", "task_42"]},
        )
    """

    kind: SourceKind
    identifier: str
    captured_at: datetime = field(default_factory=utc_now)
    confidence: float = field(default=-1.0)  # sentinel — substituído no post_init
    author: str | None = None
    version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # frozen dataclass — usar object.__setattr__ para sentinel default
        if self.confidence < 0:
            object.__setattr__(self, "confidence", self.kind.baseline_confidence)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence deve ∈ [0,1], recebido {self.confidence}"
            )
        if not self.identifier:
            raise ValueError("identifier não pode ser vazio")

    @classmethod
    def from_user(cls, session_id: str, confidence: float = 0.95) -> SourceRecord:
        """Helper — fato vindo diretamente do usuário em uma sessão."""
        return cls(
            kind=SourceKind.DIRECT_OBSERVATION,
            identifier=f"cli:{session_id}",
            author="user",
            confidence=confidence,
        )

    @classmethod
    def from_run(cls, run_id: str, agent: str = "kernel") -> SourceRecord:
        """Helper — artefato produzido por uma run do kernel."""
        return cls(
            kind=SourceKind.SYSTEM_ARTIFACT,
            identifier=f"run:{run_id}",
            author=f"agent:{agent}",
        )

    @classmethod
    def from_bootstrap(cls, where: str = "design") -> SourceRecord:
        """Helper — fato codificado no design (default capabilities, etc)."""
        return cls(
            kind=SourceKind.BOOTSTRAP,
            identifier=f"bootstrap:{where}",
            author="system",
        )

    def degrade(self, factor: float) -> SourceRecord:
        """Retorna nova SourceRecord com confiança multiplicada por ``factor``.

        Usado quando o fato é detectado como contraditado por evidência mais
        recente (a fonte não foi invalidada, apenas perdeu peso).
        """
        if not 0.0 <= factor <= 1.0:
            raise ValueError(f"factor deve ∈ [0,1], recebido {factor}")
        return SourceRecord(
            kind=self.kind,
            identifier=self.identifier,
            captured_at=self.captured_at,
            confidence=self.confidence * factor,
            author=self.author,
            version=self.version,
            metadata=dict(self.metadata),
        )
