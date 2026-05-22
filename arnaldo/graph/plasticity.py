"""Plasticidade sináptica — atualização de pesos e decaimento temporal.

**Inspiração biológica:** três mecanismos co-existem em redes neurais reais
e são adaptados aqui ao grafo cognitivo simbólico:

1. **Long-Term Potentiation (LTP)** — co-ativação bem-sucedida aumenta peso
   (regra de Hebb, 1949: "cells that fire together wire together").

2. **Long-Term Depression (LTD)** — co-ativação mal-sucedida reduz peso.

3. **Decaimento temporal** — pesos não-reforçados decaem exponencialmente,
   modelados pela curva de esquecimento de Ebbinghaus (1885) com half-life
   *adaptativa por domínio* (Kim et al., 2024 — "Not All Memories Age the Same").

Decaimento uniforme produz NDCG@5 = 0.015 vs. 0.274 do semântico puro (Kim et al.,
2024). Por isso o sistema **rejeita decaimento uniforme** — toda regra é
indexada por ``domain``.

```
              Hebbian Update Rule (modulada por reward)
              ─────────────────────────────────────────

                  ∆w = η · (s − ½) · m(t)

              s ∈ {0,1}  : sucesso da ativação (1 = success, 0 = failure)
              η ∈ (0,1)  : learning rate
              m(t)       : modulação por co-ativação no tempo
                           m(t) = exp(−|∆t| / τ_LTP)
```

```
              Ebbinghaus Adaptive Decay
              ──────────────────────────

                  R(t) = R₀ · exp(−t / λ_domain)

              R₀         : confiança inicial
              λ_domain   : half-life * 1/ln(2) (constante de tempo)
              t          : tempo desde última ativação
```

A composição final: ``effective_weight(t) = base_weight · decay(t) · reputation``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np

from .temporal import utc_now

if TYPE_CHECKING:
    from .edges import GraphEdge
    from .nodes import GraphNode


# ────────────────────────────────────────────────────────────────────────────
# Funções estatísticas compartilhadas
# ────────────────────────────────────────────────────────────────────────────


def laplace_success_rate(successes: int, failures: int) -> float:
    """Razão de sucesso com Laplace smoothing — (s+1)/(s+f+2).

    Evita divisão por zero e dá prior neutro (0.5) quando sem dados.
    """
    total = successes + failures
    if total == 0:
        return 0.5
    return (successes + 1) / (total + 2)


# ────────────────────────────────────────────────────────────────────────────
# Políticas de decaimento (half-life por domínio)
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DecayPolicy:
    """Política de decaimento adaptativa por domínio.

    Cada domínio de conhecimento tem uma half-life apropriada. Constantes
    abaixo são defaults razoáveis — podem ser sobrescritas via construtor.

    Half-lives sugeridas (literatura + intuição operacional):

    +---------------------+------------+-------------------------------------+
    | Domínio             | Half-life  | Justificativa                       |
    +=====================+============+=====================================+
    | ``tech_news``       |   3 dias   | Notícias técnicas envelhecem rápido |
    | ``security``        |  72 horas  | CVEs são tempo-críticos             |
    | ``episodic``        |   7 dias   | Interações têm relevância curta     |
    | ``negative``        |  30 dias   | Erros conhecidos permanecem úteis   |
    | ``semantic_tech``   |  30 dias   | Frameworks/APIs mudam               |
    | ``capability``      |  90 dias   | Tools permanecem funcionais         |
    | ``semantic_stable`` | 180 dias   | Fatos gerais estáveis               |
    | ``procedural``      | 365 dias   | Skills aprendidas são duradouras    |
    +---------------------+------------+-------------------------------------+

    O sistema permite domínios customizados — qualquer string é aceita; o
    default (``__fallback__``) é aplicado quando não há regra explícita.
    """

    half_lives: dict[str, timedelta] = field(
        default_factory=lambda: {
            "tech_news": timedelta(days=3),
            "security": timedelta(hours=72),
            "episodic": timedelta(days=7),
            "negative": timedelta(days=30),
            "semantic_tech": timedelta(days=30),
            "capability": timedelta(days=90),
            "semantic_stable": timedelta(days=180),
            "factual": timedelta(days=180),
            "procedural": timedelta(days=365),
            "operational": timedelta(days=14),
            "__fallback__": timedelta(days=60),
        }
    )

    forget_threshold: float = 0.05
    """Abaixo deste peso efetivo, o nó é movido para status ``ARCHIVED``."""

    refresh_threshold: float = 0.30
    """Abaixo deste peso efetivo, o nó é marcado ``STALE`` (precisa re-foragem)."""

    def half_life_for(self, domain: str) -> timedelta:
        """Retorna half-life para um domínio, com fallback."""
        return self.half_lives.get(domain, self.half_lives["__fallback__"])

    def decay_factor(self, domain: str, elapsed: timedelta) -> float:
        """Retorna fator multiplicativo ``∈ (0,1]`` aplicado ao peso.

        Implementa ``R(t) = exp(−t·ln(2)/T_½)``, equivalente a meia-vida.

        Exemplo: domínio ``episodic`` (T½=7d), elapsed=14d → fator = 0.25
        (quatro half-lives consumidas, peso reduzido a 1/4).
        """
        half_life = self.half_life_for(domain)
        if half_life.total_seconds() <= 0:
            return 1.0
        decay_const = np.log(2.0) / half_life.total_seconds()
        return float(np.exp(-decay_const * max(0.0, elapsed.total_seconds())))


# ────────────────────────────────────────────────────────────────────────────
# Regra Hebbian (LTP/LTD)
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class HebbianRule:
    """Regra de atualização de pesos sinápticos.

    Implementa LTP/LTD modulado por sucesso de outcome:

        ∆w = η · ∆s,  onde ∆s = (success_rate − 0.5) · 2
                                                         ── ∈ [−1, +1]

    O sistema usa ``success_rate`` em vez de outcome binário porque suaviza
    flutuações iniciais (poucas amostras) via Laplace smoothing.

    Atributos:
        learning_rate: η ∈ (0,1). Default 0.10 — passos pequenos preferíveis
                       em sistemas online onde catastrophic plasticity é risco.
        cap_per_step:  ``|∆w|`` máximo por update (estabilidade).
        floor:         ``w`` mínimo (nó não some por LTD agressivo).
        ceiling:       ``w`` máximo (evita saturação).
    """

    learning_rate: float = 0.10
    cap_per_step: float = 0.15
    floor: float = 0.05
    ceiling: float = 0.99

    def update(self, current_weight: float, success_rate: float) -> float:
        """Aplica regra Hebbian, retorna novo peso clipado.

        Args:
            current_weight: ``w_t`` ∈ [0,1]
            success_rate:   p ∈ [0,1] — fração de sucessos observados.

        Returns:
            ``w_{t+1}`` ∈ [floor, ceiling]
        """
        delta = self.learning_rate * (success_rate - 0.5) * 2.0
        # cap
        delta = float(np.clip(delta, -self.cap_per_step, self.cap_per_step))
        new_weight = float(np.clip(current_weight + delta, self.floor, self.ceiling))
        return new_weight


# ────────────────────────────────────────────────────────────────────────────
# Motor unificado
# ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class PlasticityEngine:
    """Motor de plasticidade — aplica regras a nós e arestas.

    Pode ser injetado em ``CognitiveGraph`` ou usado standalone para testes.
    Stateless em relação aos pesos (lê do nó, retorna novo peso); o ``store``
    é responsável por persistir.

    Composição típica do peso efetivo::

        effective(node, t) = node.weight                          # plasticidade
                           · decay_policy.decay_factor(d, ∆t)     # tempo
                           · source.confidence                    # epistemologia
    """

    rule: HebbianRule = field(default_factory=HebbianRule)
    decay: DecayPolicy = field(default_factory=DecayPolicy)

    # ── Pesos efetivos ────────────────────────────────────────────────────

    def effective_weight(self, node: GraphNode, *, at: datetime | None = None) -> float:
        """Calcula o peso efetivo do nó no instante ``at`` (default = agora).

        Composição multiplicativa de três fatores ∈ [0,1] → resultado ∈ [0,1].
        """
        now = at or utc_now()
        # 1) Tempo desde última ativação (ou criação)
        ref = node.stats.last_activated_at or node.bitemp.window.valid_from
        elapsed = now - ref
        decay = self.decay.decay_factor(node.domain, elapsed)
        # 2) Confiança da fonte
        prov = node.source.confidence
        return float(node.weight * decay * prov)

    def effective_edge_weight(self, edge: GraphEdge, *, at: datetime | None = None) -> float:
        """Análogo para arestas. Usa domínio sintético baseado no tipo."""
        now = at or utc_now()
        ref = edge.last_activated_at or edge.bitemp.window.valid_from
        elapsed = now - ref
        domain = "procedural" if edge.kind.is_synaptic else "semantic_stable"
        decay = self.decay.decay_factor(domain, elapsed)
        return float(edge.weight * decay * edge.source.confidence)

    # ── Atualização Hebbian após uma run ─────────────────────────────────

    def update_node(self, node: GraphNode, *, success: bool) -> GraphNode:
        """Aplica Hebbian update após registrar outcome. Retorna nó atualizado.

        Pipeline::

            1. registra outcome no stats
            2. computa novo peso via HebbianRule(weight, success_rate)
            3. retorna nó com peso atualizado (imutável)
        """
        node.record_outcome(success)
        new_weight = self.rule.update(node.weight, node.stats.success_rate)
        return node.with_weight(new_weight)

    def update_edge(self, edge: GraphEdge, *, success: bool) -> GraphEdge:
        """Análogo para arestas sinápticas. Para tipos não-sinápticos, no-op."""
        edge.register_outcome(success)
        if not edge.kind.is_synaptic:
            return edge  # tipos hard (REQUIRES, FORBIDS) não são plásticos
        new_weight = self.rule.update(edge.weight, edge.success_rate)
        return edge.with_weight(new_weight)

    # ── Classificação por estado ─────────────────────────────────────────

    def classify_status(self, node: GraphNode, *, at: datetime | None = None) -> str:
        """Retorna ciclo-de-vida sugerido baseado no peso efetivo.

        Não muta o nó — apenas sugere. O ``CognitiveGraph`` é quem aplica.
        """
        eff = self.effective_weight(node, at=at)
        if eff < self.decay.forget_threshold:
            return "archived"
        if eff < self.decay.refresh_threshold:
            return "stale"
        if node.stats.activations >= 10 and node.stats.success_rate > 0.7:
            return "consolidated"
        if node.stats.activations > 0:
            return "active"
        return "candidate"
