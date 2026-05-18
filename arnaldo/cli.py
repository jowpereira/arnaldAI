from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from .kernel import ArnaldoKernel


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="arnaldo",
        description="Roda o nucleo minimo do assistente Arnaldo.",
    )
    parser.add_argument("intent", nargs="*", help="Intencao que o assistente deve compilar.")
    parser.add_argument(
        "--autonomy",
        default="autonomo",
        choices=["manual", "assistido", "autonomo", "livre"],
        help="Nivel de autonomia permitido.",
    )
    parser.add_argument(
        "--out",
        default="runs",
        help="Diretorio onde a execucao sera registrada.",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="ID de sessao para continuidade entre turnos.",
    )
    parser.add_argument(
        "--accept-terms",
        action="store_true",
        help="Aceita termos de autonomia ampliada e reduz checkpoints manuais.",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Inicia loop interativo continuo.",
    )
    parser.add_argument(
        "--runtime-mode",
        default="graph",
        choices=["local", "graph", "multiagent"],
        help="Seleciona o runtime de execucao (default: graph).",
    )
    args = parser.parse_args()
    kernel = ArnaldoKernel(runtime_mode=args.runtime_mode)

    if args.chat:
        run_chat_loop(kernel, args.autonomy, Path(args.out), args.session, args.accept_terms)
        return

    intent = " ".join(args.intent).strip()
    if not intent:
        intent = input("Intencao: ").strip()

    result = kernel.run(
        intent,
        autonomy=args.autonomy,
        output_dir=Path(args.out),
        session_id=args.session,
        terms_accepted=args.accept_terms,
    )
    print_run_result(result)


def run_chat_loop(
    kernel: ArnaldoKernel,
    autonomy: str,
    output_dir: Path,
    session_id: Optional[str],
    terms_accepted: bool,
) -> None:
    print("Modo chat iniciado. Digite 'sair' para encerrar.")
    if session_id:
        print(f"Sessao atual: {session_id}")
    while True:
        intent = input("voce> ").strip()
        if not intent:
            continue
        if intent.lower() in {"sair", "exit", "quit"}:
            print("Sessao encerrada.")
            return

        result = kernel.run(
            intent,
            autonomy=autonomy,
            output_dir=output_dir,
            session_id=session_id,
            terms_accepted=terms_accepted,
        )
        session_id = result.session_id or session_id
        print_run_result(result, compact=True)


def print_run_result(result, compact: bool = False) -> None:
    print(f"Arnaldo executou a intencao em: {result.run_dir}")
    if result.session_id:
        print(f"- Session: {result.session_id}")
    print(f"- Artifact: {result.files['artifact']}")
    print(f"- Evidence: {result.files['evidence']}")
    if compact:
        return
    print(f"- Intent IR: {result.files['intent_ir']}")
    print(f"- Task IR: {result.files['task_ir']}")
    print(f"- Organization IR: {result.files['organization_ir']}")
    print(f"- Resultado: {result.files['result']}")


if __name__ == "__main__":
    main()
