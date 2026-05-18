"""Roteamento de tasks cognitivas para tiers apropriados.

Cada task cognitiva tem um tier alvo. Tasks de raciocínio profundo vão para GOD,
tasks de síntese para EXPERT, tasks de extração para FAST, tasks de código para CODEX.
"""
from __future__ import annotations

from typing import Dict, Optional

from .config import CODEX, EXPERT, FAST, GOD


# Mapa explícito de task cognitiva → tier
# Convenção de nome: <componente>.<operação>
TASK_TIER_MAP: Dict[str, str] = {
    # ─── GOD ──────────────────────────────────────────────────────
    # Raciocínio profundo, planejamento, síntese cross-domain
    "intent.deep_inference": GOD,
    "task.plan_complex": GOD,
    "cognitive.mode_selection_complex": GOD,
    "organization.synthesize_complex": GOD,
    "policy.evaluate_high_risk": GOD,
    "reality.gap_analyze_deep": GOD,
    "episteme.knowledge_synthesis": GOD,
    "episteme.contradiction_resolve": GOD,
    "memory.consolidate_insight": GOD,
    "strategic.long_horizon_plan": GOD,

    # ─── EXPERT ───────────────────────────────────────────────────
    # Síntese e análise padrão, drafting de artefatos
    "intent.compile": EXPERT,
    "intent.derive_desired_state": EXPERT,
    "task.draft": EXPERT,
    "task.derive_deliverables": EXPERT,
    "artifact.draft": EXPERT,
    "artifact.synthesize": EXPERT,
    "validation.critic_review": EXPERT,
    "organization.synthesize": EXPERT,
    "cognitive.mode_selection": EXPERT,
    "memory.consolidate": EXPERT,
    "reality.gap_analyze": EXPERT,
    "episteme.entity_extract_rich": EXPERT,

    # ─── FAST ─────────────────────────────────────────────────────
    # Extração, formatação, classificação rápida
    "intent.extract_signals": FAST,
    "intent.detect_objectives": FAST,
    "intent.classify_goal": FAST,
    "capability.detect_hints": FAST,
    "entity.extract": FAST,
    "entity.resolve": FAST,
    "format.structured_output": FAST,
    "format.summarize_brief": FAST,
    "episteme.query_classify_intent": FAST,
    "episteme.relevance_score": FAST,

    # ─── CODEX ────────────────────────────────────────────────────
    # Geração de código (com reasoning effort)
    "tool_forge.generate_connector": CODEX,
    "tool_forge.generate_connector_complex": CODEX,
    "tool_forge.refactor": CODEX,
    "tool_forge.smoke_test_synthesize": CODEX,
    "code.generate": CODEX,
    "code.refactor": CODEX,
    "code.review": CODEX,
    "code.synthesize_function": CODEX,
    "code.fix_bug": CODEX,
    "code.add_type_hints": CODEX,
    "code.generate_test": CODEX,
    "runtime.generate_step_implementation": CODEX,
}


def tier_for_task(task_type: str, override: Optional[str] = None) -> str:
    """Retorna o tier apropriado para uma task cognitiva.

    Args:
        task_type: nome canônico da task (ex: "intent.compile")
        override: força um tier específico, ignorando o mapa

    Returns:
        Nome do tier ("god", "expert", "fast" ou "codex")

    Default: EXPERT se task_type desconhecida.
    """
    if override:
        return override
    return TASK_TIER_MAP.get(task_type, EXPERT)


def register_task(task_type: str, tier: str) -> None:
    """Registra (ou sobrescreve) o mapeamento de uma task para tier."""
    valid_tiers = (GOD, EXPERT, FAST, CODEX)
    if tier not in valid_tiers:
        raise ValueError(f"Tier inválido '{tier}'. Use: {valid_tiers}")
    TASK_TIER_MAP[task_type] = tier


def tasks_by_tier() -> Dict[str, list]:
    """Retorna agrupamento de tasks por tier (útil para debug/docs)."""
    grouped: Dict[str, list] = {GOD: [], EXPERT: [], FAST: [], CODEX: []}
    for task, tier in TASK_TIER_MAP.items():
        grouped.setdefault(tier, []).append(task)
    return grouped
