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

Todos os modos estão disponíveis de forma pragmática:

* ``OWNED`` / ``SHARED``: resolução local em memória/disco.
* ``FEDERATED``: resolução read-only a partir de URI local (ex.: ``file://``).
* ``SNAPSHOT``: resolução read-only de cópia persistida e imutável.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Iterator
from urllib.parse import unquote, urlparse

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
    permanece privado. Nesta implementação, a resolução é pragmática via URI
    local (``file://`` ou path), em modo read-only.
    """

    SNAPSHOT = "snapshot"
    """Cópia imutável e versionada do sub-grafo num instante t.

    Auditoria e reprodutibilidade: decisões antigas podem ser re-rodadas
    exatamente. Snapshot é resolvido em modo read-only.
    """

    @property
    def is_implemented(self) -> bool:
        """Indica se o tipo está suportado nesta fase do projeto."""
        return True

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
            raise ValueError(f"ref_strength deve ∈ [0,1], recebido {self.ref_strength}")
        if self.kind in {GraphRefKind.FEDERATED, GraphRefKind.SNAPSHOT}:
            if not (self.uri and str(self.uri).strip()):
                raise ValueError(
                    f"GraphRefKind.{self.kind.name} exige uri para resolução lazy/read-only."
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


# Re-export para compatibilidade — uso externo continua via refs
from .registry import GraphCycleError, GraphRegistry, _new_graph_id  # noqa: F401
