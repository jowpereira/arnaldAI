from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable


@dataclass
class RuntimeResult:
    artifact_path: Path
    step_results: Iterable[Dict[str, Any]]
    agent_bus_path: Path | None = None


@dataclass
class RuntimeContext:
    run_id: str
    task: Any
    organization: Any
    policy: Any
    sandbox: Dict[str, Any] | None = None
    capability_resolution: Dict[str, Any] | None = None


class RuntimeAdapter:
    """Interface minima para adaptadores de runtime."""

    def run(self, context: RuntimeContext, store: "RunStore") -> RuntimeResult:  # type: ignore[name-defined]
        raise NotImplementedError
