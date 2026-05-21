from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class GapReport:
    status: str
    warnings: List[str]
    missing_sections: List[str]
    quality_score: float = 1.0


class RealityGapDetector:
    """Compares Task IR expectations with produced artifacts metadata."""

    def analyze(self, task: Any, step_results: List[Dict[str, Any]]) -> GapReport:
        expected = {item["id"] for item in task.deliverables}
        produced = {result.get("output") for result in step_results}
        missing = sorted(expected - produced)
        warnings: List[str] = []

        # Gap 1: deliverables não produzidos
        if missing:
            warnings.append("deliverables_missing")

        # Gap 2: steps falhados
        failed_steps = [r for r in step_results if not r.get("success", True)]
        if failed_steps:
            warnings.append(f"steps_failed:{len(failed_steps)}")

        # Gap 3: todos success mas sem conteúdo substancial
        if step_results and all(r.get("success", False) for r in step_results):
            empty_outputs = sum(
                1
                for r in step_results
                if not str(r.get("content", "")).strip() and not r.get("result")
            )
            if empty_outputs > len(step_results) // 2:
                warnings.append("outputs_shallow")

        # Score de qualidade baseado na proporção de sucesso
        total = len(step_results) or 1
        successes = sum(1 for r in step_results if r.get("success", False))
        quality = successes / total

        return GapReport(
            status="gap_detected" if warnings else "ok",
            warnings=warnings,
            missing_sections=missing,
            quality_score=round(quality, 3),
        )
