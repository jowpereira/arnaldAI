from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class GapReport:
    status: str
    warnings: List[str]
    missing_sections: List[str]


class RealityGapDetector:
    """Compares Task IR expectations with produced artifacts metadata."""

    def analyze(self, task: Any, step_results: List[Dict[str, Any]]) -> GapReport:
        expected = {item["id"] for item in task.deliverables}
        produced = {result.get("output") for result in step_results}
        missing = sorted(expected - produced)
        warnings = []
        if missing:
            warnings.append("deliverables_missing")
        return GapReport(
            status="gap_detected" if missing else "ok",
            warnings=warnings,
            missing_sections=missing,
        )
