from __future__ import annotations

from typing import Any, Dict, List
import re

from arnaldo.contracts import IntentIR, new_id, utc_now


class IntentCompiler:
    """Converts a human request into a generic declarative contract."""

    def compile(self, request: str, autonomy: str = "assistido") -> IntentIR:
        text = normalize_request(request)
        if not text:
            raise ValueError("Informe uma intencao para o Arnaldo executar.")

        signals = infer_signals(text)
        return IntentIR(
            version="intent-ir/v0",
            id=new_id("intent"),
            created_at=utc_now(),
            original_request=text,
            desired_state=derive_desired_state(text),
            primary_goal=derive_primary_goal(text),
            autonomy={
                "mode": autonomy,
                "max_level": autonomy_level(autonomy),
            },
            constraints={
                "genericity": "high",
                "local_first": True,
                "external_side_effects": "approval_required",
                "private_data": "explicit_permission_required",
            },
            inferred_requirements=infer_requirements(signals),
            open_questions=infer_open_questions(text, signals),
            signals=signals,
        )


def normalize_request(request: str) -> str:
    return " ".join((request or "").strip().split())


def derive_desired_state(text: str) -> str:
    return text[:180]


def derive_primary_goal(text: str) -> str:
    lowered = text.lower()
    goal_patterns = [
        ("crie|criar|construa|construir|gere|gerar|monte|montar|implemente|implementar", "create_or_generate"),
        ("analise|analisar|avalie|avaliar|diagnostique|diagnosticar|revise|revisar", "analyze_or_evaluate"),
        ("planeje|planejar|organize|organizar|priorize|priorizar|estruture|estruturar", "plan_or_structure"),
        ("automatize|automatizar|execute|executar|rode|rodar|operacionalize|operacionalizar", "execute_or_automate"),
        ("corrija|corrigir|melhore|melhorar|otimize|otimizar|refatore|refatorar", "repair_or_improve"),
        ("decida|decidir|escolha|escolher|compare|comparar|selecione|selecionar", "decide_or_compare"),
    ]
    for pattern, goal in goal_patterns:
        if re.search(pattern, lowered):
            return goal
    return "open_ended_execution"


def autonomy_level(autonomy: str) -> int:
    levels = {
        "manual": 1,
        "assistido": 2,
        "autonomo": 3,
    }
    return levels.get(autonomy, 2)


def infer_signals(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    words = lowered.split()
    vague_terms = count_matches(lowered, ["qualquer", "tudo", "generico", "amplo", "melhor", "ideal"])
    external_terms = count_matches(lowered, ["publicar", "enviar", "comprar", "deletar", "deploy", "cliente"])
    sensitive_terms = count_matches(lowered, ["senha", "token", "privado", "cpf", "pagamento", "dados pessoais"])
    irreversible_terms = count_matches(lowered, ["deletar", "apagar", "publicar", "comprar", "migrar"])

    return {
        "word_count": len(words),
        "ambiguity_score": min(3, vague_terms + (1 if len(words) < 8 else 0)),
        "external_impact_score": min(3, external_terms),
        "data_sensitivity_score": min(3, sensitive_terms),
        "irreversibility_score": min(3, irreversible_terms),
        "goal_type": derive_primary_goal(text),
    }


def infer_requirements(signals: Dict[str, Any]) -> List[str]:
    requirements = [
        "preservar intencao original",
        "produzir artefato verificavel",
        "registrar decisoes e evidencias",
        "marcar incertezas em vez de escondelas",
    ]
    if signals["ambiguity_score"] > 0:
        requirements.append("separar inferencias de fatos")
    if signals["external_impact_score"] > 0:
        requirements.append("bloquear efeitos externos sem aprovacao")
    return requirements


def infer_open_questions(text: str, signals: Dict[str, Any]) -> List[str]:
    questions = []
    if signals["ambiguity_score"] >= 2:
        questions.append("qual nivel de profundidade e suficiente para esta execucao?")
    if signals["external_impact_score"] > 0:
        questions.append("quais acoes externas estao autorizadas?")
    if signals["word_count"] < 8:
        questions.append("qual artefato final o usuario espera receber?")
    return questions


def count_matches(text: str, terms: List[str]) -> int:
    return sum(1 for term in terms if term in text)
