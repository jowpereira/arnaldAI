from __future__ import annotations

from pathlib import Path

from arnaldo.components import IntentCompiler, TaskCompiler
from arnaldo.contracts import IntentIR, RunResult, TaskIR
from arnaldo.kernel import ArnaldoKernel


def compile_intent(intent: str, autonomy: str = "assistido") -> IntentIR:
    return IntentCompiler().compile(intent, autonomy=autonomy)


def compile_task(intent_ir: IntentIR) -> TaskIR:
    return TaskCompiler().compile(intent_ir)


def run(
    intent: str,
    autonomy: str = "assistido",
    output_dir: Path = Path("runs"),
    session_id: str | None = None,
    terms_accepted: bool | None = None,
) -> RunResult:
    return ArnaldoKernel().run(
        intent,
        autonomy=autonomy,
        output_dir=output_dir,
        session_id=session_id,
        terms_accepted=terms_accepted,
    )
