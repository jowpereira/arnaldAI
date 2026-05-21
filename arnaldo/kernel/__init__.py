"""Kernel do ArnaldAI — coordena o pipeline intent-to-execution."""

from .classify import RequestComplexity, classify_request
from .kernel import ArnaldoKernel
from .plasticity import apply_post_run_plasticity
from .retrieval import RetrievalResult, retrieve_for_request

__all__ = [
    "ArnaldoKernel",
    "RequestComplexity",
    "RetrievalResult",
    "apply_post_run_plasticity",
    "classify_request",
    "retrieve_for_request",
]
