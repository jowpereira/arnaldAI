"""Capability time.current — horário atual sem rede (stdlib-only)."""

from __future__ import annotations

from datetime import datetime, timezone as _utc_tz
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    ZoneInfo = None  # type: ignore[assignment,misc]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]

from arnaldo.capabilities.base import CapabilityResult, make_source, timed_execution

_UTC_ALIASES = frozenset({"utc", "gmt", "z"})


def _resolve_tz(name: str) -> _utc_tz | ZoneInfo | None:  # type: ignore[valid-type]
    """Resolve timezone name para objeto tz, com tratamento robusto para UTC."""
    if name.lower() in _UTC_ALIASES:
        return _utc_tz.utc
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError):
        return None


class TimeCurrentCapability:
    """Retorna horário atual em qualquer timezone — stdlib, sem rede."""

    capability_id = "time.current"

    def describe(self) -> str:
        return "retornar data e hora atual em qualquer fuso horário"

    @timed_execution
    def execute(self, params: dict[str, Any]) -> CapabilityResult:
        tz_name = str(params.get("timezone", "UTC")).strip()
        tz = _resolve_tz(tz_name)
        if tz is None:
            return CapabilityResult(
                success=False,
                data=None,
                source=make_source("time.current"),
                error=f"Timezone '{tz_name}' não encontrado",
            )
        now = datetime.now(tz)
        return CapabilityResult(
            success=True,
            data={
                "timezone": tz_name,
                "datetime_iso": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "utc_offset": str(now.utcoffset()),
            },
            source=make_source(f"time.current:{tz_name}"),
        )
