from __future__ import annotations

import argparse
from pathlib import Path

from .kernel import ArnaldoKernel


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="arnaldo",
        description="Roda o nucleo minimo do assistente Arnaldo.",
    )
    parser.add_argument("intent", nargs="*", help="Intencao que o assistente deve compilar.")
    parser.add_argument(
        "--autonomy",
        default="assistido",
        choices=["manual", "assistido", "autonomo"],
        help="Nivel de autonomia permitido.",
    )
    parser.add_argument(
        "--out",
        default="runs",
        help="Diretorio onde a execucao sera registrada.",
    )
    args = parser.parse_args()

    intent = " ".join(args.intent).strip()
    if not intent:
        intent = input("Intencao: ").strip()

    result = ArnaldoKernel().run(intent, autonomy=args.autonomy, output_dir=Path(args.out))

    print(f"Arnaldo executou a intencao em: {result.run_dir}")
    print(f"- Intent IR: {result.files['intent_ir']}")
    print(f"- Task IR: {result.files['task_ir']}")
    print(f"- Organization IR: {result.files['organization_ir']}")
    print(f"- Artifact: {result.files['artifact']}")
    print(f"- Evidence: {result.files['evidence']}")
    print(f"- Resultado: {result.files['result']}")


if __name__ == "__main__":
    main()
