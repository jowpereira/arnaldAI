"""Modelo bi-temporal para o grafo cognitivo.

Inspirado em **Graphiti/Zep** (Rasmussen et al., 2025) e em bancos de dados
bi-temporais (Snodgrass, 1999).

Cada fato no grafo carrega duas linhas-do-tempo ortogonais:

* **Event time (T)** — quando o fato ocorreu (ou passou a valer) no mundo real.
* **Transaction time (T′)** — quando o sistema aprendeu (ou registrou) o fato.

Formalmente, um fato ``φ`` é representado pela tupla::

    φ = ⟨ payload, T_valid_from, T_valid_to, T'_created_at, T'_invalidated_at ⟩

Permite distinguir três classes de operação:

1. **Backfill**           — registrar agora algo que valia no passado.
2. **Forward-dated fact** — registrar agora algo que só valerá no futuro.
3. **Retroactive update** — invalidar um fato antigo com nova evidência,
   preservando a linha-do-tempo de transação para auditoria.

Sem isso, contradições no grafo (ex.: "A é manager" vs "A foi promovido a
diretor") destroem informação em vez de coexistirem com janelas distintas.

```
              T (event time)  ──────────────────────────────────►
                              ●═════════════════════●
                              │ valid_from          │ valid_to
                              │                     │
              T' (txn time)   ●═════════════════════●
                              │ created_at          │ invalidated_at
                              ▼                     ▼
                          aprendeu          esqueceu/sobreescreveu
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from arnaldo.utils.time import utc_now  # noqa: F401 — re-export canônico


@dataclass(frozen=True, slots=True)
class ValidityWindow:
    """Janela ``[valid_from, valid_to)`` no eixo do **event time** (T).

    Semântica:
        * ``valid_from`` — instante em que o fato passou a ser verdadeiro.
        * ``valid_to`` — instante em que deixou de ser; ``None`` = ainda válido.

    Invariante: ``valid_to is None or valid_to > valid_from``.

    Métodos puros (frozen dataclass) — toda mutação retorna nova instância.
    """

    valid_from: datetime
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError(
                f"valid_to ({self.valid_to}) deve ser > valid_from ({self.valid_from})"
            )

    @classmethod
    def open_at(cls, instant: datetime) -> Self:
        """Janela aberta — fato válido a partir de ``instant`` sem expiração."""
        return cls(valid_from=instant, valid_to=None)

    @classmethod
    def from_now(cls) -> Self:
        """Conveniência — janela aberta começando agora."""
        return cls.open_at(utc_now())

    def is_valid_at(self, instant: datetime) -> bool:
        """Retorna True se o fato está vigente em ``instant``."""
        if instant < self.valid_from:
            return False
        if self.valid_to is None:
            return True
        return instant < self.valid_to

    def overlaps(self, other: ValidityWindow) -> bool:
        """Duas janelas se sobrepõem se ∃ instante válido em ambas.

        Útil para detectar contradições temporais entre fatos sobre a mesma
        entidade-propriedade.
        """
        # self começa depois do fim de other?
        if other.valid_to is not None and self.valid_from >= other.valid_to:
            return False
        # other começa depois do fim de self?
        if self.valid_to is not None and other.valid_from >= self.valid_to:
            return False
        return True

    def closed_at(self, instant: datetime) -> ValidityWindow:
        """Retorna nova janela com ``valid_to`` definido (encerra a vigência)."""
        if instant <= self.valid_from:
            raise ValueError(
                f"Instante de fechamento ({instant}) precede valid_from ({self.valid_from})"
            )
        return ValidityWindow(valid_from=self.valid_from, valid_to=instant)


@dataclass(frozen=True, slots=True)
class BiTemporal:
    """Tupla bi-temporal completa.

    Combina ``ValidityWindow`` (event time T) com timestamps de transação
    ``T′`` que registram a observação do sistema.

    Auditoria responde a duas perguntas distintas:
        * "Quando o fato passou a valer?" → ``window.valid_from``
        * "Quando o sistema soube disso?" → ``recorded_at``

    Essas perguntas têm respostas diferentes em backfills e correções
    retroativas — é o que torna o modelo bi-temporal essencial em domínios
    auditáveis (finanças, saúde, governo).
    """

    window: ValidityWindow
    recorded_at: datetime = field(default_factory=utc_now)
    invalidated_at: datetime | None = None

    @classmethod
    def now(cls) -> Self:
        """Conveniência — válido agora, registrado agora, não invalidado."""
        return cls(window=ValidityWindow.from_now())

    @property
    def is_active(self) -> bool:
        """Não foi invalidado na linha-do-tempo transacional."""
        return self.invalidated_at is None

    def invalidate(self, at: datetime | None = None) -> BiTemporal:
        """Marca o fato como invalidado em ``T′`` (auditoria preservada).

        O fato continua acessível para queries históricas, mas não aparece em
        retrievals padrão.
        """
        if not self.is_active:
            return self  # idempotente
        return BiTemporal(
            window=self.window,
            recorded_at=self.recorded_at,
            invalidated_at=at or utc_now(),
        )

    def age_seconds(self, at: datetime | None = None) -> float:
        """Idade do fato em segundos, baseada em ``valid_from``."""
        reference = at or utc_now()
        return max(0.0, (reference - self.window.valid_from).total_seconds())

    def transactional_age_seconds(self, at: datetime | None = None) -> float:
        """Idade desde ``recorded_at`` — usado por políticas de cache."""
        reference = at or utc_now()
        return max(0.0, (reference - self.recorded_at).total_seconds())
