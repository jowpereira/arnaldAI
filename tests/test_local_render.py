from __future__ import annotations

from types import SimpleNamespace

from arnaldo.runtime.local_render import _derive_human_response, _derive_next_actions


def test_derive_human_response_prefers_primary_artifact_over_latest_critic_review() -> None:
    task = SimpleNamespace(goal={"statement": "Organizar runtime"})
    step_results = [
        {
            "output": "primary_artifact",
            "result": {
                "sections": [
                    "status: proposed_draft_pending_info",
                    "primary_artifact_outline: Plano de Arquitetura do Runtime",
                ],
                "evidence": ["Nova estrutura proposta com control-plane e data-plane."],
            },
        },
        {
            "output": "critic_review",
            "result": {
                "status": "revisions_required_pending_clarifications",
                "warnings": ["Há pontos a validar antes do rollout."],
            },
        },
    ]

    response = _derive_human_response(task, step_results)

    assert "Plano de Arquitetura do Runtime" in response
    assert "revisions_required_pending_clarifications" not in response


def test_derive_next_actions_prefers_review_uncertainties_when_available() -> None:
    step_results = [
        {
            "output": "primary_artifact",
            "result": {
                "sections": ["Plano principal"],
                "uncertainties": ["incerteza do artefato"],
            },
        },
        {
            "output": "critic_review",
            "result": {
                "status": "revisions_required",
                "uncertainties": [
                    "definir baseline atual",
                    "definir SLOs",
                ],
            },
        },
    ]

    next_actions = _derive_next_actions(step_results)

    assert "definir baseline atual" in next_actions
    assert "definir SLOs" in next_actions
