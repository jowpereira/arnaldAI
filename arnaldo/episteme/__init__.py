"""Camada epistêmica — gaps, curiosidade, foraging."""

from .curiosity import CuriosityEngine
from .forager import ForagerPolicy, WebForager
from .gap_analyzer import DomainCoverage, EpistemicGapAnalyzer
from .ingester import KnowledgeIngester
from .signals import CuriositySignal, GapType, SignalStatus
from .entity_extraction import extract_entities

__all__ = [
    "CuriosityEngine",
    "CuriositySignal",
    "DomainCoverage",
    "EpistemicGapAnalyzer",
    "ForagerPolicy",
    "GapType",
    "KnowledgeIngester",
    "SignalStatus",
    "WebForager",
    "extract_entities",
]
