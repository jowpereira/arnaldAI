from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from arnaldo.contracts import OrganizationIR, PolicyDecision, TaskIR, new_id


class PolicyEngine:
    """Local policy gate for autonomy, side effects and missing approvals."""

    def evaluate(
        self,
        task: TaskIR,
        organization: OrganizationIR,
        session: Dict[str, Any] | None = None,
    ) -> PolicyDecision:
        session = session or {}
        autonomy_mode = task.autonomy.get("mode", "assistido")
        terms_accepted = bool(session.get("terms_accepted", False))
        governance_profile = session.get("governance_profile", "guarded")
        self_managed = terms_accepted and governance_profile == "self_managed"

        approval_required = bool(organization.human_checkpoints) and not self_managed
        reasons = []

        constraints = self._build_constraints(autonomy_mode, self_managed)

        if approval_required:
            reasons.append("organizacao contem checkpoint humano bloqueante")
        if autonomy_mode == "manual":
            reasons.append("modo manual exige aprovacao a cada etapa")
        if (
            task.constraints.get("external_side_effects") == "approval_required"
            and not self_managed
        ):
            reasons.append("efeitos externos permanecem bloqueados neste runtime")
        if self_managed:
            reasons.append("termos aceitos: autonomia ampliada com intervencao minima")
        if not reasons:
            reasons.append("execucao local permitida")

        escalation_plan = self._build_escalation_plan(
            approval_required, autonomy_mode, self_managed
        )

        telemetry = {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "autonomy_mode": autonomy_mode,
            "checkpoint_count": len(organization.human_checkpoints),
            "terms_accepted": terms_accepted,
            "governance_profile": governance_profile,
            "self_managed": self_managed,
        }

        return PolicyDecision(
            version="policy-decision/v0",
            id=new_id("policy"),
            task_id=task.id,
            organization_id=organization.id,
            allowed=True,
            approval_required=approval_required,
            reasons=reasons,
            constraints=constraints,
            escalation_plan=escalation_plan,
            notes=[],
            telemetry=telemetry,
        )

    def _build_constraints(self, autonomy_mode: str, self_managed: bool) -> Dict[str, str]:
        if self_managed:
            return {
                "network": "read_write",
                "filesystem": "workspace_write",
                "external_messages": "allowed",
                "spend_money": "blocked_unless_budget_defined",
                "unsafe_actions": "blocked",
            }
        return {
            "network": "read" if autonomy_mode != "manual" else "disabled",
            "filesystem": "write_run_directory_only",
            "external_messages": "blocked",
            "spend_money": "blocked",
        }

    def _build_escalation_plan(
        self, approval_required: bool, autonomy_mode: str, self_managed: bool
    ) -> Dict[str, Any]:
        if self_managed:
            return {
                "contact": "human_on_demand",
                "channels": ["cli"],
                "timeout_minutes": 240,
            }
        if autonomy_mode == "manual" or approval_required:
            return {
                "contact": "human_operator",
                "channels": ["cli"],
                "timeout_minutes": 15,
            }
        if autonomy_mode == "assistido":
            return {
                "contact": "human_operator",
                "channels": ["cli"],
                "timeout_minutes": 60,
            }
        return {
            "contact": "human_on_call",
            "channels": ["cli"],
            "timeout_minutes": 120,
        }
