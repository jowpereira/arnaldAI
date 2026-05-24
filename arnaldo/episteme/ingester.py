"""Knowledge Ingester — converte resultados de busca em nós do grafo."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from arnaldo.graph.store import CognitiveGraph
from arnaldo.graph.nodes import MemoryNode
from arnaldo.graph.provenance import SourceRecord, SourceKind
from arnaldo.graph.edge_ops import ensure_edge
from arnaldo.graph.edges import EdgeKind

from .entity_extraction import extract_entities, entity_node_id

logger = logging.getLogger("arnaldo.episteme")

_MAX_SEMANTIC_BATCH = 10
_TECH_ROOT_ID = "ent_technology"


class KnowledgeIngester:
    """Ingere resultados de busca web como nós no grafo cognitivo."""

    def _create_entity_nodes(
        self,
        graph: CognitiveGraph,
        source_node_id: str,
        entities: list[tuple[str, str]],
        domain: str,
    ) -> int:
        """Cria nós de entidade e arestas MENTIONS. Retorna nº de arestas criadas."""
        edges_created = 0
        for name, entity_type in entities:
            ent_id = entity_node_id(name)
            if not graph.has_node(ent_id):
                src = SourceRecord(
                    kind=SourceKind.INFERENCE,
                    identifier="entity.extraction",
                    confidence=0.60,
                )
                ent_node = MemoryNode.semantic(
                    label=f"entity::{name}",
                    id=ent_id,
                    source=src,
                    payload={"entity_type": entity_type, "name": name},
                    domain=domain,
                )
                graph.add_node(ent_node)

            ensure_edge(
                graph,
                source_id=source_node_id,
                target_id=ent_id,
                kind=EdgeKind.MENTIONS,
                weight=0.5,
            )
            edges_created += 1

            if entity_type == "technology":
                self._ensure_tech_root(graph, domain)
                ensure_edge(
                    graph,
                    source_id=ent_id,
                    target_id=_TECH_ROOT_ID,
                    kind=EdgeKind.IS_A,
                    weight=0.7,
                )
                edges_created += 1

        return edges_created

    def _ensure_tech_root(self, graph: CognitiveGraph, domain: str) -> None:
        """Cria nó raiz 'technology' se não existir."""
        if graph.has_node(_TECH_ROOT_ID):
            return
        src = SourceRecord(
            kind=SourceKind.BOOTSTRAP,
            identifier="entity.taxonomy",
        )
        root = MemoryNode.semantic(
            label="entity::technology",
            id=_TECH_ROOT_ID,
            source=src,
            payload={"entity_type": "category", "name": "technology"},
            domain=domain,
        )
        graph.add_node(root)

    def ingest_search_results(
        self,
        graph: CognitiveGraph,
        results: list[dict[str, Any]],
        *,
        query: str,
        domain: str = "external_knowledge",
    ) -> list[str]:
        """Cria nós de memória a partir de resultados de busca."""
        created: list[str] = []

        for item in results:
            title = str(item.get("title", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            url = str(item.get("url", "")).strip()
            if not title or not snippet:
                continue

            node_id = f"web_{hashlib.sha256(url.encode()).hexdigest()[:12]}"
            if graph.has_node(node_id):
                continue

            source = SourceRecord(
                kind=SourceKind.EXTERNAL_AUTHORITY,
                identifier=url or f"web:{query}",
                confidence=0.55,
            )
            node = MemoryNode.semantic(
                label=f"web::{title[:120]}",
                id=node_id,
                source=source,
                payload={
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "query": query,
                    "memory_type": "semantic",
                },
                domain=domain,
            )
            graph.add_node(node)
            created.append(node.id)

            # Extrai entidades do título + snippet
            text = f"{title} {snippet}"
            entities = extract_entities(text)
            if entities:
                self._create_entity_nodes(graph, node_id, entities, domain)

        # Guard: limita batch de arestas semânticas O(n²)
        if len(created) > _MAX_SEMANTIC_BATCH:
            logger.warning(
                "Batch excede máximo semântico (%d > %d)",
                len(created),
                _MAX_SEMANTIC_BATCH,
            )
            return created

        # Liga nós do mesmo batch com arestas semânticas
        for i, a in enumerate(created):
            for b in created[i + 1 :]:
                ensure_edge(
                    graph,
                    source_id=a,
                    target_id=b,
                    kind=EdgeKind.SEMANTIC,
                    weight=0.4,
                )

        return created
