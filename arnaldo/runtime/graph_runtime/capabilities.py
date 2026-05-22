"""Gestão de capabilities para o GraphRuntime."""

from __future__ import annotations

from typing import Any, Dict

from arnaldo.graph import CapabilityNode, CognitiveGraph

from .infra import _slug


def _infer_capability_id_from_output(
    *,
    action: str,
    output: str,
    tooling_id_by_slug: Dict[str, str],
) -> str:
    output_lower = output.strip().lower()
    prefix = {
        "design_tooling": "tool_specs_",
        "stabilize_tooling": "tool_stability_",
        "execute_tooling": "tool_exec_",
    }.get(action, "")
    if not prefix or not output_lower.startswith(prefix):
        return ""
    slug = output_lower[len(prefix) :].strip("_")
    if not slug:
        return ""
    return tooling_id_by_slug.get(slug, "")


def _collect_tooling_targets(capability_resolution: Dict[str, Any]) -> Dict[str, list[str]]:
    missing: set[str] = set()
    degraded: set[str] = set()
    for item in capability_resolution.get("missing", []) or []:
        capability_id = str(item.get("id", "")).strip()
        if capability_id.startswith(("connector.", "tool.", "search.")):
            missing.add(capability_id)
    for item in capability_resolution.get("degraded", []) or []:
        capability_id = str(item.get("id", "")).strip()
        if capability_id.startswith(("connector.", "tool.", "search.")):
            degraded.add(capability_id)
    return {
        "missing": sorted(missing),
        "degraded": sorted(degraded),
    }


def _collect_tool_execution_targets(
    capability_resolution: Dict[str, Any],
) -> list[Dict[str, str]]:
    targets: dict[str, str] = {}
    for bucket in ("available", "degraded", "missing"):
        for item in capability_resolution.get(bucket, []) or []:
            capability_id = str(item.get("id", "")).strip()
            if not capability_id.startswith(("connector.", "tool.", "search.")):
                continue
            module_path = _capability_module_path(item)
            if not module_path:
                continue
            targets[capability_id] = module_path
    return [
        {"id": capability_id, "module_path": targets[capability_id]}
        for capability_id in sorted(targets.keys())
    ]


def _collect_workflow_tooling_capabilities(workflow: list[Dict[str, Any]]) -> set[str]:
    tooling_actions = {"design_tooling", "stabilize_tooling", "execute_tooling"}
    capabilities: set[str] = set()
    for item in workflow:
        action = str(item.get("action", "")).strip()
        if action not in tooling_actions:
            continue
        capability_id = str(item.get("capability_id", "")).strip()
        if capability_id:
            capabilities.add(capability_id)
    return capabilities


def _capability_module_path(item: Dict[str, Any]) -> str:
    direct = _normalize_module_path(item.get("module_path"))
    if direct:
        return direct
    policies = item.get("policies") or {}
    if isinstance(policies, dict):
        return _normalize_module_path(policies.get("module_path"))
    return ""


from arnaldo.utils.normalize import normalize_module_path as _normalize_module_path  # noqa: E402


def _collect_capability_state(
    task: Any,
    capability_resolution: Dict[str, Any],
    organization: Any,
) -> dict[str, dict[str, str]]:
    state_by_id: dict[str, dict[str, str]] = {}
    state_rank = {"missing": 0, "degraded": 1, "available": 2}

    def merge(capability_id: str, state: str, *, maturity: str | None = None) -> None:
        if not capability_id:
            return
        current = state_by_id.get(capability_id)
        if current is None or state_rank[state] > state_rank[current["state"]]:
            state_by_id[capability_id] = {"state": state}
        if maturity:
            bucket = state_by_id.setdefault(capability_id, {"state": state})
            existing_maturity = str(bucket.get("maturity", "")).strip()
            bucket["maturity"] = (
                maturity if not existing_maturity else _max_maturity(existing_maturity, maturity)
            )

    for item in task.capability_needs:
        capability_id = str(item.get("id", "")).strip()
        if not capability_id:
            continue
        inferred_state = "missing" if bool(item.get("required", True)) else "degraded"
        merge(capability_id, inferred_state)

    for item in capability_resolution.get("available", []) or []:
        capability_id = str(item.get("id", "")).strip()
        merge(capability_id, "available", maturity=_capability_maturity_hint(item))
    for item in capability_resolution.get("degraded", []) or []:
        capability_id = str(item.get("id", "")).strip()
        merge(capability_id, "degraded", maturity=_capability_maturity_hint(item))
    for item in capability_resolution.get("missing", []) or []:
        capability_id = str(item.get("id", "")).strip()
        merge(capability_id, "missing", maturity=_capability_maturity_hint(item))

    for capability_id in organization.required_capabilities:
        merge(str(capability_id).strip(), "missing")

    return {key: state_by_id[key] for key in sorted(state_by_id)}


def _capability_maturity_hint(item: Dict[str, Any]) -> str | None:
    direct = str(item.get("maturity", "")).strip()
    if direct:
        return direct
    policies = item.get("policies") or {}
    hinted = str(policies.get("maturity", "")).strip()
    return hinted or None


def _upsert_capability_node(
    graph: CognitiveGraph,
    capability_id: str,
    *,
    state: str,
    maturity_hint: str | None,
) -> CapabilityNode:
    node_id = f"cap_{_slug(capability_id)}"
    target_maturity = _resolve_capability_maturity(
        capability_id=capability_id,
        state=state,
        maturity_hint=maturity_hint,
    )
    existing = graph.get_node(node_id)
    if isinstance(existing, CapabilityNode):
        merged_maturity = _max_maturity(existing.maturity, target_maturity)
        updated = existing.with_payload_merge(
            maturity=merged_maturity,
            state=state,
            risk_level=_risk_level_for_state(state),
        )
        assert isinstance(updated, CapabilityNode)
        updated = updated.with_weight(_capability_weight_for_maturity(merged_maturity))
        assert isinstance(updated, CapabilityNode)
        graph.add_node(updated)
        return updated

    description = "Capability dinâmica observada no fluxo de execução (%s)" % state
    capability = CapabilityNode.tool(
        capability_id,
        id=node_id,
        description=description,
        maturity=target_maturity,
        risk_level=_risk_level_for_state(state),
        payload={"state": state},
    )
    graph.add_node(capability)
    return capability


def _resolve_capability_maturity(
    *,
    capability_id: str,
    state: str,
    maturity_hint: str | None,
) -> str:
    levels = set(CapabilityNode.MATURITY_LEVELS)
    hinted = str(maturity_hint or "").strip().lower()
    if hinted in levels:
        return hinted
    is_tooling = capability_id.startswith(("connector.", "tool."))
    if state == "available":
        return "tested" if is_tooling else "trusted"
    if state == "degraded":
        return "draft" if is_tooling else "tested"
    return "scaffolded" if is_tooling else "draft"


def _max_maturity(current: str, candidate: str) -> str:
    levels = list(CapabilityNode.MATURITY_LEVELS)
    current_idx = levels.index(current) if current in levels else 0
    candidate_idx = levels.index(candidate) if candidate in levels else 0
    if current == "deprecated":
        return current
    return levels[max(current_idx, candidate_idx)]


def _capability_weight_for_maturity(maturity: str) -> float:
    return {
        "scaffolded": 0.10,
        "draft": 0.25,
        "tested": 0.55,
        "trusted": 0.85,
        "deprecated": 0.05,
    }.get(maturity, 0.25)


def _risk_level_for_state(state: str) -> str:
    return {
        "available": "low",
        "degraded": "medium",
        "missing": "high",
    }.get(state, "medium")
