"""Catálogo central de grafos referenciados — resolução, ownership, GC."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Iterator
from urllib.parse import unquote, urlparse

from .refs import GraphRef, GraphRefKind

if TYPE_CHECKING:
    from .store import CognitiveGraph


# ────────────────────────────────────────────────────────────────────────────
# Exceção
# ────────────────────────────────────────────────────────────────────────────


class GraphCycleError(ValueError):
    """Anexar este sub-grafo criaria um ciclo na hierarquia."""


# ────────────────────────────────────────────────────────────────────────────
# GraphRegistry — catálogo de grafos conhecidos
# ────────────────────────────────────────────────────────────────────────────


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
        self._paths: dict[str, str] = {}
        self._readonly_cache: dict[str, CognitiveGraph] = {}
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
        uri: Path | str | None = None,
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
            self._paths[gid] = str(uri)
        self._refcounts.setdefault(gid, 0)
        return gid

    def unregister(self, graph_id: str) -> None:
        """Remove um grafo do registro (sem garantia de cleanup de filhos)."""
        self._graphs.pop(graph_id, None)
        self._paths.pop(graph_id, None)
        for key in list(self._readonly_cache.keys()):
            if key.split("::", 1)[0] == graph_id:
                self._readonly_cache.pop(key, None)
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
        if ref.kind in {GraphRefKind.OWNED, GraphRefKind.SHARED} and ref.graph_id in self._graphs:
            return self._graphs[ref.graph_id]
        readonly = ref.kind in {GraphRefKind.FEDERATED, GraphRefKind.SNAPSHOT}
        readonly_key = f"{ref.graph_id}::{ref.kind.value}"
        if readonly and readonly_key in self._readonly_cache:
            return self._readonly_cache[readonly_key]
        # Lazy load
        from .store import CognitiveGraph  # import tardio para evitar ciclo

        uri = ref.uri or (self._paths.get(ref.graph_id))
        if uri is None:
            return None
        try:
            path = _uri_to_path(uri)
            if path is None:
                return None
            cog = CognitiveGraph.load(path, registry=self)
            if readonly:
                cog._set_read_only(True)
                self._readonly_cache[readonly_key] = cog
            else:
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
            raise GraphCycleError(f"Anexar {child_graph_id} sob {parent_graph_id} cria ciclo")
        if child_graph_id in self._owners.values():
            raise ValueError(f"Sub-grafo {child_graph_id} já possui dono OWNED")
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

    def _would_create_cycle(self, parent_graph_id: str, child_graph_id: str) -> bool:
        """Verifica se anexar ``child`` sob ``parent`` cria ciclo.

        Algoritmo: BFS a partir de ``child`` seguindo todas as ``GraphRef``;
        se alcançarmos ``parent``, há ciclo.
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
            "readonly_cached": len(self._readonly_cache),
            "owned_subgraphs": len(self._owners),
            "shared_active": sum(1 for c in self._refcounts.values() if c > 1),
        }


def _new_graph_id() -> str:
    """Gera id único hexadecimal para um grafo."""
    return f"cog_{uuid.uuid4().hex}"


def _uri_to_path(uri: str) -> Path | None:
    """Converte URI/path em ``Path`` local, suportando ``file://``.

    URIs HTTP(S) não são resolvidos nesta camada; retornam ``None`` para manter
    a resolução federada explicitamente local/read-only por enquanto.
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    # Windows absoluto ("C:\\path\\file") é parseado como scheme="c".
    if len(scheme) == 1 and len(uri) >= 2 and uri[1] == ":":
        return Path(uri)
    if scheme in {"http", "https"}:
        return None
    if scheme == "file":
        raw_path = unquote(parsed.path or "")
        if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
            raw_path = raw_path[1:]
        if not raw_path:
            return None
        return Path(raw_path)
    if scheme == "":
        return Path(uri)
    return None
