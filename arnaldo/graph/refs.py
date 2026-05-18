"""Grafos referenciando grafos — hierarquia composicional.

Um ``GraphRef`` permite que um nó de um ``CognitiveGraph`` aponte para outro
``CognitiveGraph`` inteiro. Isso transforma a estrutura plana de um grafo único
em uma **hierarquia de grafos** — análoga a *Hierarchical Graph Networks*
(Battaglia et al., 2018) e à *Thousand Brains Theory* (Hawkins, 2021), onde
cada nó pode possuir uma sub-rede própria.

A motivação é tripla:

1. **Isolamento epistêmico.** Conhecimento específico de um agente fica em seu
   próprio sub-grafo, sem poluir o grafo pai.

2. **Composição sem cópia.** Múltiplos agentes podem referenciar o mesmo
   sub-grafo compartilhado (``SHARED``) — atualizações propagam, há
   versionamento via ``SNAPSHOT``.

3. **Federação.** Sub-grafos podem viver em outro processo/servidor (modo
   ``FEDERATED``), acessados apenas por *bridge_nodes* expostos. Permite
   composição cross-organização sem expor o grafo inteiro.

Modelo formal::

    GraphRef = ⟨ graph_id, uri, kind, bridge_nodes, attached_at, ref_strength ⟩
                ∈  ID × URI? × RefKind × P(ID) × Time × [0,1]

E cada nó ``n ∈ V`` pode carregar uma lista de ``GraphRef``::

    n.subgraph_refs : list[GraphRef]

Resolução é *lazy*: o sub-grafo só é carregado quando alguém o consulta
(``GraphRegistry.resolve(ref)``). Caches em memória amortizam carregamentos.

```
                ROOT GRAPH
                    │
        ┌───────────┼──────────────────┐
        │           │                  │
   synapse_A   synapse_B          memory_C
        │           │                  │
        │ OWNED     │ SHARED       (sem ref)
        ▼           ▼
   sub-grafo    sub-grafo
   (privado)    (compartilhado
                 com outros nós)
```

Apenas ``OWNED`` e ``SHARED`` são implementados na Fase 2. ``FEDERATED`` e
``SNAPSHOT`` ficam para Fase 4 (precisam de protocolo A2A funcionando para
``FEDERATED`` e versionamento de schema para ``SNAPSHOT``).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from .temporal import utc_now

if TYPE_CHECKING:
    from .store import CognitiveGraph


# ────────────────────────────────────────────────────────────────────────────
# Taxonomia de referência
# ────────────────────────────────────────────────────────────────────────────


class GraphRefKind(str, Enum):
    """Semântica da relação entre o nó-pai e o sub-grafo referenciado."""

    OWNED = "owned"
    """O nó-pai é dono exclusivo do sub-grafo.

    Ao deletar o nó-pai, o sub-grafo também é removido (composição forte —
    análogo a *UML aggregation* com propagação de delete). Apenas um nó pode
    ser ``OWNED``-owner de um determinado sub-grafo.
    """

    SHARED = "shared"
    """Múltiplos nós podem referenciar o mesmo sub-grafo.

    O sub-grafo persiste enquanto houver ≥ 1 referência ativa. Útil para
    bases de conhecimento compartilhadas entre vários agentes especialistas.
    """

    FEDERATED = "federated"
    """Sub-grafo vive em servidor remoto (acessado via A2A/MCP).

    Apenas os ``bridge_nodes`` listados são acessíveis — o resto do grafo
    permanece privado. **Não implementado na Fase 2** — requer protocolo A2A
    funcional.
    """

    SNAPSHOT = "snapshot"
    """Cópia imutável e versionada do sub-grafo num instante t.

    Auditoria e reprodutibilidade: decisões antigas podem ser re-rodadas
    exatamente. **Não implementado na Fase 2** — requer versionamento de
    schema.
    """

    @property
    def is_implemented(self) -> bool:
        """Indica se o tipo está suportado nesta fase do projeto."""
        return self in {GraphRefKind.OWNED, GraphRefKind.SHARED}

    @property
    def allows_mutation(self) -> bool:
        """SNAPSHOT é read-only por design."""
        return self != GraphRefKind.SNAPSHOT


# ────────────────────────────────────────────────────────────────────────────
# GraphRef — referência tipada para outro grafo
# ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class GraphRef:
    """Referência tipada a outro ``CognitiveGraph``.

    Atributos:
        graph_id:       ID estável (UUID hex) do sub-grafo referenciado.
        kind:           Tipo da relação — define semântica e ciclo-de-vida.
        uri:            Caminho persistido (path local) ou URL remota (A2A).
                        ``None`` se o grafo é puramente em-memória.
        bridge_nodes:   IDs de nós do sub-grafo que são "interface pública".
                        Em modo FEDERATED, apenas esses são acessíveis.
                        Em OWNED/SHARED, define ponto-de-entrada preferencial.
        attached_at:    Quando a referência foi criada (transaction time).
        ref_strength:   Peso da aresta de referência ∈ [0,1].
                        Sujeito a plasticidade — referências bem-sucedidas
                        ganham peso; falhas perdem.

    Plasticidade de referência: o peso ``ref_strength`` reflete a utilidade
    histórica de invocar este sub-grafo a partir do nó-pai. Aplicada via
    ``PlasticityEngine.update_edge``-like, mas no escopo do ``GraphRef``
    (não cria aresta no grafo principal — fica como metadado do nó-pai).
    """

    graph_id: str
    kind: GraphRefKind
    uri: str | None = None
    bridge_nodes: tuple[str, ...] = field(default_factory=tuple)
    attached_at: datetime = field(default_factory=utc_now)
    ref_strength: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.ref_strength <= 1.0:
            raise ValueError(
                f"ref_strength deve ∈ [0,1], recebido {self.ref_strength}"
            )
        if not self.kind.is_implemented:
            raise NotImplementedError(
                f"GraphRefKind.{self.kind.name} ainda não implementado nesta fase. "
                f"Use {GraphRefKind.OWNED.name} ou {GraphRefKind.SHARED.name}."
            )

    def with_strength(self, new_strength: float) -> GraphRef:
        """Retorna nova GraphRef com strength clipado em [0,1]."""
        clipped = max(0.0, min(1.0, new_strength))
        return replace(self, ref_strength=clipped)

    def __repr__(self) -> str:  # pragma: no cover
        bridges = ",".join(self.bridge_nodes[:3])
        if len(self.bridge_nodes) > 3:
            bridges += f",... (+{len(self.bridge_nodes) - 3})"
        return (
            f"<GraphRef {self.kind.value} → {self.graph_id[:8]} "
            f"strength={self.ref_strength:.2f} bridges=[{bridges}]>"
        )


# ────────────────────────────────────────────────────────────────────────────
# GraphRegistry — catálogo de grafos conhecidos
# ────────────────────────────────────────────────────────────────────────────


class GraphCycleError(ValueError):
    """Anexar este sub-grafo criaria um ciclo na hierarquia."""


class GraphRegistry:
    """Catálogo central de ``CognitiveGraph`` referenciados.

    Responsabilidades:

    1. **Identidade.** Cada grafo registrado recebe ``graph_id`` único.
    2. **Resolução.** Mapeia ``GraphRef → CognitiveGraph`` (lazy: carrega do
       disco se necessário).
    3. **Ownership.** Rastreia qual nó é "dono" de cada sub-grafo ``OWNED``.
    4. **Cycle detection.** Impede que A referencie B que referencia A.
    5. **Garbage collection.** Sub-grafos ``OWNED`` órfãos podem ser purgados.

    Não é thread-safe — assume orquestrador único (kernel). Para multi-tenant,
    instanciar um ``GraphRegistry`` por tenant.
    """

    def __init__(self, *, base_path: Path | None = None) -> None:
        self._graphs: dict[str, CognitiveGraph] = {}
        self._paths: dict[str, Path] = {}
        # owner_key = f"{parent_graph_id}::{node_id}"  → child_graph_id
        self._owners: dict[str, str] = {}
        # Para SHARED: contagem de referências a cada graph_id
        self._refcounts: dict[str, int] = {}
        self._base_path = base_path

    # ── Registration ────────────────────────────────────────────────────

    def register(
        self,
        graph: CognitiveGraph,
        *,
        graph_id: str | None = None,
        uri: Path | None = None,
    ) -> str:
        """Registra um grafo. Atribui ``graph_id`` se ausente.

        Args:
            graph:    instância a registrar.
            graph_id: id pré-existente (para load); se ``None``, gera UUID.
            uri:      caminho persistido (para resolução pós-restart).

        Returns:
            ``graph_id`` registrado.
        """
        gid = graph_id or graph.graph_id or _new_graph_id()
        graph._bind_graph_id(gid)
        graph._bind_registry(self)
        self._graphs[gid] = graph
        if uri is not None:
            self._paths[gid] = Path(uri)
        self._refcounts.setdefault(gid, 0)
        return gid

    def unregister(self, graph_id: str) -> None:
        """Remove um grafo do registro (sem garantia de cleanup de filhos)."""
        self._graphs.pop(graph_id, None)
        self._paths.pop(graph_id, None)
        self._owners.pop(graph_id, None)
        self._refcounts.pop(graph_id, None)

    # ── Resolution ───────────────────────────────────────────────────────

    def resolve(self, ref: GraphRef) -> CognitiveGraph | None:
        """Resolve ``GraphRef`` → ``CognitiveGraph``.

        Estratégia:
        1. Se já em memória, retorna direto.
        2. Se há ``uri``, carrega do disco e cacheia.
        3. Caso contrário, retorna ``None`` (referência morta).
        """
        if ref.graph_id in self._graphs:
            return self._graphs[ref.graph_id]
        # Lazy load
        from .store import CognitiveGraph  # import tardio para evitar ciclo

        uri = ref.uri or (self._paths.get(ref.graph_id))
        if uri is None:
            return None
        try:
            cog = CognitiveGraph.load(Path(uri), registry=self)
            self._graphs[ref.graph_id] = cog
            return cog
        except (FileNotFoundError, ValueError):
            return None

    def get(self, graph_id: str) -> CognitiveGraph | None:
        """Lookup direto por ``graph_id``."""
        return self._graphs.get(graph_id)

    # ── Ownership tracking ───────────────────────────────────────────────

    def mark_owned(
        self,
        *,
        parent_graph_id: str,
        parent_node_id: str,
        child_graph_id: str,
    ) -> None:
        """Registra relação de ownership OWNED.

        Raises:
            GraphCycleError: se anexar criaria ciclo.
            ValueError: se sub-grafo já tem dono (OWNED é exclusivo).
        """
        if self._would_create_cycle(parent_graph_id, child_graph_id):
            raise GraphCycleError(
                f"Anexar {child_graph_id} sob {parent_graph_id} cria ciclo"
            )
        if child_graph_id in self._owners.values():
            raise ValueError(
                f"Sub-grafo {child_graph_id} já possui dono OWNED"
            )
        key = f"{parent_graph_id}::{parent_node_id}"
        self._owners[key] = child_graph_id

    def incr_refcount(self, graph_id: str) -> int:
        """Incrementa refcount (para tracking de SHARED)."""
        self._refcounts[graph_id] = self._refcounts.get(graph_id, 0) + 1
        return self._refcounts[graph_id]

    def decr_refcount(self, graph_id: str) -> int:
        """Decrementa refcount; retorna valor atual."""
        current = self._refcounts.get(graph_id, 0)
        new = max(0, current - 1)
        self._refcounts[graph_id] = new
        return new

    # ── Cycle detection ──────────────────────────────────────────────────

    def _would_create_cycle(
        self, parent_graph_id: str, child_graph_id: str
    ) -> bool:
        """Verifica se anexar ``child`` sob ``parent`` cria ciclo.

        Algoritmo: BFS a partir de ``child`` seguindo todas as ``GraphRef``;
        se alcançarmos ``parent``, há ciclo.

        Complexidade ``O(V_h + E_h)`` onde ``V_h, E_h`` são o tamanho da
        hierarquia atual.
        """
        if parent_graph_id == child_graph_id:
            return True
        visited: set[str] = set()
        stack = [child_graph_id]
        while stack:
            current = stack.pop()
            if current == parent_graph_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            child_graph = self._graphs.get(current)
            if child_graph is None:
                continue
            for node in child_graph.iter_nodes(active_only=False):
                for ref in node.subgraph_refs:
                    if ref.graph_id not in visited:
                        stack.append(ref.graph_id)
        return False

    # ── Garbage collection ───────────────────────────────────────────────

    def collect_orphan_owned(self) -> list[str]:
        """Remove sub-grafos OWNED cujo nó-pai não existe mais.

        Returns:
            Lista de ``graph_id`` removidos.
        """
        removed: list[str] = []
        for owner_key, child_id in list(self._owners.items()):
            parent_graph_id, _, parent_node_id = owner_key.partition("::")
            parent = self._graphs.get(parent_graph_id)
            if parent is None or parent.get_node(parent_node_id) is None:
                self._owners.pop(owner_key, None)
                self.unregister(child_id)
                removed.append(child_id)
        return removed

    # ── Diagnostics ──────────────────────────────────────────────────────

    def iter_graphs(self) -> Iterator[CognitiveGraph]:
        """Itera todos os grafos atualmente em memória."""
        yield from self._graphs.values()

    def stats(self) -> dict[str, int]:
        return {
            "graphs_in_memory": len(self._graphs),
            "persisted_paths": len(self._paths),
            "owned_subgraphs": len(self._owners),
            "shared_active": sum(1 for c in self._refcounts.values() if c > 1),
        }


def _new_graph_id() -> str:
    """Gera id único hexadecimal para um grafo."""
    return f"cog_{uuid.uuid4().hex}"
