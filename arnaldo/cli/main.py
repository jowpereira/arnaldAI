from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from typing import Any, Optional

from .output import print_chat_result, print_run_result, print_runtime_error
from .streaming import ProactiveNotifier, RunStreamer
from .utils import list_run_dir_names, safe_pending_proactive_count


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="arnaldo",
        description="Roda o nucleo do Arnaldo em modo grafo (execucao real).",
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
        "--chat-stream",
        action="store_true",
        help="No modo chat, exibe stream detalhado de trace/evidence/prompt (implica --chat).",
    )
    args = parser.parse_args()
    if args.chat_stream and not args.chat:
        args.chat = True

    from ..kernel import ArnaldoKernel

    kernel = ArnaldoKernel(runtime_mode="graph")

    if args.chat:
        run_chat_loop(
            kernel,
            args.autonomy,
            Path(args.out),
            args.session,
            args.accept_terms,
            stream_events=bool(args.chat_stream),
        )
        return

    intent = " ".join(args.intent).strip()
    if not intent:
        intent = input("Intencao: ").strip()
    if not intent:
        raise SystemExit("Intencao vazia.")

    output_dir = Path(args.out)
    try:
        result = run_with_live_streaming(
            kernel=kernel,
            intent=intent,
            autonomy=args.autonomy,
            output_dir=output_dir,
            session_id=args.session,
            terms_accepted=args.accept_terms,
        )
    except Exception as exc:
        print_runtime_error(exc)
        raise SystemExit(1) from exc
    print_run_result(result)


def run_chat_loop(
    kernel: Any,
    autonomy: str,
    output_dir: Path,
    session_id: Optional[str],
    terms_accepted: bool,
    *,
    stream_events: bool = False,
) -> None:
    print("=" * 72)
    print("ARNALDO CHAT (modo real, sem fallback)")
    print("- runtime: graph")
    print("- llm: obrigatoria")
    print("- saidas: resposta direta no terminal")
    print("- observabilidade: cada mensagem gera uma run (pasta run_*)")
    if stream_events:
        print("- streaming detalhado: ligado (--chat-stream)")
    if session_id:
        print(f"- sessao: {session_id}")
        pending = safe_pending_proactive_count(kernel, session_id)
        if pending > 0:
            print(f"- proatividade: {pending} mensagem(ns) pendente(s)")
    print("=" * 72)
    print("Digite 'sair' para encerrar.")

    notifier = ProactiveNotifier(kernel=kernel)
    notifier.set_session_id(session_id)
    notifier.start()

    try:
        while True:
            notifier.enable_prompt_mode()
            intent = input("voce> ").strip()
            notifier.disable_prompt_mode()
            if not intent:
                continue
            if intent.lower() in {"sair", "exit", "quit"}:
                print("Sessao encerrada.")
                return

            try:
                result = run_with_live_streaming(
                    kernel=kernel,
                    intent=intent,
                    autonomy=autonomy,
                    output_dir=output_dir,
                    session_id=session_id,
                    terms_accepted=terms_accepted,
                    stream_events=stream_events,
                )
            except Exception as exc:
                print_runtime_error(exc)
                continue

            session_id = result.session_id or session_id
            notifier.set_session_id(session_id)
            print_chat_result(result)
    finally:
        notifier.stop()


def run_with_live_streaming(
    *,
    kernel: Any,
    intent: str,
    autonomy: str,
    output_dir: Path,
    session_id: str | None,
    terms_accepted: bool,
    stream_events: bool = True,
    poll_interval: float = 0.08,
) -> Any:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not stream_events:
        return kernel.run(
            intent,
            autonomy=autonomy,
            output_dir=output_dir,
            session_id=session_id,
            terms_accepted=terms_accepted,
        )

    known_run_dirs = list_run_dir_names(output_dir)
    streamer = RunStreamer(output_dir=output_dir, known_run_dirs=known_run_dirs)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            kernel.run,
            intent,
            autonomy=autonomy,
            output_dir=output_dir,
            session_id=session_id,
            terms_accepted=terms_accepted,
        )
        while not future.done():
            streamer.poll()
            time.sleep(max(0.02, poll_interval))
        streamer.poll()
        return future.result()
