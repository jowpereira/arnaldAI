"""Bootstrap do grafo cognitivo — sementes iniciais para aprendizado."""

from __future__ import annotations

from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
    GraphEdge,
    SourceKind,
    SourceRecord,
)
from arnaldo.graph.node_types import SynapseNode


_BOOTSTRAP_SOURCE = SourceRecord(
    kind=SourceKind.BOOTSTRAP, identifier="kernel:bootstrap", confidence=0.95
)

# Sinapses fundamentais que formam o "instinto" do Arnaldo
_SEED_SYNAPSES = [
    {
        "id": "syn-responder",
        "label": "Responder perguntas",
        "role": "responder",
        "objective": "Responder perguntas do usuário com precisão e personalidade",
        "tier": "fast",
    },
    {
        "id": "syn-planejar",
        "label": "Planejar tarefas",
        "role": "planner",
        "objective": "Decompor requests complexos em etapas executáveis",
        "tier": "expert",
    },
    {
        "id": "syn-analisar",
        "label": "Analisar informação",
        "role": "analyst",
        "objective": "Analisar dados, código ou texto para extrair insights",
        "tier": "expert",
    },
    {
        "id": "syn-criar",
        "label": "Criar artefatos",
        "role": "creator",
        "objective": "Gerar código, texto, documentação ou outros artefatos",
        "tier": "god",
    },
    {
        "id": "syn-corrigir",
        "label": "Corrigir e debugar",
        "role": "debugger",
        "objective": "Identificar e corrigir erros em código ou processos",
        "tier": "expert",
    },
]

# Arestas que conectam synapses por afinidade funcional
_SEED_EDGES = [
    ("syn-planejar", "syn-criar", EdgeKind.ACTIVATES, 0.7),
    ("syn-planejar", "syn-analisar", EdgeKind.ACTIVATES, 0.6),
    ("syn-analisar", "syn-criar", EdgeKind.ACTIVATES, 0.5),
    ("syn-corrigir", "syn-analisar", EdgeKind.ACTIVATES, 0.6),
    ("syn-responder", "syn-analisar", EdgeKind.SEMANTIC, 0.4),
]


def bootstrap_graph(graph: CognitiveGraph) -> int:
    """Semeia grafo com sinapses bootstrap se estiver vazio.

    Returns:
        Número de nós adicionados (0 se grafo já tinha conteúdo).
    """
    if graph.node_count > 0:
        return 0

    added = 0
    for spec in _SEED_SYNAPSES:
        if graph.get_node(spec["id"]) is not None:
            continue
        syn = SynapseNode.specialist(
            label=spec["label"],
            id=spec["id"],
            role=spec["role"],
            objective=spec["objective"],
            tier_preference=spec["tier"],
            source=_BOOTSTRAP_SOURCE,
        )
        graph.add_node(syn)
        added += 1

    for src, tgt, kind, weight in _SEED_EDGES:
        if graph.get_node(src) is None or graph.get_node(tgt) is None:
            continue
        edge = GraphEdge.connect(
            src,
            tgt,
            kind,
            weight=weight,
            source=_BOOTSTRAP_SOURCE,
        )
        try:
            graph.add_edge(edge)
        except Exception:
            pass

    return added
