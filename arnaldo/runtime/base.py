from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable

if TYPE_CHECKING:
    from arnaldo.contracts import OrganizationIR, PolicyDecision, TaskIR
    from arnaldo.storage import RunStore


@dataclass
class RuntimeResult:
    artifact_path: Path
    step_results: Iterable[Dict[str, Any]]
    agent_bus_path: Path | None = None


@dataclass
class RuntimeContext:
    run_id: str
    task: TaskIR
    organization: OrganizationIR
    policy: PolicyDecision
    sandbox: Dict[str, Any] | None = None
    capability_resolution: Dict[str, Any] | None = None
    memory_hints: Dict[str, Any] | None = None


class RuntimeAdapter(ABC):
    """Interface abstrata para adaptadores de runtime."""

    @abstractmethod
    def run(self, context: RuntimeContext, store: RunStore) -> RuntimeResult:
        raise NotImplementedError
