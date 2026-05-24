"""Testes para extração de entidades e integração com o ingester."""

from __future__ import annotations

from arnaldo.episteme.entity_extraction import extract_entities, entity_node_id
from arnaldo.episteme.ingester import KnowledgeIngester
from arnaldo.graph import CognitiveGraph
from arnaldo.graph.edges import EdgeKind


class TestExtractEntities:
    def test_extract_entities_backtick(self) -> None:
        entities = extract_entities("Use `Python` for scripting")
        names = {e[0] for e in entities}
        types = {e[0]: e[1] for e in entities}
        assert "Python" in names
        assert types["Python"] == "technology"

    def test_extract_entities_url(self) -> None:
        entities = extract_entities("Visit http://example.com for docs")
        names = {e[0] for e in entities}
        types = {e[0]: e[1] for e in entities}
        assert "http://example.com" in names
        assert types["http://example.com"] == "url"

    def test_extract_entities_proper_nouns(self) -> None:
        entities = extract_entities("Azure OpenAI is a service")
        names = {e[0] for e in entities}
        types = {e[0]: e[1] for e in entities}
        assert "Azure OpenAI" in names
        assert types["Azure OpenAI"] == "concept"

    def test_extract_entities_known_tech(self) -> None:
        entities = extract_entities("We use Docker and Kubernetes")
        names = {e[0].lower() for e in entities}
        assert "docker" in names
        assert "kubernetes" in names

    def test_extract_entities_dedup(self) -> None:
        entities = extract_entities("`Python` is great. `Python` is fast.")
        python_entities = [e for e in entities if e[0].lower() == "python"]
        assert len(python_entities) == 1


class TestIngesterEntities:
    def test_ingest_creates_entity_nodes(self) -> None:
        graph = CognitiveGraph()
        ingester = KnowledgeIngester()
        results = [
            {
                "title": "Getting started with `React`",
                "snippet": "React is a JavaScript library",
                "url": "http://example.com/react",
            }
        ]
        created = ingester.ingest_search_results(graph, results, query="react")
        assert len(created) == 1

        # Deve ter criado nós de entidade para React e JavaScript
        react_id = entity_node_id("React")
        js_id = entity_node_id("JavaScript")
        assert graph.has_node(react_id) or graph.has_node(entity_node_id("react"))
        assert graph.has_node(js_id) or graph.has_node(entity_node_id("javascript"))

        # Deve ter arestas MENTIONS
        web_node_id = created[0]
        mentions = list(graph.iter_edges_from(web_node_id, kinds=[EdgeKind.MENTIONS]))
        assert len(mentions) >= 1

    def test_entity_deduplication(self) -> None:
        graph = CognitiveGraph()
        ingester = KnowledgeIngester()
        results = [
            {
                "title": "`Python` guide",
                "snippet": "Learn `Python` basics",
                "url": "http://example.com/py1",
            },
            {
                "title": "`Python` advanced",
                "snippet": "Advanced `Python` patterns",
                "url": "http://example.com/py2",
            },
        ]
        ingester.ingest_search_results(graph, results, query="python")

        # Python entity deve existir apenas 1x
        py_id = entity_node_id("Python")
        assert graph.has_node(py_id)
        # Contar nós entity::Python
        py_nodes = [n for n in graph.iter_nodes(active_only=False) if n.label == "entity::Python"]
        assert len(py_nodes) == 1
