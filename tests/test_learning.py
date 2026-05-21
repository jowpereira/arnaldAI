"""Testes do módulo de learning — detecção de feedback implícito."""

from __future__ import annotations

from arnaldo.kernel.learning import (
    compute_reward,
    detect_implicit_feedback,
    extract_quality_signals,
)


class TestDetectImplicitFeedback:
    """Testa detecção de sinais de qualidade."""

    def test_positive_obrigado(self):
        assert detect_implicit_feedback("Obrigado, ficou perfeito!") == "positive"

    def test_positive_valeu(self):
        assert detect_implicit_feedback("valeu!") == "positive"

    def test_negative_errado(self):
        assert detect_implicit_feedback("Isso está errado") == "negative"

    def test_negative_nao_funciona(self):
        assert detect_implicit_feedback("não funciona") == "negative"

    def test_correction_na_verdade(self):
        assert detect_implicit_feedback("Na verdade, eu quis dizer outra coisa") == "correction"

    def test_correction_actually(self):
        assert detect_implicit_feedback("actually, o certo seria X") == "correction"

    def test_neutral_normal(self):
        assert detect_implicit_feedback("Crie um plano de negócios") == "neutral"

    def test_empty_is_neutral(self):
        assert detect_implicit_feedback("") == "neutral"

    def test_none_equivalent(self):
        assert detect_implicit_feedback("   ") == "neutral"

    def test_correction_takes_priority_over_negative(self):
        # "na verdade" implica correção, não negatividade pura
        assert detect_implicit_feedback("Na verdade isso tá errado") == "correction"


class TestComputeReward:
    """Testa conversão feedback → reward numérico."""

    def test_positive_reward(self):
        assert compute_reward("positive") == 0.8

    def test_neutral_reward(self):
        assert compute_reward("neutral") == 0.5

    def test_negative_reward(self):
        assert compute_reward("negative") == 0.1

    def test_correction_reward(self):
        assert compute_reward("correction") == 0.15

    def test_unknown_defaults_neutral(self):
        assert compute_reward("invalid") == 0.5


class TestExtractQualitySignals:
    """Testa extração de sinais de qualidade do histórico."""

    def test_empty_history(self):
        result = extract_quality_signals([])
        assert result["avg_reward"] == 0.0
        assert result["trend"] == "negative"
        assert result["signals"] == []

    def test_positive_trend(self):
        history = [
            {"role": "assistant", "content": "Resposta"},
            {"role": "user", "content": "Obrigado, perfeito!"},
            {"role": "assistant", "content": "Outra resposta"},
            {"role": "user", "content": "Excelente!"},
        ]
        result = extract_quality_signals(history)
        assert result["trend"] == "positive"
        assert result["avg_reward"] == 0.8

    def test_negative_trend(self):
        history = [
            {"role": "user", "content": "Isso tá errado"},
            {"role": "user", "content": "Não funciona, refaz"},
        ]
        result = extract_quality_signals(history)
        assert result["trend"] == "negative"

    def test_window_limits(self):
        history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        result = extract_quality_signals(history, window=3)
        assert len(result["signals"]) == 3
