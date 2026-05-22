"""Bootstrap do grafo cognitivo — sementes iniciais para aprendizado."""

from __future__ import annotations

import logging

from arnaldo.graph import (
    CognitiveGraph,
    EdgeKind,
    GraphEdge,
    SourceKind,
    SourceRecord,
)
from arnaldo.graph.node_types import CapabilityNode, SynapseNode

logger = logging.getLogger("arnaldo.kernel.bootstrap")


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
        "depth": 0,
    },
    {
        "id": "syn-planejar",
        "label": "Planejar tarefas",
        "role": "planner",
        "objective": "Decompor requests complexos em etapas executáveis",
        "tier": "expert",
        "depth": 2,
    },
    {
        "id": "syn-analisar",
        "label": "Analisar informação",
        "role": "analyst",
        "objective": "Analisar dados, código ou texto para extrair insights",
        "tier": "expert",
        "depth": 2,
    },
    {
        "id": "syn-criar",
        "label": "Criar artefatos",
        "role": "creator",
        "objective": "Gerar código, texto, documentação ou outros artefatos",
        "tier": "god",
        "depth": 1,
    },
    {
        "id": "syn-corrigir",
        "label": "Corrigir e debugar",
        "role": "debugger",
        "objective": "Identificar e corrigir erros em código ou processos",
        "tier": "expert",
        "depth": 1,
    },
]

# LLM tiers como nós do grafo — o LLM é só um agente
_SEED_LLM_SYNAPSES = [
    {
        "id": "syn-llm-fast",
        "label": "LLM Fast — respostas rápidas",
        "role": "llm_executor",
        "objective": "executar tarefas conversacionais com baixa latência",
        "tier": "fast",
        "depth": 0,
    },
    {
        "id": "syn-llm-expert",
        "label": "LLM Expert — análise e geração complexa",
        "role": "llm_executor",
        "objective": "executar tarefas que requerem raciocínio profundo",
        "tier": "expert",
        "depth": 1,
    },
    {
        "id": "syn-llm-god",
        "label": "LLM God — complexidade máxima",
        "role": "llm_executor",
        "objective": "executar tarefas de máxima complexidade",
        "tier": "god",
        "depth": 3,
    },
    {
        "id": "syn-llm-codex",
        "label": "LLM Codex — geração e análise de código",
        "role": "llm_executor",
        "objective": "executar tarefas de geração e análise de código",
        "tier": "codex",
        "depth": 2,
    },
]

# Arestas que conectam synapses por afinidade funcional
_SEED_EDGES = [
    ("syn-planejar", "syn-criar", EdgeKind.ACTIVATES, 0.7),
    ("syn-planejar", "syn-analisar", EdgeKind.ACTIVATES, 0.6),
    ("syn-analisar", "syn-criar", EdgeKind.ACTIVATES, 0.5),
    ("syn-corrigir", "syn-analisar", EdgeKind.ACTIVATES, 0.6),
    ("syn-responder", "syn-analisar", EdgeKind.SEMANTIC, 0.4),
    # Inibição neural — competição entre synapses
    ("syn-planejar", "syn-responder", EdgeKind.INHIBITS, 0.3),
    ("syn-corrigir", "syn-criar", EdgeKind.INHIBITS, 0.2),
    # REQUIRES: task synapses → LLM synapses
    ("syn-responder", "syn-llm-fast", EdgeKind.REQUIRES, 0.9),
    ("syn-analisar", "syn-llm-expert", EdgeKind.REQUIRES, 0.8),
    ("syn-planejar", "syn-llm-expert", EdgeKind.REQUIRES, 0.85),
    ("syn-criar", "syn-llm-god", EdgeKind.REQUIRES, 0.8),
    ("syn-corrigir", "syn-llm-expert", EdgeKind.REQUIRES, 0.7),
    # Inibição entre LLM tiers (não usar dois ao mesmo tempo)
    ("syn-llm-god", "syn-llm-fast", EdgeKind.INHIBITS, 0.5),
    ("syn-llm-expert", "syn-llm-fast", EdgeKind.INHIBITS, 0.3),
    ("syn-llm-codex", "syn-llm-fast", EdgeKind.INHIBITS, 0.4),
    # G4: REQUIRES para codex
    ("syn-criar", "syn-llm-codex", EdgeKind.REQUIRES, 0.75),
    ("syn-corrigir", "syn-llm-codex", EdgeKind.REQUIRES, 0.7),
    # Capabilities → Sinapses que podem precisar delas
    ("syn-analisar", "cap-search-web", EdgeKind.REQUIRES, 0.6),
    ("syn-responder", "cap-search-web", EdgeKind.REQUIRES, 0.4),
    ("syn-analisar", "cap-http-generic", EdgeKind.REQUIRES, 0.5),
]

# Capabilities bootstrap — "mãos" do substrate
_SEED_CAPABILITIES = [
    {
        "id": "cap-search-web",
        "capability_id": "search.public_web",
        "description": (
            "Buscar informação atual na web — cotações, preços, câmbio, "
            "dólar, euro, bitcoin, ações, bolsa, notícias, clima, tempo, "
            "dados em tempo real, status de serviço, eventos atuais"
        ),
        "module_path": "arnaldo.capabilities.web_search",
        "maturity": "draft",
        "risk_level": "low",
        "requires_network": True,
    },
    {
        "id": "cap-http-generic",
        "capability_id": "connector.http.generic",
        "description": (
            "Fazer requisições HTTP a APIs externas — GET, POST, "
            "REST, JSON, webhook, integração com serviços terceiros"
        ),
        "module_path": "arnaldo.capabilities.http_connector",
        "maturity": "draft",
        "risk_level": "medium",
        "requires_network": True,
    },
]


def bootstrap_graph(graph: CognitiveGraph) -> int:
    """Semeia grafo com sinapses bootstrap se estiver vazio.

    Returns:
        Número de nós adicionados (0 se grafo já tinha conteúdo).
    """
    if graph.node_count > 0:
        return 0

    added = 0
    for spec in [*_SEED_SYNAPSES, *_SEED_LLM_SYNAPSES]:
        if graph.get_node(spec["id"]) is not None:
            continue
        syn = SynapseNode.specialist(
            label=spec["label"],
            id=spec["id"],
            role=spec["role"],
            objective=spec["objective"],
            tier_preference=spec["tier"],
            specialization_depth=spec.get("depth", 0),
            source=_BOOTSTRAP_SOURCE,
        )
        graph.add_node(syn)
        added += 1

    for spec in _SEED_CAPABILITIES:
        if graph.get_node(spec["id"]) is not None:
            continue
        cap = CapabilityNode.tool(
            spec["capability_id"],
            id=spec["id"],
            description=spec["description"],
            module_path=spec["module_path"],
            maturity=spec["maturity"],
            risk_level=spec["risk_level"],
            requires_network=spec.get("requires_network", False),
            source=_BOOTSTRAP_SOURCE,
        )
        graph.add_node(cap)
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
            logger.warning(
                "Falha ao adicionar seed edge %s→%s (%s)",
                src, tgt, kind, exc_info=True,
            )

    return added
