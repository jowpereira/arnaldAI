"""Capabilities executáveis — as "mãos" do substrate cognitivo.

Cada capability implementa ``CapabilityBase`` e é registrada pelo
``capability_id`` (ex: ``search.public_web``, ``connector.http.generic``).
"""

from .base import CapabilityBase, CapabilityResult
from .registry import CapabilityExecutor

__all__ = ["CapabilityBase", "CapabilityResult", "CapabilityExecutor"]
