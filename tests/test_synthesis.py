"""Testes para build_synthesis_messages e synthesize_response."""

from __future__ import annotations

from types import SimpleNamespace

from arnaldo.prompts.context import _extract_step_content, build_synthesis_messages
from arnaldo.kernel.fast_path import synthesize_response


# ── _extract_step_content ───────────────────────────────────────────


def test_extract_step_content_uses_result_summary() -> None:
    step = {"output": "primary_artifact", "result": {"summary": "Resposta real do step"}}
    assert _extract_step_content(step) == "Resposta real do step"


def test_extract_step_content_uses_result_content() -> None:
    step = {"output": "primary_artifact", "result": {"content": "Conteúdo real"}}
    assert _extract_step_content(step) == "Conteúdo real"


def test_extract_step_content_uses_result_sections() -> None:
    step = {
        "output": "primary_artifact",
        "result": {"sections": [{"content": "Seção 1 texto"}]},
    }
    content = _extract_step_content(step)
    assert "Seção 1 texto" in content


def test_extract_step_content_uses_result_string() -> None:
    step = {"output": "primary_artifact", "result": "Texto direto do result"}
    assert _extract_step_content(step) == "Texto direto do result"


def test_extract_step_content_falls_back_to_summary() -> None:
    step = {"summary": "Resumo do step", "output": "primary_artifact"}
    assert _extract_step_content(step) == "Resumo do step"


def test_extract_step_content_rejects_deliverable_name() -> None:
    """Nome de deliverable (snake_case sem espaços) não deve ser retornado."""
    step = {"output": "primary_artifact"}
    assert _extract_step_content(step) == ""


def test_extract_step_content_accepts_real_text_output() -> None:
    step = {"output": "Esta é uma resposta textual real com espaços"}
    assert "resposta textual real" in _extract_step_content(step)


# ── build_synthesis_messages ────────────────────────────────────────


def test_build_synthesis_messages_uses_result_not_deliverable_name() -> None:
    steps = [
        {
            "output": "primary_artifact",
            "result": {"sections": [{"content": "Análise completa do mercado"}]},
            "success": True,
        }
    ]
    messages = build_synthesis_messages(step_results=steps, original_request="analise o mercado")
    content = messages[-1]["content"]
    assert "primary_artifact" not in content
    assert "mercado" in content.lower()


def test_build_synthesis_messages_marks_failed_steps() -> None:
    steps = [
        {"output": "x", "result": "falhou", "success": False},
    ]
    messages = build_synthesis_messages(step_results=steps, original_request="teste")
    content = messages[-1]["content"]
    assert "FALHOU" in content


def test_build_synthesis_messages_truncates_at_500() -> None:
    steps = [{"result": "x" * 1000, "success": True}]
    messages = build_synthesis_messages(step_results=steps, original_request="teste")
    content = messages[-1]["content"]
    # Step content truncado a 500 chars
    assert len(content) < 1500


# ── synthesize_response ─────────────────────────────────────────────


def test_synthesize_response_empty_steps() -> None:
    result = SimpleNamespace(step_results=[])
    response = synthesize_response(result, "teste", None)
    assert "concluída" in response.lower()


def test_synthesize_response_without_llm_uses_result_content() -> None:
    steps = [
        {
            "output": "primary_artifact",
            "result": {"summary": "Resposta correta do planner"},
            "success": True,
        }
    ]
    result = SimpleNamespace(step_results=steps)
    response = synthesize_response(result, "teste", None)
    assert "Resposta correta do planner" in response
    assert "primary_artifact" not in response


def test_synthesize_response_without_llm_rejects_deliverable_name() -> None:
    """Regressão: 'primary_artifact' nunca aparece na resposta ao usuário."""
    steps = [
        {"output": "primary_artifact", "success": True},
        {"output": "execution_evidence", "success": True},
    ]
    result = SimpleNamespace(step_results=steps)
    response = synthesize_response(result, "teste", None)
    assert "primary_artifact" not in response
    assert "execution_evidence" not in response


def test_synthesize_response_with_llm_calls_chat() -> None:
    """Com LLM configurado, usa chat tier=fast para sintetizar."""
    steps = [
        {"output": "primary_artifact", "result": {"summary": "ok"}, "success": True},
    ]
    result = SimpleNamespace(step_results=steps)

    class FakeLLM:
        is_configured = True
        calls: list = []

        def chat(self, tier: str = "fast", messages: list | None = None, **kw):
            self.calls.append({"tier": tier, "messages": messages})
            return SimpleNamespace(content="Resposta sintetizada pelo LLM")

    llm = FakeLLM()
    response = synthesize_response(result, "analise o mercado", llm)
    assert response == "Resposta sintetizada pelo LLM"
    assert llm.calls[0]["tier"] == "fast"


# ── Edge cases de _extract_step_content ─────────────────────────────


def test_extract_step_content_empty_dict_result() -> None:
    """Dict vazio como result não deve retornar '{}'."""
    step = {"output": "primary_artifact", "result": {}}
    content = _extract_step_content(step)
    # Dict vazio é tratado como ausência — cai no fallback
    assert content != "{}"


def test_extract_step_content_allows_snake_case_real_content() -> None:
    """Conteúdo legítimo snake_case (ex: mt5_terminal_64) não é descartado."""
    step = {"output": "mt5_terminal_64"}
    content = _extract_step_content(step)
    assert content == "mt5_terminal_64"


def test_extract_step_content_rejects_known_deliverable_names() -> None:
    """Nomes de deliverable conhecidos (execution_evidence, next_actions) são rejeitados."""
    for deliverable in ("primary_artifact", "execution_evidence", "next_actions"):
        step = {"output": deliverable}
        assert _extract_step_content(step) == "", f"'{deliverable}' deveria ser rejeitado"
