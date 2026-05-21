"""Chat REPL — loop conversacional interativo com o Arnaldo."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from arnaldo.contracts import new_id
from arnaldo.kernel import ArnaldoKernel

logger = logging.getLogger("arnaldo.chat")


def _print_status(kernel: ArnaldoKernel) -> None:
    """Mostra status do grafo cognitivo."""
    graph = kernel.memory.load_graph()
    n_nodes = graph.node_count
    from arnaldo.graph.nodes import NodeKind

    memories = sum(1 for _ in graph.iter_nodes(kind=NodeKind.MEMORY, active_only=False))
    synapses = sum(1 for _ in graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=False))
    caps = sum(1 for _ in graph.iter_nodes(kind=NodeKind.CAPABILITY, active_only=False))
    edges = sum(
        sum(1 for _ in graph.iter_edges_from(n.id)) for n in graph.iter_nodes(active_only=False)
    )
    print(
        f"\n  Grafo: {n_nodes} nós ({memories} mem, {synapses} syn, {caps} cap) | {edges} arestas"
    )
    # Synapses detalhadas
    for syn in graph.iter_nodes(kind=NodeKind.SYNAPSE, active_only=False):
        w = graph.plasticity.effective_weight(syn)
        print(f"    syn: {syn.label[:35]:35} w={w:.3f} status={syn.status.value}")
    print()


def _print_graph_summary(kernel: ArnaldoKernel) -> None:
    """Mostra resumo do grafo com nós mais fortes."""
    graph = kernel.memory.load_graph()
    nodes = sorted(
        graph.iter_nodes(active_only=True),
        key=lambda n: graph.plasticity.effective_weight(n),
        reverse=True,
    )
    print(f"\n  Top nós ({graph.node_count} total):")
    for node in nodes[:10]:
        w = graph.plasticity.effective_weight(node)
        print(f"    [{node.kind.value:10}] {node.label[:40]:40} w={w:.3f}")
    print()


def _handle_slash(command: str, kernel: ArnaldoKernel) -> bool:
    """Processa slash commands. Retorna True se deve continuar o loop."""
    cmd = command.lower().strip()
    if cmd in ("/sair", "/quit", "/exit"):
        return False
    if cmd == "/status":
        _print_status(kernel)
        return True
    if cmd in ("/grafo", "/graph"):
        _print_graph_summary(kernel)
        return True
    if cmd in ("/help", "/ajuda"):
        print("\n  Comandos: /status /grafo /nova /help /sair\n")
        return True
    if cmd == "/nova":
        return True  # sinaliza nova sessão — tratado no loop
    print(f"\n  Comando desconhecido: {command}. Use /help\n")
    return True


def chat_loop(
    *,
    session_id: str | None = None,
    autonomy: str = "assistido",
    output_dir: Path = Path("runs"),
) -> None:
    """Loop conversacional interativo. Ctrl+C para sair."""
    kernel = ArnaldoKernel()

    # F7: Observabilidade — logging configurável (scoped ao arnaldo.*)
    if os.environ.get("ARNALDO_DEBUG"):
        arnaldo_logger = logging.getLogger("arnaldo")
        arnaldo_logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("  [%(name)s] %(message)s"))
        arnaldo_logger.addHandler(handler)

    # F2: Session continuity — retoma sessão anterior se existir
    if not session_id:
        last = kernel.sessions.last_active_session()
        if last:
            session_id = last
            state = kernel.sessions.load(session_id)
            print(f"Arnaldo · retomando sessão ({state.turns} turnos)")
            print("(/nova para sessão limpa | /help para comandos)\n")
        else:
            session_id = new_id("session")
            print("Arnaldo · substrate cognitivo simbólico")
            print("(Ctrl+C para sair | /help para comandos)\n")
    else:
        print("Arnaldo · substrate cognitivo simbólico")
        print("(Ctrl+C para sair | /help para comandos)\n")

    while True:
        try:
            user_input = input("→ ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if user_input.lower().strip() == "/nova":
                session_id = new_id("session")
                print("\n  Nova sessão iniciada.\n")
                continue
            if not _handle_slash(user_input, kernel):
                break
            continue

        # Indicador de progresso
        sys.stdout.write("  ⏳ pensando...")
        sys.stdout.flush()
        t0 = time.monotonic()

        try:
            result = kernel.run(
                user_input,
                autonomy=autonomy,
                output_dir=output_dir,
                session_id=session_id,
                llm_classify=True,
            )
            elapsed = time.monotonic() - t0
            # F7: mostra path e stats no debug
            graph = kernel.memory.load_graph()
            logger.debug(
                "%.1fs | grafo=%d nós | session=%s",
                elapsed,
                graph.node_count,
                session_id,
            )
            sys.stdout.write(f"\r  ✓ {elapsed:.1f}s        \n")
        except Exception as exc:
            elapsed = time.monotonic() - t0
            sys.stdout.write(f"\r  ✗ erro ({elapsed:.1f}s)  \n")
            print(f"\n  [erro] {type(exc).__name__}: {exc}\n")
            continue

        session_id = result.session_id or session_id

        if result.response:
            print(f"\n{result.response}\n")
        else:
            print("\n[execução concluída sem resposta textual]\n")

        proactive = kernel.pop_due_proactive_messages(session_id)
        for msg in proactive:
            print(f"  💭 {msg}\n")


def main() -> None:
    """Entry point para chat via CLI."""
    import argparse

    parser = argparse.ArgumentParser(description="Arnaldo Chat REPL")
    parser.add_argument("--session", type=str, default=None, help="Session ID")
    parser.add_argument("--autonomy", type=str, default="assistido")
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()

    chat_loop(
        session_id=args.session,
        autonomy=args.autonomy,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
