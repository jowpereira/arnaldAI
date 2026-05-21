"""Métricas do pipeline — latência, plasticidade e custos."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Generator


@dataclass
class PipelineMetrics:
    """Métricas coletadas durante uma execução do pipeline."""

    # Latência por fase (em ms)
    phase_latencies: Dict[str, float] = field(default_factory=dict)

    # Plasticidade
    synapses_updated: int = 0
    synapses_consolidated: int = 0
    inhibits_created: int = 0
    decay_applied: int = 0

    # Custos LLM (estimativas)
    llm_calls: int = 0
    total_tokens_estimate: int = 0

    # Classificação
    request_complexity: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase_latencies_ms": self.phase_latencies,
            "plasticity": {
                "synapses_updated": self.synapses_updated,
                "synapses_consolidated": self.synapses_consolidated,
                "inhibits_created": self.inhibits_created,
                "decay_applied": self.decay_applied,
            },
            "llm": {
                "calls": self.llm_calls,
                "total_tokens_estimate": self.total_tokens_estimate,
            },
            "request_complexity": self.request_complexity,
            "total_latency_ms": sum(self.phase_latencies.values()),
        }


class MetricsCollector:
    """Coletor de métricas para o pipeline do kernel."""

    def __init__(self) -> None:
        self._metrics = PipelineMetrics()
        self._start_times: Dict[str, float] = {}

    @property
    def metrics(self) -> PipelineMetrics:
        return self._metrics

    @contextmanager
    def phase(self, name: str) -> Generator[None, None, None]:
        """Context manager que mede latência de uma fase."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._metrics.phase_latencies[name] = round(elapsed_ms, 2)

    def record_plasticity(self, report: Dict[str, Any]) -> None:
        self._metrics.synapses_updated += int(report.get("updated_synapses", 0))
        self._metrics.synapses_consolidated += int(report.get("consolidated", 0))
        self._metrics.inhibits_created += int(report.get("inhibits_created", 0))

    def record_llm_call(self, tokens: int = 0) -> None:
        self._metrics.llm_calls += 1
        self._metrics.total_tokens_estimate += tokens

    def record_decay(self, count: int) -> None:
        self._metrics.decay_applied += count

    def set_complexity(self, level: str) -> None:
        self._metrics.request_complexity = level
