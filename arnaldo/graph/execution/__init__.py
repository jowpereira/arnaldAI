"""Execution engine — motor de execução de synapses no grafo cognitivo."""

from .context import StepContext, SynapseExecutionResult
from .engine import ExecutionEngine
from .routing import (
    dijkstra_weighted_path,
    find_best_execution_path,
    select_synapses_for_request,
)

__all__ = [
    "ExecutionEngine",
    "StepContext",
    "SynapseExecutionResult",
    "dijkstra_weighted_path",
    "find_best_execution_path",
    "select_synapses_for_request",
]
