from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from arnaldo.proactivity import ProactivityManager


class ProactivityManagerTest(unittest.TestCase):
    def test_schedule_and_pop_due_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProactivityManager(base_dir=Path(tmp))
            created = manager.schedule(
                session_id="sessao_a",
                message="Posso continuar daqui?",
                priority=0.8,
                delay_seconds=0,
            )
            self.assertTrue(created)

            due = manager.pop_due(session_id="sessao_a", limit=3)
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0]["status"], "delivered")
            self.assertEqual(due[0]["message"], "Posso continuar daqui?")
            self.assertEqual(manager.pending_count(session_id="sessao_a"), 0)

    def test_schedule_deduplicates_recent_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProactivityManager(base_dir=Path(tmp))
            first = manager.schedule(
                session_id="sessao_a",
                message="Retomo objetivo ativo?",
                delay_seconds=0,
            )
            second = manager.schedule(
                session_id="sessao_a",
                message="Retomo objetivo ativo?",
                delay_seconds=0,
            )
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(manager.pending_count(session_id="sessao_a"), 1)

    def test_schedule_from_run_skips_lightweight_chat_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProactivityManager(base_dir=Path(tmp))
            session = SimpleNamespace(
                id="sessao_chat",
                turns=1,
                learned_preferences={},
                active_objectives=[],
            )
            task = SimpleNamespace(
                goal={"type": "open_ended_execution"},
                context={"raw_request": "oi"},
                uncertainty=[{"question": "qual artefato final o usuario espera receber?"}],
            )
            adaptive_plan = SimpleNamespace(inferred_objectives=[])

            created = manager.schedule_from_run(
                session=session,
                task=task,
                adaptive_plan=adaptive_plan,
                run_id="run_1",
            )
            self.assertEqual(created, 0)
            self.assertEqual(manager.pending_count(session_id="sessao_chat"), 0)

    def test_schedule_from_run_creates_followups_for_uncertainty_and_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProactivityManager(base_dir=Path(tmp))
            session = SimpleNamespace(
                id="sessao_obj",
                turns=3,
                learned_preferences={"user_name": "Jonathan"},
                active_objectives=[{"status": "active", "statement": "validar memoria de sessao"}],
            )
            task = SimpleNamespace(
                goal={"type": "analyze_or_evaluate"},
                context={"raw_request": "analise o problema"},
                uncertainty=[{"question": "qual hipótese devemos testar primeiro?"}],
            )
            adaptive_plan = SimpleNamespace(
                inferred_objectives=["melhorar continuidade conversacional"]
            )

            created = manager.schedule_from_run(
                session=session,
                task=task,
                adaptive_plan=adaptive_plan,
                run_id="run_2",
            )
            self.assertGreaterEqual(created, 1)
            self.assertGreaterEqual(manager.pending_count(session_id="sessao_obj"), 1)

    def test_schedule_from_run_with_gap_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProactivityManager(base_dir=Path(tmp))
            session = SimpleNamespace(
                id="sessao_gap",
                turns=2,
                learned_preferences={},
                active_objectives=[],
            )
            task = SimpleNamespace(
                goal={"type": "analyze_or_evaluate", "statement": "pesquisa avançada"},
                context={"raw_request": "explique como funciona a computação quântica em detalhe"},
                uncertainty=[],
                gap_type="genuine",
            )
            adaptive_plan = SimpleNamespace(inferred_objectives=[])

            created = manager.schedule_from_run(
                session=session,
                task=task,
                adaptive_plan=adaptive_plan,
                run_id="run_gap",
            )
            self.assertGreaterEqual(created, 1)
            # Verifica que agendou mensagem de pesquisa (pending, ainda não due)
            self.assertGreaterEqual(manager.pending_count(session_id="sessao_gap"), 1)
            # Verifica conteúdo via load direto
            records = manager._load_records_locked("sessao_gap")
            research_msgs = [r for r in records if r.get("kind") == "research"]
            self.assertGreaterEqual(len(research_msgs), 1)
            self.assertIn("lacuna", research_msgs[0]["message"])


if __name__ == "__main__":
    unittest.main()
