"""Kernel do ArnaldAI — coordena o pipeline intent-to-execution."""

from .classify import RequestComplexity, classify_request
from .kernel import ArnaldoKernel
from .plasticity import apply_post_run_plasticity
from .retrieval import RetrievalResult, retrieve_for_request
from .thinking import ThinkingEmitter, ThinkingEvent, ThinkingKind

__all__ = [
    "ArnaldoKernel",
    "RequestComplexity",
    "RetrievalResult",
    "ThinkingEmitter",
    "ThinkingEvent",
    "ThinkingKind",
    "apply_post_run_plasticity",
    "classify_request",
    "retrieve_for_request",
]
