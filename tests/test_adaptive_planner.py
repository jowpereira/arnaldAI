from __future__ import annotations

import unittest

from arnaldo.components.adaptive_planner import (
    compose_turn_request,
    infer_capability_hints,
    infer_learning_updates,
    infer_objectives,
    should_forge,
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


# ── Testes de infer_capability_hints (descoberta local) ──────────────


def test_infer_hints_detects_ache_pasta() -> None:
    hints = infer_capability_hints("tenho o mt5 instalado ache a pasta")
    ids = {h["id"] for h in hints}
    assert "filesystem.local.search" in ids


def test_infer_hints_detects_powershell() -> None:
    hints = infer_capability_hints("rode comandos powershell para achar a pasta do mt5")
    ids = {h["id"] for h in hints}
    assert "filesystem.local.search" in ids


def test_infer_hints_detects_discovery_verbs_pt_br() -> None:
    for verb in ("ache", "localize", "encontre", "procure", "busque"):
        hints = infer_capability_hints(f"{verb} o arquivo de config")
        ids = {h["id"] for h in hints}
        assert "filesystem.local.search" in ids, f"verbo '{verb}' não detectado"


def test_infer_hints_detects_execute_commands() -> None:
    for term in ("rode os comandos", "execute o script", "rodar no terminal"):
        hints = infer_capability_hints(term)
        ids = {h["id"] for h in hints}
        assert "filesystem.local.search" in ids, f"'{term}' não detectado"


def test_infer_hints_detects_path_caminho() -> None:
    hints = infer_capability_hints("qual o caminho do executável")
    ids = {h["id"] for h in hints}
    assert "filesystem.local.search" in ids


def test_infer_hints_detects_instalado() -> None:
    hints = infer_capability_hints("onde o python está instalado")
    ids = {h["id"] for h in hints}
    assert "filesystem.local.search" in ids


def test_infer_hints_ignores_web_search_only() -> None:
    hints = infer_capability_hints("pesquise na web sobre python")
    ids = {h["id"] for h in hints}
    assert "search.public_web" in ids
    assert "filesystem.local.search" not in ids


def test_infer_hints_ignores_pure_greeting() -> None:
    hints = infer_capability_hints("oi tudo bem")
    ids = {h["id"] for h in hints}
    assert "filesystem.local.search" not in ids


def test_infer_hints_detects_connector() -> None:
    hints = infer_capability_hints("integre com a api do github")
    ids = {h["id"] for h in hints}
    assert "connector.http.generic" in ids
    assert "connector.github" in ids


def test_infer_hints_detects_tool_build() -> None:
    hints = infer_capability_hints("cria ferramenta de análise")
    ids = {h["id"] for h in hints}
    assert "tool.dynamic.build" in ids


# ── shell.local.readonly inference (2.3) ─────────────────────────────


def test_infer_hints_shell_from_execute_verb() -> None:
    hints = infer_capability_hints("execute os comandos no terminal")
    ids = {h["id"] for h in hints}
    assert "shell.local.readonly" in ids


def test_infer_hints_shell_from_powershell() -> None:
    hints = infer_capability_hints("rode no powershell")
    ids = {h["id"] for h in hints}
    assert "shell.local.readonly" in ids


def test_infer_hints_shell_from_terminal() -> None:
    hints = infer_capability_hints("abra o terminal e verifique")
    ids = {h["id"] for h in hints}
    assert "shell.local.readonly" in ids


def test_infer_hints_no_shell_for_greeting() -> None:
    hints = infer_capability_hints("oi tudo bem")
    ids = {h["id"] for h in hints}
    assert "shell.local.readonly" not in ids


# ── should_forge filters builtins (2.4) ──────────────────────────────


def _dummy_session() -> SessionState:
    return SessionState(
        version="session/v0",
        id="s",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        autonomy_mode="assistido",
        terms_accepted=False,
        governance_profile="guarded",
        turns=0,
        active_objectives=[],
        learned_preferences={},
        tool_history=[],
    )


def test_should_forge_false_for_builtins_only() -> None:
    hints = [
        {"id": "filesystem.local.search", "required": True},
        {"id": "search.public_web", "required": False},
    ]
    assert should_forge("ache a pasta", hints, _dummy_session()) is False


def test_should_forge_true_for_unknown_capability() -> None:
    hints = [{"id": "connector.salesforce", "required": True}]
    assert should_forge("integre com salesforce", hints, _dummy_session()) is True


def test_should_forge_true_for_explicit_keyword() -> None:
    assert should_forge("crie ferramenta de análise", [], _dummy_session()) is True


def test_infer_hints_no_false_positive_disco() -> None:
    hints = infer_capability_hints("pesquise sobre discografia do metallica")
    ids = {h["id"] for h in hints}
    assert "filesystem.local.search" not in ids


if __name__ == "__main__":
    unittest.main()
