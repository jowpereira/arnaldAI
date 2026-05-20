from __future__ import annotations

import unittest

from arnaldo.components.adaptive_planner import (
    compose_turn_request,
    infer_learning_updates,
    infer_objectives,
)
from arnaldo.session import SessionState


class AdaptivePlannerTest(unittest.TestCase):
    def _session(self) -> SessionState:
        return SessionState(
            version="session/v0",
            id="sessao_teste",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            autonomy_mode="assistido",
            terms_accepted=False,
            governance_profile="guarded",
            turns=3,
            active_objectives=[
                {
                    "id": "objective_1",
                    "statement": "analisar relatorio pendente",
                    "status": "active",
                }
            ],
            learned_preferences={},
            tool_history=[],
        )

    def test_infer_objectives_skips_plain_chat_turn(self) -> None:
        self.assertEqual(infer_objectives("oi"), [])
        self.assertEqual(infer_objectives("quem sou eu?"), [])

    def test_infer_objectives_keeps_explicit_work_request(self) -> None:
        objectives = infer_objectives("quero um plano de arquitetura para o runtime")
        self.assertEqual(objectives, ["um plano de arquitetura para o runtime"])

    def test_compose_turn_request_appends_session_context_when_available(self) -> None:
        session = self._session()
        compiled = compose_turn_request("meu nome e jonathan", session, inferred_objectives=[])
        self.assertIn("meu nome e jonathan", compiled)
        self.assertIn("contexto_objetivos_ativos:", compiled)

    def test_infer_learning_updates_extracts_user_name(self) -> None:
        updates = infer_learning_updates("meu nome e jonathan")
        self.assertEqual(updates.get("user_name"), "Jonathan")

    def test_infer_learning_updates_extracts_user_name_from_me_chama_assim(self) -> None:
        updates = infer_learning_updates("jonathan, me chama assim")
        self.assertEqual(updates.get("user_name"), "Jonathan")


if __name__ == "__main__":
    unittest.main()
