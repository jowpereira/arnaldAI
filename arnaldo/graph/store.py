"""``CognitiveGraph`` — store principal do substrate cognitivo.

Wrapper opinado sobre :class:`networkx.MultiDiGraph` que adiciona:

* tipagem forte (nós e arestas com schemas),
* indexação secundária (por kind, domain, tag),
* operações sinápticas (ativação, plasticidade),
* persistência via msgpack/JSON,
* matching híbrido injetado.

**Decisão arquitetural — por que MultiDiGraph e não DiGraph simples:**

O grafo cognitivo é intrinsecamente multi-relacional: dois nós podem ter ao
mesmo tempo uma aresta SEMANTIC (similaridade) e uma CAUSAL (A causou B). Forçar
DiGraph simples colapsaria essas dimensões. ``MultiDiGraph`` mantém cada aresta
identificável pelo seu ``key`` (que aqui é o ``edge.id``).

**Invariantes mantidos:**

I1. Todo nó tem ``id`` único globalmente.
I2. Toda aresta referencia source/target que existem em ``V``.
I3. Toda aresta tem ``kind`` válido (``EdgeKind``).
I4. Nenhum nó/aresta sem ``SourceRecord``.
I5. Janelas de validade são consistentes (``valid_to > valid_from``).

Violar qualquer invariante levanta exceção *no momento* da operação — falhas
nunca são silenciosas.

```
                       ┌─────────────────────────┐
                       │    CognitiveGraph       │
                       │                         │
                       │  ┌───────────────────┐  │
                       │  │  MultiDiGraph     │  │
                       │  │  (nx.MultiDiGraph)│  │
                       │  └───────────────────┘  │
                       │  ┌───────────────────┐  │
                       │  │  Índices          │  │
                       │  │  by_kind          │  │
                       │  │  by_domain        │  │
                       │  │  by_tag           │  │
                       │  └───────────────────┘  │
                       │  ┌───────────────────┐  │
                       │  │  PlasticityEngine │  │
                       │  │  HybridMatcher    │  │
                       │  └───────────────────┘  │
                       └─────────────────────────┘
```
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

import msgpack
import networkx as nx
import numpy as np

from .edges import EdgeKind, GraphEdge
from .matching import HybridMatcher, MatchResult
from .nodes import CapabilityNode, GraphNode, MemoryNode, NodeKind, NodeStatus, SynapseNode
from .plasticity import PlasticityEngine
from .provenance import SourceKind, SourceRecord
from .refs import GraphRef, GraphRefKind, GraphRegistry, _new_graph_id
from .temporal import BiTemporal, ValidityWindow, utc_now


# ────────────────────────────────────────────────────────────────────────────
# Eventos / Telemetria
# ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class GraphEvent:
    """Telemetria mínima de mutação no grafo, alimenta Evidence Ledger."""

    kind: str  # "node_added" | "edge_added" | "activation" | "decay_swept" ...
    target_id: str
    at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


# ────────────────────────────────────────────────────────────────────────────
# CognitiveGraph
# ────────────────────────────────────────────────────────────────────────────


class CognitiveGraph:
    """Substrate cognitivo unificado — nós e arestas tipados, com plasticidade.

    Operações principais:

    * ``add_node(node)``         — adiciona ou substitui um nó.
    * ``add_edge(edge)``         — adiciona aresta tipada.
    * ``activate(node_id)``      — marca ativação (usado em runtime).
    * ``record_outcome(node_id, success)`` — Hebbian update após uma run.
    * ``match(query=..., ...)``  — retrieval híbrido (vector + graph).
    * ``sweep_decay()``          — aplica decaimento, marca STALE/ARCHIVED.
    * ``persist(path)`` / ``load(path)`` — serialização msgpack.

    Composição:

    ``cog = CognitiveGraph()``
        + ``cog.plasticity``  → PlasticityEngine (defaults razoáveis)
        + ``cog.matcher``     → HybridMatcher (defaults razoáveis)
    """

    # ── Construção ────────────────────────────────────────────────────────

    def __init__(
        self,
        *,
        graph_id: str | None = None,
        plasticity: PlasticityEngine | None = None,
        matcher: HybridMatcher | None = None,
        registry: GraphRegistry | None = None,
    ) -> None:
        # Identidade — usado como nó na hierarquia GraphRegistry
        self._graph_id: str = graph_id or _new_graph_id()

        self._g: nx.MultiDiGraph = nx.MultiDiGraph()
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}

        # Índices secundários (atualizados em add/remove)
        self._by_kind: dict[NodeKind, set[str]] = defaultdict(set)
        self._by_domain: dict[str, set[str]] = defaultdict(set)
        self._by_tag: dict[str, set[str]] = defaultdict(set)

        # Composições
        self.plasticity: PlasticityEngine = plasticity or PlasticityEngine()
        self.matcher: HybridMatcher = matcher or HybridMatcher()
        self._registry: GraphRegistry | None = registry

        # Snapshots/Federated refs são resolvidos em read-only.
        self._read_only: bool = False

        # Telemetria opcional (lista circular curta — produção plugar logger)
        self._events: list[GraphEvent] = []

    # ── Identidade ───────────────────────────────────────────────────────

    @property
    def graph_id(self) -> str:
        """ID único deste grafo. Usado por ``GraphRegistry``."""
        return self._graph_id

    def _bind_graph_id(self, gid: str) -> None:
        """Reassigna o ``graph_id``. Usado apenas pelo ``GraphRegistry``."""
        self._graph_id = gid

    def _bind_registry(self, registry: GraphRegistry) -> None:
        """Associa este grafo a um ``GraphRegistry``."""
        self._registry = registry

    @property
    def registry(self) -> GraphRegistry | None:
        return self._registry

    @property
    def is_read_only(self) -> bool:
        return self._read_only

    def _set_read_only(self, value: bool = True) -> None:
        self._read_only = bool(value)

    def _assert_mutable(self) -> None:
        if self._read_only:
            raise RuntimeError(
                f"CognitiveGraph '{self._graph_id}' está em modo read-only."
            )

    # ── Adição / remoção ─────────────────────────────────────────────────

    def add_node(self, node: GraphNode) -> GraphNode:
        """Adiciona ou substitui um nó.

        Side-effects:
            * Atualiza índices ``by_kind``, ``by_domain``, ``by_tag``.
            * Adiciona ao ``nx.MultiDiGraph``.
            * Emite ``GraphEvent("node_added", ...)``.

        Raises:
            ValueError: se id contém caracteres inválidos.
        """
        self._assert_mutable()
        if not node.id:
            raise ValueError("Node sem id não pode ser adicionado")
        # Remove de índices antigos se já existia
        if node.id in self._nodes:
            self._remove_from_indices(self._nodes[node.id])
        self._nodes[node.id] = node
        self._g.add_node(node.id, kind=node.kind.value)
        self._add_to_indices(node)
        self._record(GraphEvent("node_added", node.id, utc_now(), {"kind": node.kind.value}))
        return node

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        """Adiciona aresta. Source/target devem existir; tipo deve ser válido.

        Raises:
            KeyError: se source ou target inexistentes.
            ValueError: se aresta viola invariantes.
        """
        self._assert_mutable()
        if edge.source_id not in self._nodes:
            raise KeyError(f"source_id {edge.source_id} inexistente")
        if edge.target_id not in self._nodes:
            raise KeyError(f"target_id {edge.target_id} inexistente")
        if edge.id in self._edges:
            self._g.remove_edge(
                self._edges[edge.id].source_id,
                self._edges[edge.id].target_id,
                key=edge.id,
            )
        self._edges[edge.id] = edge
        self._g.add_edge(edge.source_id, edge.target_id, key=edge.id, kind=edge.kind.value)
        # Para arestas semânticas, espelha (não-direcional)
        if not edge.kind.is_directed and edge.source_id != edge.target_id:
            self._g.add_edge(
                edge.target_id, edge.source_id, key=edge.id, kind=edge.kind.value
            )
        self._record(
            GraphEvent("edge_added", edge.id, utc_now(), {"kind": edge.kind.value})
        )
        return edge

    def remove_node(self, node_id: str) -> None:
        """Remove nó e todas as arestas incidentes."""
        self._assert_mutable()
        if node_id not in self._nodes:
            return
        # Remove arestas incidentes do dicionário local
        incident = [
            eid for eid, e in self._edges.items()
            if e.source_id == node_id or e.target_id == node_id
        ]
        for eid in incident:
            del self._edges[eid]
        node = self._nodes.pop(node_id)
        self._remove_from_indices(node)
        self._g.remove_node(node_id)
        self._record(GraphEvent("node_removed", node_id, utc_now()))

    # ── Lookup ───────────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def get_edge(self, edge_id: str) -> GraphEdge | None:
        return self._edges.get(edge_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    # ── Iteração / filtros ───────────────────────────────────────────────

    def iter_nodes(
        self,
        *,
        kind: NodeKind | None = None,
        domain: str | None = None,
        tag: str | None = None,
        active_only: bool = True,
    ) -> Iterator[GraphNode]:
        """Itera nós filtrando por dimensões comuns."""
        if kind is not None:
            ids: Iterable[str] = self._by_kind.get(kind, set())
        elif domain is not None:
            ids = self._by_domain.get(domain, set())
        elif tag is not None:
            ids = self._by_tag.get(tag, set())
        else:
            ids = self._nodes.keys()

        for node_id in ids:
            node = self._nodes.get(node_id)
            if node is None:
                continue
            if active_only and not node.is_active:
                continue
            yield node

    def iter_edges_from(
        self,
        node_id: str,
        *,
        kinds: Iterable[EdgeKind] | None = None,
        active_only: bool = True,
    ) -> Iterator[GraphEdge]:
        """Itera arestas saindo de ``node_id``, filtrando por kind."""
        kind_set = {k for k in kinds} if kinds is not None else None
        if node_id not in self._g:
            return
        for _, target_id, key in self._g.out_edges(node_id, keys=True):
            edge = self._edges.get(key)
            if edge is None:
                continue
            if kind_set is not None and edge.kind not in kind_set:
                continue
            if active_only and not edge.is_active:
                continue
            yield edge

    def iter_edges_to(
        self,
        node_id: str,
        *,
        kinds: Iterable[EdgeKind] | None = None,
        active_only: bool = True,
    ) -> Iterator[GraphEdge]:
        """Itera arestas entrando em ``node_id``."""
        kind_set = {k for k in kinds} if kinds is not None else None
        if node_id not in self._g:
            return
        for source_id, _, key in self._g.in_edges(node_id, keys=True):
            edge = self._edges.get(key)
            if edge is None:
                continue
            if kind_set is not None and edge.kind not in kind_set:
                continue
            if active_only and not edge.is_active:
                continue
            yield edge

    def neighbors(
        self, node_id: str, *, kinds: Iterable[EdgeKind] | None = None
    ) -> Iterator[GraphNode]:
        """Vizinhos imediatos (out-edges) filtrando por kind."""
        for edge in self.iter_edges_from(node_id, kinds=kinds):
            neighbor = self._nodes.get(edge.target_id)
            if neighbor is not None:
                yield neighbor

    # ── Operações sinápticas (runtime) ───────────────────────────────────

    def activate(self, node_id: str, *, at: datetime | None = None) -> None:
        """Registra ativação de um nó. Sem efeito se nó inexistente."""
        self._assert_mutable()
        node = self._nodes.get(node_id)
        if node is None:
            return
        node.activate(at)
        self._record(GraphEvent("activation", node_id, at or utc_now()))

    def record_outcome(self, node_id: str, *, success: bool) -> None:
        """Aplica Hebbian update após resultado da ativação."""
        self._assert_mutable()
        node = self._nodes.get(node_id)
        if node is None:
            return
        updated = self.plasticity.update_node(node, success=success)
        self._nodes[node_id] = updated
        self._record(
            GraphEvent("hebbian", node_id, utc_now(), {"success": success})
        )

    def record_edge_outcome(self, edge_id: str, *, success: bool) -> None:
        """Hebbian update em arestas sinápticas (ACTIVATES, COLLAB, INHIBITS)."""
        self._assert_mutable()
        edge = self._edges.get(edge_id)
        if edge is None:
            return
        updated = self.plasticity.update_edge(edge, success=success)
        self._edges[edge_id] = updated

    # ── Sub-grafos referenciados ─────────────────────────────────────────

    def attach_subgraph(
        self,
        node_id: str,
        subgraph: CognitiveGraph,
        *,
        kind: GraphRefKind = GraphRefKind.OWNED,
        bridge_nodes: list[str] | None = None,
        uri: Path | None = None,
        ref_strength: float = 0.5,
    ) -> GraphRef:
        """Anexa ``subgraph`` como sub-grafo do nó ``node_id``.

        Args:
            node_id:       Nó-pai que ganhará a referência.
            subgraph:      Sub-grafo a anexar.
            kind:          Tipo da relação (OWNED ou SHARED na Fase 2).
            bridge_nodes:  IDs no sub-grafo expostos como interface.
            uri:           Path opcional para persistência do sub-grafo.
            ref_strength:  Peso inicial da referência ∈ [0,1].

        Returns:
            ``GraphRef`` criada e anexada ao nó.

        Raises:
            KeyError: nó-pai inexistente.
            ValueError: se o nó-pai não pertence a este grafo.
            GraphCycleError: anexar criaria ciclo (via registry).
            RuntimeError: se nenhum ``GraphRegistry`` configurado.
        """
        self._assert_mutable()
        node = self._nodes.get(node_id)
        if node is None:
            raise KeyError(f"node {node_id} não existe em {self.graph_id}")

        registry = self._registry
        if registry is None:
            # Auto-cria registry mínimo para isolar este grafo
            registry = GraphRegistry()
            registry.register(self, graph_id=self._graph_id)
            self._registry = registry

        # Garante que self está registrado
        if registry.get(self._graph_id) is None:
            registry.register(self, graph_id=self._graph_id)

        if kind == GraphRefKind.FEDERATED and uri is None:
            raise ValueError("GraphRefKind.FEDERATED exige uri.")

        effective_uri = Path(uri) if uri is not None else None
        target_subgraph = subgraph
        target_graph_id = subgraph._graph_id

        if kind == GraphRefKind.SNAPSHOT:
            if effective_uri is None:
                base_path = registry._base_path  # pylint: disable=protected-access
                if base_path is None:
                    raise ValueError(
                        "GraphRefKind.SNAPSHOT exige uri ou GraphRegistry(base_path=...)."
                    )
                snapshot_dir = Path(base_path) / "snapshots"
                snapshot_dir.mkdir(parents=True, exist_ok=True)
                snapshot_name = f"{subgraph.graph_id}_{utc_now().strftime('%Y%m%dT%H%M%S%f')}.msgpack"
                effective_uri = snapshot_dir / snapshot_name
            subgraph.persist(effective_uri)
            target_subgraph = CognitiveGraph.load(effective_uri, registry=registry)
            target_subgraph._set_read_only(True)
            target_graph_id = _new_graph_id()

        # Registra sub-grafo (gera id se necessário)
        sub_gid = registry.register(target_subgraph, graph_id=target_graph_id, uri=effective_uri)

        # Marca ownership/refcount
        if kind == GraphRefKind.OWNED:
            registry.mark_owned(
                parent_graph_id=self._graph_id,
                parent_node_id=node_id,
                child_graph_id=sub_gid,
            )
        registry.incr_refcount(sub_gid)

        # Cria e anexa GraphRef
        ref = GraphRef(
            graph_id=sub_gid,
            kind=kind,
            uri=str(effective_uri) if effective_uri else None,
            bridge_nodes=tuple(bridge_nodes or []),
            ref_strength=ref_strength,
        )
        node.attach_ref(ref)

        self._record(
            GraphEvent(
                "subgraph_attached",
                node_id,
                utc_now(),
                {"sub_graph_id": sub_gid, "kind": kind.value},
            )
        )
        return ref

    def detach_subgraph(self, node_id: str, sub_graph_id: str) -> bool:
        """Remove referência de ``sub_graph_id`` no nó ``node_id``.

        Para ``OWNED``: também desregistra o sub-grafo do registry.
        Para ``SHARED``: apenas decrementa refcount.

        Returns:
            ``True`` se a referência foi encontrada e removida.
        """
        self._assert_mutable()
        node = self._nodes.get(node_id)
        if node is None:
            return False
        ref = node.detach_ref(sub_graph_id)
        if ref is None:
            return False
        if self._registry is not None:
            remaining = self._registry.decr_refcount(sub_graph_id)
            if ref.kind == GraphRefKind.OWNED and remaining == 0:
                self._registry.unregister(sub_graph_id)
        self._record(
            GraphEvent(
                "subgraph_detached",
                node_id,
                utc_now(),
                {"sub_graph_id": sub_graph_id, "kind": ref.kind.value},
            )
        )
        return True

    def resolve_subgraph(self, ref: GraphRef) -> CognitiveGraph | None:
        """Resolve ``GraphRef`` para ``CognitiveGraph`` (lazy via registry)."""
        if self._registry is None:
            return None
        return self._registry.resolve(ref)

    def iter_subgraphs(
        self, node_id: str
    ) -> Iterator[tuple[GraphRef, CognitiveGraph | None]]:
        """Itera (ref, sub_grafo_resolvido) para todos os sub-grafos do nó."""
        node = self._nodes.get(node_id)
        if node is None:
            return
        for ref in node.subgraph_refs:
            yield ref, self.resolve_subgraph(ref)

    def record_outcome_recursive(
        self,
        node_id: str,
        *,
        success: bool,
        scoped_activations: dict[str, set[str]] | None = None,
        depth: int = 0,
        max_depth: int = 3,
    ) -> None:
        """Propaga plasticidade Hebbian através da hierarquia de sub-grafos.

        Args:
            node_id:             Nó no grafo atual.
            success:             Resultado da run.
            scoped_activations:  Map ``{graph_id: {node_ids ativados}}``,
                                 fornecido pelo runtime. Sem ele, propagação
                                 não desce (segurança — evita reforçar nós
                                 que nunca foram tocados).
            depth:               Profundidade atual.
            max_depth:           Limite (default 3) — evita explosão.

        Pseudo-código formal::

            P(n, s):
                self.record_outcome(n, s)               # local
                if depth ≥ max_depth: return
                for ref ∈ n.subgraph_refs:
                    G' = resolve(ref)
                    for n' ∈ scoped_activations[ref.graph_id]:
                        G'.record_outcome_recursive(n', s, depth+1)
        """
        self._assert_mutable()
        self.record_outcome(node_id, success=success)

        if depth >= max_depth:
            return

        node = self._nodes.get(node_id)
        if node is None or not node.has_subgraphs:
            return

        for ref in node.subgraph_refs:
            subgraph = self.resolve_subgraph(ref)
            if subgraph is None:
                continue

            if not ref.kind.allows_mutation:
                continue

            # Sem trace de ativação, não desce (evita reforço espúrio)
            if not scoped_activations:
                continue

            activated_in_sub = scoped_activations.get(ref.graph_id, set())
            for sub_node_id in activated_in_sub:
                subgraph.record_outcome_recursive(
                    sub_node_id,
                    success=success,
                    scoped_activations=scoped_activations,
                    depth=depth + 1,
                    max_depth=max_depth,
                )

            # Plasticidade da própria referência (peso da ref no nó-pai)
            ref_updated = ref.with_strength(
                self.plasticity.rule.update(
                    ref.ref_strength,
                    1.0 if success else 0.0,
                )
            )
            # Substitui in-place
            for i, existing in enumerate(node.subgraph_refs):
                if existing.graph_id == ref.graph_id:
                    node.subgraph_refs[i] = ref_updated
                    break

    def federated_match(
        self,
        node_id: str,
        *,
        query: str | None = None,
        query_embedding: np.ndarray | None = None,
        intent: str | None = None,
    ) -> dict[str, list[MatchResult]]:
        """Executa ``match`` em sub-grafos do nó, agregando por graph_id.

        Estratégia: para cada sub-grafo referenciado, executa retrieval no
        escopo dos ``bridge_nodes`` (se especificados). Útil para "consultar"
        agentes referenciados sem revelar todo o seu mundo interno.

        Returns:
            Map ``{graph_id: [MatchResult, ...]}``.
        """
        results: dict[str, list[MatchResult]] = {}
        node = self._nodes.get(node_id)
        if node is None:
            return results
        for ref in node.subgraph_refs:
            subgraph = self.resolve_subgraph(ref)
            if subgraph is None:
                continue
            sub_results = subgraph.match(
                query=query,
                query_embedding=query_embedding,
                intent=intent,
            )
            # Filtra para bridge_nodes se especificado
            if ref.bridge_nodes:
                allowed = set(ref.bridge_nodes)
                sub_results = [
                    r for r in sub_results
                    if r.node.id in allowed
                    # ou conectado a bridge — implementação básica:
                    # apenas filtra estritos por enquanto
                ]
            results[ref.graph_id] = sub_results
        return results

    # ── Decaimento periódico ─────────────────────────────────────────────

    def sweep_decay(self, *, at: datetime | None = None) -> dict[str, int]:
        """Varre todos os nós aplicando decay → status.

        Retorna contadores dos nós que mudaram de estado, útil para
        observabilidade. Operação ``O(|V|)`` — chamada periodicamente
        (uma vez por run, scheduled job, etc).
        """
        self._assert_mutable()
        now = at or utc_now()
        counters = {"to_stale": 0, "to_archived": 0, "to_consolidated": 0}
        for node_id, node in list(self._nodes.items()):
            suggested = self.plasticity.classify_status(node, at=now)
            new_status = {
                "candidate": NodeStatus.CANDIDATE,
                "active": NodeStatus.ACTIVE,
                "consolidated": NodeStatus.CONSOLIDATED,
                "stale": NodeStatus.STALE,
                "archived": NodeStatus.ARCHIVED,
            }[suggested]
            if new_status != node.status:
                self._nodes[node_id] = node.with_status(new_status)
                if new_status == NodeStatus.STALE:
                    counters["to_stale"] += 1
                elif new_status == NodeStatus.ARCHIVED:
                    counters["to_archived"] += 1
                elif new_status == NodeStatus.CONSOLIDATED:
                    counters["to_consolidated"] += 1
        self._record(GraphEvent("decay_swept", "<all>", now, dict(counters)))
        return counters

    # ── Retrieval ────────────────────────────────────────────────────────

    def match(
        self,
        *,
        query: str | None = None,
        query_embedding: np.ndarray | None = None,
        intent: str | None = None,
        node_kinds: Iterable[NodeKind] | None = None,
    ) -> list[MatchResult]:
        """Conveniência — delega para ``self.matcher``.

        Args:
            query:           texto da query.
            query_embedding: embedding pré-computado (preferível).
            intent:          intenção ("why"/"when"/etc); inferido se ausente.
            node_kinds:      filtro por tipo de nó.
        """
        kind_values = [k.value for k in node_kinds] if node_kinds else None
        return self.matcher.retrieve(
            self,
            query=query,
            query_embedding=query_embedding,
            intent=intent,
            node_kinds=kind_values,
        )

    # ── Persistência ─────────────────────────────────────────────────────

    def persist(self, path: Path) -> Path:
        """Serializa grafo em msgpack binário (compacto, rápido).

        Schema ``cognitive-graph/v2`` preserva:
          * ``graph_id`` (identidade na hierarquia)
          * Nós + ``subgraph_refs``
          * Arestas
          * Embeddings como bytes
          * Bitemp como ISO 8601

        Sub-grafos referenciados **não são** serializados aqui — cada um
        persiste em arquivo próprio. ``uri`` na ``GraphRef`` aponta para eles.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "cognitive-graph/v2",
            "graph_id": self._graph_id,
            "nodes": [_serialize_node(n) for n in self._nodes.values()],
            "edges": [_serialize_edge(e) for e in self._edges.values()],
        }
        with path.open("wb") as f:
            msgpack.pack(payload, f, use_bin_type=True)
        return path

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        plasticity: PlasticityEngine | None = None,
        matcher: HybridMatcher | None = None,
        registry: GraphRegistry | None = None,
    ) -> CognitiveGraph:
        """Carrega grafo de arquivo msgpack.

        Suporta v1 (legacy, sem graph_id/subgraph_refs) e v2.
        """
        with Path(path).open("rb") as f:
            payload = msgpack.unpack(f, raw=False)
        version = payload.get("version")
        if version not in {"cognitive-graph/v1", "cognitive-graph/v2"}:
            raise ValueError(f"Versão de schema desconhecida: {version}")
        cog = cls(
            graph_id=payload.get("graph_id"),
            plasticity=plasticity,
            matcher=matcher,
            registry=registry,
        )
        for n_data in payload["nodes"]:
            cog.add_node(_deserialize_node(n_data))
        for e_data in payload["edges"]:
            cog.add_edge(_deserialize_edge(e_data))
        return cog

    # ── Diagnostics ─────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Resumo estrutural — útil para logs e debugging."""
        kind_counts = {k.value: len(v) for k, v in self._by_kind.items()}
        edge_kind_counts: dict[str, int] = defaultdict(int)
        for e in self._edges.values():
            edge_kind_counts[e.kind.value] += 1
        return {
            "nodes_total": self.node_count,
            "edges_total": self.edge_count,
            "nodes_by_kind": kind_counts,
            "edges_by_kind": dict(edge_kind_counts),
            "domains": sorted(self._by_domain.keys()),
            "tags_top_10": _top_n_tags(self._by_tag, 10),
        }

    # ── Helpers internos ────────────────────────────────────────────────

    def _add_to_indices(self, node: GraphNode) -> None:
        self._by_kind[node.kind].add(node.id)
        self._by_domain[node.domain].add(node.id)
        for tag in node.tags:
            self._by_tag[tag].add(node.id)

    def _remove_from_indices(self, node: GraphNode) -> None:
        self._by_kind[node.kind].discard(node.id)
        self._by_domain[node.domain].discard(node.id)
        for tag in node.tags:
            self._by_tag[tag].discard(node.id)

    def _record(self, event: GraphEvent) -> None:
        self._events.append(event)
        # Mantém apenas últimos 1000 eventos em memória — produção plugar logger
        if len(self._events) > 1000:
            self._events = self._events[-500:]


# ────────────────────────────────────────────────────────────────────────────
# Serialização interna
# ────────────────────────────────────────────────────────────────────────────


def _serialize_node(n: GraphNode) -> dict[str, Any]:
    """Converte ``GraphNode`` em dict serializável por msgpack."""
    return {
        "id": n.id,
        "kind": n.kind.value,
        "label": n.label,
        "payload": n.payload,
        "embedding": n.embedding.tobytes() if n.embedding is not None else None,
        "embedding_shape": list(n.embedding.shape) if n.embedding is not None else None,
        "embedding_dtype": str(n.embedding.dtype) if n.embedding is not None else None,
        "weight": n.weight,
        "status": n.status.value,
        "bitemp": _serialize_bitemp(n.bitemp),
        "source": _serialize_source(n.source),
        "stats": {
            "activations": n.stats.activations,
            "successes": n.stats.successes,
            "failures": n.stats.failures,
            "last_activated_at": n.stats.last_activated_at.isoformat()
            if n.stats.last_activated_at else None,
            "last_refreshed_at": n.stats.last_refreshed_at.isoformat()
            if n.stats.last_refreshed_at else None,
        },
        "tags": sorted(n.tags),
        "domain": n.domain,
        "subgraph_refs": [_serialize_ref(r) for r in n.subgraph_refs],
    }


def _serialize_ref(r: GraphRef) -> dict[str, Any]:
    """Serializa ``GraphRef``."""
    return {
        "graph_id": r.graph_id,
        "kind": r.kind.value,
        "uri": r.uri,
        "bridge_nodes": list(r.bridge_nodes),
        "attached_at": r.attached_at.isoformat(),
        "ref_strength": r.ref_strength,
    }


def _deserialize_ref(data: dict[str, Any]) -> GraphRef:
    return GraphRef(
        graph_id=data["graph_id"],
        kind=GraphRefKind(data["kind"]),
        uri=data.get("uri"),
        bridge_nodes=tuple(data.get("bridge_nodes", [])),
        attached_at=datetime.fromisoformat(data["attached_at"]),
        ref_strength=float(data.get("ref_strength", 0.5)),
    )


def _deserialize_node(data: dict[str, Any]) -> GraphNode:
    from .nodes import NodeStats  # tardio para evitar ciclo

    kind = NodeKind(data["kind"])
    cls_map = {
        NodeKind.MEMORY: MemoryNode,
        NodeKind.SYNAPSE: SynapseNode,
        NodeKind.CAPABILITY: CapabilityNode,
    }
    cls = cls_map[kind]
    embedding = None
    if data.get("embedding"):
        arr = np.frombuffer(data["embedding"], dtype=data["embedding_dtype"])
        embedding = arr.reshape(data["embedding_shape"]).astype(np.float32)
    stats = NodeStats(
        activations=data["stats"]["activations"],
        successes=data["stats"]["successes"],
        failures=data["stats"]["failures"],
        last_activated_at=datetime.fromisoformat(data["stats"]["last_activated_at"])
        if data["stats"]["last_activated_at"] else None,
        last_refreshed_at=datetime.fromisoformat(data["stats"]["last_refreshed_at"])
        if data["stats"]["last_refreshed_at"] else None,
    )
    return cls(
        id=data["id"],
        kind=kind,
        label=data["label"],
        payload=dict(data["payload"]),
        embedding=embedding,
        weight=float(data["weight"]),
        status=NodeStatus(data["status"]),
        bitemp=_deserialize_bitemp(data["bitemp"]),
        source=_deserialize_source(data["source"]),
        stats=stats,
        tags=set(data["tags"]),
        domain=data["domain"],
        subgraph_refs=[
            _deserialize_ref(r) for r in data.get("subgraph_refs", [])
        ],
    )


def _serialize_edge(e: GraphEdge) -> dict[str, Any]:
    return {
        "id": e.id,
        "source_id": e.source_id,
        "target_id": e.target_id,
        "kind": e.kind.value,
        "weight": e.weight,
        "bitemp": _serialize_bitemp(e.bitemp),
        "source": _serialize_source(e.source),
        "payload": e.payload,
        "activations": e.activations,
        "successes": e.successes,
        "failures": e.failures,
        "last_activated_at": e.last_activated_at.isoformat()
        if e.last_activated_at else None,
    }


def _deserialize_edge(data: dict[str, Any]) -> GraphEdge:
    return GraphEdge(
        id=data["id"],
        source_id=data["source_id"],
        target_id=data["target_id"],
        kind=EdgeKind(data["kind"]),
        weight=float(data["weight"]),
        bitemp=_deserialize_bitemp(data["bitemp"]),
        source=_deserialize_source(data["source"]),
        payload=dict(data["payload"]),
        activations=data.get("activations", 0),
        successes=data.get("successes", 0),
        failures=data.get("failures", 0),
        last_activated_at=datetime.fromisoformat(data["last_activated_at"])
        if data.get("last_activated_at") else None,
    )


def _serialize_bitemp(b: BiTemporal) -> dict[str, Any]:
    return {
        "valid_from": b.window.valid_from.isoformat(),
        "valid_to": b.window.valid_to.isoformat() if b.window.valid_to else None,
        "recorded_at": b.recorded_at.isoformat(),
        "invalidated_at": b.invalidated_at.isoformat() if b.invalidated_at else None,
    }


def _deserialize_bitemp(data: dict[str, Any]) -> BiTemporal:
    window = ValidityWindow(
        valid_from=datetime.fromisoformat(data["valid_from"]),
        valid_to=datetime.fromisoformat(data["valid_to"]) if data["valid_to"] else None,
    )
    return BiTemporal(
        window=window,
        recorded_at=datetime.fromisoformat(data["recorded_at"]),
        invalidated_at=datetime.fromisoformat(data["invalidated_at"])
        if data["invalidated_at"] else None,
    )


def _serialize_source(s: SourceRecord) -> dict[str, Any]:
    return {
        "kind": s.kind.value,
        "identifier": s.identifier,
        "captured_at": s.captured_at.isoformat(),
        "confidence": s.confidence,
        "author": s.author,
        "version": s.version,
        "metadata": s.metadata,
    }


def _deserialize_source(data: dict[str, Any]) -> SourceRecord:
    return SourceRecord(
        kind=SourceKind(data["kind"]),
        identifier=data["identifier"],
        captured_at=datetime.fromisoformat(data["captured_at"]),
        confidence=float(data["confidence"]),
        author=data.get("author"),
        version=data.get("version"),
        metadata=dict(data.get("metadata", {})),
    )


def _top_n_tags(tag_index: dict[str, set[str]], n: int) -> list[tuple[str, int]]:
    ranked = sorted(tag_index.items(), key=lambda kv: len(kv[1]), reverse=True)
    return [(tag, len(ids)) for tag, ids in ranked[:n]]
