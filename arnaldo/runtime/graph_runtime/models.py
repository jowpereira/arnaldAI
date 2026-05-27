"""Modelos de dados e constantes para o GraphRuntime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class IntentFrameOutput:
    goal: str
    goal_type: str
    constraints: list[str]
    evidence: list[str]
    uncertainties: list[str]


@dataclass
class WorkPlanOutput:
    steps: list[str]
    evidence: list[str]
    uncertainties: list[str]


@dataclass
class ArtifactDraftOutput:
    sections: list[str]
    evidence: list[str]
    uncertainties: list[str]


@dataclass
class CriticReviewOutput:
    status: str
    warnings: list[str]
    evidence: list[str]
    uncertainties: list[str]


@dataclass
class GenericStepOutput:
    status: str
    evidence: list[str]
    uncertainties: list[str]


ACTION_MODEL_MAP: dict[str, type[Any]] = {
    "frame_intent": IntentFrameOutput,
    "decompose_work": WorkPlanOutput,
    "explore_path_a": WorkPlanOutput,
    "explore_path_b": WorkPlanOutput,
    "clarify_uncertainties": WorkPlanOutput,
    "design_tooling": WorkPlanOutput,
    "stabilize_tooling": WorkPlanOutput,
    "execute_tooling": GenericStepOutput,
    "compose_tooling": WorkPlanOutput,
    "draft_artifact": ArtifactDraftOutput,
    "synthesize_artifact": ArtifactDraftOutput,
    "critic_review": CriticReviewOutput,
    "risk_review": CriticReviewOutput,
    "decision_synthesis": CriticReviewOutput,
}

ACTION_CAPABILITY_HINTS: dict[str, list[str]] = {
    "frame_intent": ["intent.structure"],
    "decompose_work": ["work.decompose"],
    "explore_path_a": ["work.decompose"],
    "explore_path_b": ["work.decompose"],
    "clarify_uncertainties": ["validation.critic_review"],
    "design_tooling": ["tool.dynamic.build", "connector.http.generic"],
    "stabilize_tooling": ["tool.dynamic.build", "connector.http.generic"],
    "execute_tooling": ["tool.dynamic.build", "connector.http.generic"],
    "compose_tooling": ["tool.dynamic.build", "connector.http.generic", "artifact.draft"],
    "draft_artifact": ["artifact.draft"],
    "synthesize_artifact": ["artifact.draft"],
    "critic_review": ["validation.critic_review"],
    "risk_review": ["validation.critic_review"],
    "decision_synthesis": ["validation.critic_review"],
}

ROLE_TIER_PREFERENCE: dict[str, str] = {
    "operator": "expert",
    "explorer": "expert",
    "synthesizer": "expert",
    "critic": "expert",
    "analyst": "expert",
}
