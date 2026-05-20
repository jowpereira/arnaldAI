"""Cognitive Graph — substrate simbólico unificado para Arnaldo.

Estrutura de grafo tipado, temporal, com plasticidade Hebbian, onde co-existem:

* **MemoryNode**     — fato, episódio, conceito (o "que se sabe").
* **SynapseNode**    — agente persistente especializado (o "que sabe fazer").
* **CapabilityNode** — ferramenta executável forjada (o "como executar").

Cada nó pode possuir/referenciar outros grafos via :class:`GraphRef`,
formando uma hierarquia composicional. Modos suportados: ``OWNED`` (dono
exclusivo), ``SHARED`` (compartilhado), ``FEDERATED`` (resolução read-only por
URI) e ``SNAPSHOT`` (cópia imutável).

As arestas são tipadas e ponderadas, sujeitas a plasticidade Hebbian em
tipos sinápticos. Tudo descrito formalmente em ``docs/architecture.md``.

Convenção de import público::

    from arnaldo.graph import CognitiveGraph, NodeKind, EdgeKind
    from arnaldo.graph import MemoryNode, SynapseNode, CapabilityNode
    from arnaldo.graph import SourceRecord, ValidityWindow
    from arnaldo.graph import GraphRef, GraphRefKind, GraphRegistry
"""
from __future__ import annotations

from .edges import EdgeKind, GraphEdge
from .execution import ExecutionEngine, StepContext, SynapseExecutionResult
from .matching import HybridMatcher, MatchResult
from .nodes import (
    CapabilityNode,
    GraphNode,
    MemoryNode,
    NodeKind,
    NodeStatus,
    SynapseNode,
)
from .plasticity import DecayPolicy, HebbianRule, PlasticityEngine
from .provenance import SourceKind, SourceRecord
from .refs import GraphCycleError, GraphRef, GraphRefKind, GraphRegistry
from .store import CognitiveGraph
from .temporal import BiTemporal, ValidityWindow, utc_now
from .workflows import WorkflowStepSpec, compose_workflows, make_workflow

__all__ = [
    # Store principal
    "CognitiveGraph",
    # Tipos de nó
    "GraphNode",
    "MemoryNode",
    "SynapseNode",
    "CapabilityNode",
    # Arestas
    "GraphEdge",
    "ExecutionEngine",
    "StepContext",
    "SynapseExecutionResult",
    # Hierarquia de grafos
    "GraphRef",
    "GraphRefKind",
    "GraphRegistry",
    "GraphCycleError",
    "WorkflowStepSpec",
    "make_workflow",
    "compose_workflows",
    # Enums
    "NodeKind",
    "NodeStatus",
    "EdgeKind",
    "SourceKind",
    # Sub-objetos
    "SourceRecord",
    "ValidityWindow",
    "BiTemporal",
    "MatchResult",
    # Comportamento
    "HybridMatcher",
    "PlasticityEngine",
    "HebbianRule",
    "DecayPolicy",
    # Utilidades
    "utc_now",
]
