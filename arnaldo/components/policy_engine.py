from __future__ import annotations

from arnaldo.contracts import OrganizationIR, PolicyDecision, TaskIR, new_id


class PolicyEngine:
    """Local policy gate for autonomy, side effects and missing approvals."""

    def evaluate(self, task: TaskIR, organization: OrganizationIR) -> PolicyDecision:
        approval_required = bool(organization.human_checkpoints)
        reasons = []
        if approval_required:
            reasons.append("organizacao contem checkpoint humano bloqueante")
        if task.constraints.get("external_side_effects") == "approval_required":
            reasons.append("efeitos externos permanecem bloqueados neste runtime")
        if not reasons:
            reasons.append("execucao local permitida")

        return PolicyDecision(
            version="policy-decision/v0",
            id=new_id("policy"),
            task_id=task.id,
            organization_id=organization.id,
            allowed=True,
            approval_required=approval_required,
            reasons=reasons,
            constraints={
                "network": "disabled_for_local_runtime",
                "filesystem": "write_only_run_directory",
                "external_messages": "blocked",
                "spend_money": "blocked",
            },
        )
