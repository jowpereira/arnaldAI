"""Testes para heurísticas de classificação do GraphRuntime."""

from __future__ import annotations

from types import SimpleNamespace

from arnaldo.runtime.graph_runtime.classify import (
    _contains_structured_execution_intent,
    _is_conversational_cli_turn,
)


# ── _contains_structured_execution_intent ────────────────────────────


def test_detects_ache_pasta() -> None:
    assert _contains_structured_execution_intent("ache a pasta do mt5") is True


def test_detects_encontre_arquivo() -> None:
    assert _contains_structured_execution_intent("encontre o arquivo de config") is True


def test_detects_rode_comandos() -> None:
    assert _contains_structured_execution_intent("rode os comandos e descubra") is True


def test_detects_powershell_keyword() -> None:
    assert _contains_structured_execution_intent("rode comandos powershell") is True


def test_detects_localize_diretorio() -> None:
    assert _contains_structured_execution_intent("localize o diretório de instalação") is True


def test_detects_terminal() -> None:
    assert _contains_structured_execution_intent("abra o terminal e verifique") is True


def test_detects_instalado() -> None:
    assert _contains_structured_execution_intent("tenho o mt5 instalado") is True


def test_detects_execute() -> None:
    assert _contains_structured_execution_intent("execute o script de teste") is True


def test_detects_caminho() -> None:
    assert _contains_structured_execution_intent("qual o caminho do executável") is True


def test_detects_explicit_ls_command() -> None:
    assert _contains_structured_execution_intent("consegue fazer um ls aqui") is True


def test_ignores_pure_conversation() -> None:
    assert _contains_structured_execution_intent("legal e vc quem e") is False


def test_ignores_greeting() -> None:
    assert _contains_structured_execution_intent("oi tudo bem") is False


def test_ignores_empty() -> None:
    assert _contains_structured_execution_intent("") is False


# Patterns originais continuam funcionando
def test_detects_api() -> None:
    assert _contains_structured_execution_intent("crie uma api rest") is True


def test_detects_workflow() -> None:
    assert _contains_structured_execution_intent("configure o workflow") is True


# ── _is_conversational_cli_turn ──────────────────────────────────────


def _make_task(raw_request: str, goal_type: str = "open_ended_execution") -> SimpleNamespace:
    return SimpleNamespace(
        goal={"type": goal_type, "statement": ""},
        context={
            "source": "cli",
            "raw_request": raw_request,
            "original_request": raw_request,
        },
    )


def test_rejects_local_discovery_request() -> None:
    task = _make_task("tenho o mt5 instalado ache a pasta")
    assert _is_conversational_cli_turn(task=task) is False


def test_rejects_powershell_request() -> None:
    task = _make_task("rode comandos powershell para achar a pasta")
    assert _is_conversational_cli_turn(task=task) is False


def test_rejects_encontre_arquivo() -> None:
    task = _make_task("encontre o arquivo de configuração")
    assert _is_conversational_cli_turn(task=task) is False


def test_accepts_genuine_conversation() -> None:
    task = _make_task("legal e vc quem e")
    assert _is_conversational_cli_turn(task=task) is True


def test_accepts_greeting() -> None:
    task = _make_task("oi")
    assert _is_conversational_cli_turn(task=task) is True


def test_rejects_non_cli_source() -> None:
    task = SimpleNamespace(
        goal={"type": "open_ended_execution", "statement": ""},
        context={"source": "api", "raw_request": "oi", "original_request": "oi"},
    )
    assert _is_conversational_cli_turn(task=task) is False


def test_rejects_non_open_ended_goal() -> None:
    task = _make_task("oi", goal_type="create_or_build")
    assert _is_conversational_cli_turn(task=task) is False


# ── False positives (2.2) — verbos ambíguos SEM contexto técnico ─────


def test_criar_coragem_is_not_execution() -> None:
    assert _contains_structured_execution_intent("quero criar coragem") is False


def test_sistema_solar_is_not_execution() -> None:
    assert _contains_structured_execution_intent("o sistema solar é grande") is False


def test_abra_coracao_is_not_execution() -> None:
    assert _contains_structured_execution_intent("abra o coração") is False


def test_mostre_respeito_is_not_execution() -> None:
    assert _contains_structured_execution_intent("mostre respeito") is False


def test_criar_com_contexto_tecnico_is_execution() -> None:
    assert _contains_structured_execution_intent("criar uma api rest") is True


def test_mostrar_arquivo_is_execution() -> None:
    assert _contains_structured_execution_intent("mostrar o arquivo de config") is True


def test_abrir_terminal_is_execution() -> None:
    assert _contains_structured_execution_intent("abrir o terminal") is True


def test_memoria_ruim_is_not_execution() -> None:
    assert _contains_structured_execution_intent("minha memória está ruim") is False


def test_verifique_horario_is_execution() -> None:
    """'verifique' é verbo de descoberta, match direto."""
    assert _contains_structured_execution_intent("verifique se o docker está rodando") is True


# ── False negatives — requests operacionais que DEVEM ser detectados ──


def test_descubra_onde_esta_python() -> None:
    assert (
        _contains_structured_execution_intent(
            "preciso que você descubra onde está instalado o Python"
        )
        is True
    )


def test_listar_processos() -> None:
    assert (
        _contains_structured_execution_intent("quero listar todos os processos do sistema") is True
    )


def test_mostra_conteudo_pasta() -> None:
    assert _contains_structured_execution_intent("me mostra o conteúdo da pasta C:\\Users") is True


def test_obrigado_is_not_execution() -> None:
    assert _contains_structured_execution_intent("obrigado pela ajuda") is False


def test_como_vai_is_not_execution() -> None:
    assert _contains_structured_execution_intent("como vai você?") is False


# ── _is_conversational_cli_turn com capability_resolution ─────────


def test_rejects_conversational_with_filesystem_capability() -> None:
    task = _make_task("me ajuda aqui")
    cap_res = {"missing": [{"id": "filesystem.local.search"}], "degraded": []}
    assert _is_conversational_cli_turn(task=task, capability_resolution=cap_res) is False


def test_rejects_conversational_with_shell_capability() -> None:
    task = _make_task("me ajuda aqui")
    cap_res = {"missing": [{"id": "shell.local.readonly"}], "degraded": []}
    assert _is_conversational_cli_turn(task=task, capability_resolution=cap_res) is False


def test_rejects_conversational_with_available_shell_capability() -> None:
    task = _make_task("me ajuda aqui")
    cap_res = {"available": [{"id": "shell.local.readonly"}], "missing": [], "degraded": []}
    assert _is_conversational_cli_turn(task=task, capability_resolution=cap_res) is False
