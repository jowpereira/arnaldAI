"""Capabilities executáveis — as "mãos" do substrate cognitivo.

Cada capability implementa ``CapabilityBase`` e é registrada pelo
``capability_id`` (ex: ``search.public_web``, ``connector.http.generic``).
"""

from .base import CapabilityBase, CapabilityResult
from .catalog import CapabilityCatalog, CapabilityDescriptor, get_catalog
from .needs import CapabilityNeed, need_from_id, need_to_dict, needs_from_ids
from .registry import CapabilityExecutor

__all__ = [
    "CapabilityBase",
    "CapabilityCatalog",
    "CapabilityDescriptor",
    "CapabilityExecutor",
    "CapabilityNeed",
    "CapabilityResult",
    "get_catalog",
    "need_from_id",
    "need_to_dict",
    "needs_from_ids",
]
