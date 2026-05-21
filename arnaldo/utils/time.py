"""Utilitários de tempo — fonte canônica para timestamps no ArnaldAI.

Duas formas canônicas:
- utc_now()     → datetime tz-aware (para graph/temporal)
- utc_now_iso() → str ISO-8601 (para contracts/IRs/serialização)
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timestamp UTC com tz-aware. Único timezone reference do sistema."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Timestamp UTC em formato ISO-8601 string."""
    return utc_now().isoformat()
