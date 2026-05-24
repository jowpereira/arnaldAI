from __future__ import annotations

from typing import Any, Dict, List

from arnaldo.contracts import IntentIR, TaskIR, new_id, utc_now


class TaskCompiler:
    """Builds a versioned Task IR without binding the system to a fixed subject area."""

    def compile(
        self,
        intent: IntentIR,
        retrieval: Any = None,
        *,
        extra_capability_needs: List[str] | None = None,
    ) -> TaskIR:
        # Enriquece contexto com retrieval quando disponível
        context_enrichment: Dict[str, Any] = {}
        if retrieval is not None and hasattr(retrieval, "has_context") and retrieval.has_context:
            context_enrichment = {
                "retrieved_memories": len(retrieval.relevant_memories),
                "retrieved_synapses": len(retrieval.relevant_synapses),
                "inhibited_synapses": retrieval.inhibited_synapses[:5],
            }

        task_context: Dict[str, Any] = {
            "source": "cli",
            "scope": "generic",
            "original_request": intent.original_request,
        }
        if context_enrichment:
            task_context["retrieval"] = context_enrichment

        return TaskIR(
            version="task-ir/v0",
            id=new_id("task"),
            created_at=utc_now(),
            intent_id=intent.id,
            goal={
                "statement": intent.desired_state,
                "type": intent.primary_goal,
            },
            context=task_context,
            constraints=intent.constraints,
            deliverables=build_deliverables(intent),
            success_criteria=[
                {
                    "id": "actionable",
                    "description": "a entrega deve permitir uma proxima acao clara",
                },
                {
                    "id": "evidence_marked",
                    "description": "decisoes e premissas relevantes devem deixar rastro",
                },
                {
                    "id": "uncertainty_marked",
                    "description": "lacunas devem ser explicitadas",
                },
            ],
            autonomy=intent.autonomy,
            risk=build_risk(intent.signals),
            capability_needs=build_capability_needs(extra_capability_needs),
            uncertainty=[
                {"question": question, "blocking": False} for question in intent.open_questions
            ],
        )


def build_deliverables(intent: IntentIR) -> List[Dict[str, Any]]:
    return [
        {
            "id": "primary_artifact",
            "schema": "generic_work_artifact",
            "description": "artefato principal derivado da intencao",
        },
        {
            "id": "execution_evidence",
            "schema": "evidence_ledger",
            "description": "registro append-only de decisoes e execucao",
        },
        {
            "id": "next_actions",
            "schema": "action_backlog",
            "description": "proximos passos ordenados",
        },
    ]


def build_risk(signals: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "execution_risk": score_to_level(
            max(signals["ambiguity_score"], signals["external_impact_score"])
        ),
        "data_sensitivity": score_to_level(signals["data_sensitivity_score"]),
        "reversibility": "low" if signals["irreversibility_score"] > 0 else "high",
    }


def build_capability_needs(
    extra_needs: List[str] | None = None,
) -> List[Dict[str, Any]]:
    base = [
        {"id": "intent.structure", "required": True},
        {"id": "work.decompose", "required": True},
        {"id": "organization.generate", "required": True},
        {"id": "artifact.draft", "required": True},
        {"id": "validation.critic_review", "required": True},
        {"id": "evidence.record", "required": True},
    ]
    existing_ids = {item["id"] for item in base}
    for cap_id in extra_needs or []:
        if cap_id not in existing_ids:
            base.append({"id": cap_id, "required": True})
            existing_ids.add(cap_id)
    return base


def score_to_level(score: int) -> str:
    if score <= 0:
        return "low"
    if score == 1:
        return "medium"
    return "high"
