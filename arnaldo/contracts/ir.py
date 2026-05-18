from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return "%s_%s" % (prefix, uuid.uuid4().hex[:12])


def to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value


@dataclass
class IntentIR:
    version: str
    id: str
    created_at: str
    original_request: str
    desired_state: str
    primary_goal: str
    autonomy: Dict[str, Any]
    constraints: Dict[str, Any]
    inferred_requirements: List[str]
    open_questions: List[str]
    signals: Dict[str, Any]


@dataclass
class TaskIR:
    version: str
    id: str
    created_at: str
    intent_id: str
    goal: Dict[str, Any]
    context: Dict[str, Any]
    constraints: Dict[str, Any]
    deliverables: List[Dict[str, Any]]
    success_criteria: List[Dict[str, Any]]
    autonomy: Dict[str, Any]
    risk: Dict[str, Any]
    capability_needs: List[Dict[str, Any]]
    uncertainty: List[Dict[str, Any]]


@dataclass
class CognitiveDecision:
    version: str
    id: str
    task_id: str
    ambiguity: str
    reversibility: str
    external_impact: str
    data_sensitivity: str
    required_confidence: str
    selected_modes: List[str]
    rejected_modes: List[Dict[str, str]]
    budget: Dict[str, Any]
    stop_conditions: List[str]


@dataclass
class Capability:
    id: str
    name: str
    description: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    risk: Dict[str, Any]
    policies: Dict[str, Any]


@dataclass
class AgentGenome:
    id: str
    species: str
    role: str
    objective: str
    epistemic_style: str
    required_capabilities: List[str]
    forbidden_capabilities: List[str]
    output_contract: Dict[str, Any]
    validation: Dict[str, Any]
    lifecycle: Dict[str, Any]


@dataclass
class OrganizationIR:
    version: str
    id: str
    created_at: str
    task_id: str
    topology: str
    agents: List[AgentGenome]
    workflow: List[Dict[str, Any]]
    required_capabilities: List[str]
    human_checkpoints: List[Dict[str, Any]]
    communication_plan: Dict[str, Any] | None = None


@dataclass
class PolicyDecision:
    version: str
    id: str
    task_id: str
    organization_id: str
    allowed: bool
    approval_required: bool
    reasons: List[str]
    constraints: Dict[str, Any]
    escalation_plan: Dict[str, Any]
    notes: List[str]
    telemetry: Dict[str, Any]


@dataclass
class RuntimeEvent:
    id: str
    run_id: str
    created_at: str
    event_type: str
    payload: Dict[str, Any]


@dataclass
class EvidenceRecord:
    id: str
    run_id: str
    task_id: str
    created_at: str
    record_type: str
    summary: str
    payload: Dict[str, Any]


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    files: Dict[str, Path]
    session_id: str | None = None
