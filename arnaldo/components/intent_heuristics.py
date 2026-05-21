"""Heurísticas de classificação e derivação para IntentCompiler."""

from __future__ import annotations

import re
from typing import Any, Dict, List


def normalize_request(request: str) -> str:
    return " ".join((request or "").strip().split())


def derive_desired_state(text: str) -> str:
    """Transforma pedido imperativo em estado final declarativo."""
    clean = " ".join(text.strip().split())
    if not clean:
        return clean[:180]

    transforms = [
        (r"^crie\b|^criar\b|^gere\b|^gerar\b|^construa\b|^monte\b", "Existe"),
        (r"^analise\b|^analisar\b|^avalie\b|^avaliar\b", "Análise completa de"),
        (r"^planeje\b|^planejar\b|^organize\b|^estruture\b", "Plano estruturado para"),
        (r"^corrija\b|^corrigir\b|^melhore\b|^otimize\b|^refatore\b", "Versão melhorada de"),
        (r"^automatize\b|^automatizar\b|^execute\b|^rode\b", "Automação funcional de"),
        (r"^implemente\b|^implementar\b", "Implementação completa de"),
        (r"^documente\b|^documentar\b", "Documentação completa de"),
        (r"^integre\b|^integrar\b", "Integração funcional de"),
        (r"^teste\b|^testar\b|^valide\b|^validar\b", "Validação completa de"),
    ]
    lowered = clean.lower()
    for pattern, prefix in transforms:
        match = re.match(pattern, lowered)
        if match:
            remainder = clean[match.end() :].strip()
            if remainder:
                return f"{prefix} {remainder}"[:180]
            return f"{prefix} {clean}"[:180]

    if any(lowered.startswith(v) for v in ("quero", "preciso", "foco")):
        return clean[:180]
    return f"Resultado completo: {clean}"[:180]


def derive_primary_goal(text: str) -> str:
    lowered = text.lower()
    goal_patterns = [
        (
            "crie|criar|construa|construir|gere|gerar|monte|montar|implemente|implementar",
            "create_or_generate",
        ),
        (
            "analise|analisar|avalie|avaliar|diagnostique|diagnosticar|revise|revisar",
            "analyze_or_evaluate",
        ),
        (
            "planeje|planejar|organize|organizar|priorize|priorizar|estruture|estruturar",
            "plan_or_structure",
        ),
        (
            "automatize|automatizar|execute|executar|rode|rodar|operacionalize|operacionalizar",
            "execute_or_automate",
        ),
        (
            "corrija|corrigir|melhore|melhorar|otimize|otimizar|refatore|refatorar",
            "repair_or_improve",
        ),
        (
            "decida|decidir|escolha|escolher|compare|comparar|selecione|selecionar",
            "decide_or_compare",
        ),
    ]
    for pattern, goal in goal_patterns:
        if re.search(pattern, lowered):
            return goal
    return "open_ended_execution"


def autonomy_level(autonomy: str) -> int:
    levels = {"manual": 1, "assistido": 2, "autonomo": 3, "livre": 6}
    return levels.get(autonomy, 2)


def external_effects_for(autonomy: str) -> str:
    if autonomy == "livre":
        return "allowed_if_policy_compliant"
    return "approval_required"


def infer_signals(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    words = lowered.split()
    vague_terms = count_matches(
        lowered, ["qualquer", "tudo", "generico", "amplo", "melhor", "ideal"]
    )
    external_terms = count_matches(
        lowered, ["publicar", "enviar", "comprar", "deletar", "deploy", "cliente"]
    )
    sensitive_terms = count_matches(
        lowered, ["senha", "token", "privado", "cpf", "pagamento", "dados pessoais"]
    )
    irreversible_terms = count_matches(
        lowered, ["deletar", "apagar", "publicar", "comprar", "migrar"]
    )
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
