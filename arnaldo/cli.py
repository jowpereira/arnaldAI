from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import re
import time
from typing import Any, Optional


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="arnaldo",
        description="Roda o nucleo do Arnaldo em modo real (grafo, sem fallback).",
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
    args = parser.parse_args()

    from .kernel import ArnaldoKernel

    kernel = ArnaldoKernel(runtime_mode="graph")

    if args.chat:
        run_chat_loop(kernel, args.autonomy, Path(args.out), args.session, args.accept_terms)
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
) -> None:
    print("=" * 72)
    print("ARNALDO CHAT (modo real, sem fallback)")
    print("- runtime: graph")
    print("- llm: obrigatoria")
    print("- saidas: runs + trace + evidence + artifact")
    if session_id:
        print(f"- sessao: {session_id}")
    print("=" * 72)
    print("Digite 'sair' para encerrar.")

    while True:
        intent = input("voce> ").strip()
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
            )
        except Exception as exc:
            print_runtime_error(exc)
            continue

        session_id = result.session_id or session_id
        print_run_result(result, compact=True)


def run_with_live_streaming(
    *,
    kernel: Any,
    intent: str,
    autonomy: str,
    output_dir: Path,
    session_id: str | None,
    terms_accepted: bool,
    poll_interval: float = 0.08,
) -> Any:
    output_dir.mkdir(parents=True, exist_ok=True)
    known_run_dirs = _list_run_dir_names(output_dir)
    streamer = _RunStreamer(output_dir=output_dir, known_run_dirs=known_run_dirs)

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


def print_run_result(result: Any, compact: bool = False) -> None:
    summary = build_run_summary(result)
    agent_response = _build_agent_response_preview(result)
    print("=" * 72)
    print("ARNALDO - EXECUCAO CONCLUIDA")
    print("=" * 72)
    print(f"Run ID        : {result.run_id}")
    print(f"Session       : {result.session_id or '-'}")
    print(f"Run Dir       : {result.run_dir}")
    print(f"Topologia     : {summary['topology']}")
    print(f"Execucao      : {summary['execution_mode']}")
    if summary["duration_seconds"] is not None:
        print(f"Duracao       : {summary['duration_seconds']:.2f}s")
    print("-" * 72)
    print(
        "Workflow      : %d planejados | %d executados"
        % (summary["planned_steps"], summary["executed_steps"])
    )
    print(
        "Evidencias    : %d total | recusas=%d | erros=%d | fallback=%d"
        % (
            summary["evidence_total"],
            summary["refusal_count"],
            summary["error_count"],
            summary["fallback_count"],
        )
    )
    print(
        "Capabilities  : available=%d | missing=%d | degraded=%d"
        % (
            summary["capabilities_available"],
            summary["capabilities_missing"],
            summary["capabilities_degraded"],
        )
    )
    if summary["tool_forge_created"] or summary["tool_forge_failed"]:
        print(
            "Tool Forge    : created=%d | failed=%d"
            % (summary["tool_forge_created"], summary["tool_forge_failed"])
        )
    if summary["graph_capability_synced"] or summary["graph_capability_sync_skipped"]:
        print(
            "Graph Sync    : synced=%d | skipped=%d"
            % (summary["graph_capability_synced"], summary["graph_capability_sync_skipped"])
        )
    print("-" * 72)
    print(f"Artifact      : {summary['artifact_path']}")
    print(f"Evidence      : {summary['evidence_path']}")
    print(f"Trace         : {summary['trace_path']}")
    if summary["prompts_path"]:
        print(f"Prompts       : {summary['prompts_path']}")
    print("-" * 72)
    print("Resposta do Agente")
    if agent_response:
        print(agent_response)
    else:
        print("(vazia - artifact sem secao legivel)")

    if compact:
        print("=" * 72)
        return

    if summary["evidence_by_type"]:
        print("-" * 72)
        print("Evidence by Type")
        for record_type, count in summary["evidence_by_type"].items():
            print(f"- {record_type}: {count}")

    if summary["trace_by_event"]:
        print("-" * 72)
        print("Trace by Event")
        for event_type, count in summary["trace_by_event"].items():
            print(f"- {event_type}: {count}")

    print("-" * 72)
    print("Arquivos da Run")
    for key in sorted(result.files.keys()):
        print(f"- {key}: {result.files[key]}")
    print("=" * 72)


def print_runtime_error(exc: Exception) -> None:
    message = str(exc).strip() or repr(exc)
    print("=" * 72)
    print("ERRO DE EXECUCAO (modo real, sem fallback)")
    print("=" * 72)
    print(f"Tipo          : {exc.__class__.__name__}")
    print(f"Mensagem      : {message}")
    print("-" * 72)
    print("Checklist rapido")
    print("- Configure LLM Azure no ambiente (.env) com endpoint, key e deployments.")
    print("- Verifique conectividade com a Azure OpenAI.")
    print("- Confirme se o deployment/tier requisitado existe e aceita requests.")
    print("- Se o erro for refusal, revise o pedido para reduzir bloqueios de safety.")
    print("=" * 72)


def build_run_summary(result: Any) -> dict[str, Any]:
    files = dict(result.files or {})
    organization = _safe_read_json(files.get("organization_ir"))
    workflow = _safe_read_json(files.get("graph_workflow_materialized"))
    capability_resolution = _safe_read_json(files.get("capability_resolution"))
    graph_tool_forge = _safe_read_json(files.get("graph_tool_forge"))
    graph_capability_sync = _safe_read_json(files.get("graph_capability_sync"))
    trace = _safe_read_jsonl(files.get("trace"))
    evidence = _safe_read_jsonl(files.get("evidence"))

    trace_by_event = _sorted_counts(_count_by_key(trace, "event_type"))
    evidence_by_type = _sorted_counts(_count_by_key(evidence, "record_type"))

    planned_steps = _as_int(workflow.get("step_count"))
    executed_steps = _as_int(trace_by_event.get("step_completed"))
    duration_seconds = _duration_from_trace(trace)

    return {
        "topology": str(workflow.get("topology") or organization.get("topology") or "-"),
        "execution_mode": str(workflow.get("execution_mode") or "-"),
        "planned_steps": planned_steps,
        "executed_steps": executed_steps,
        "evidence_total": len(evidence),
        "refusal_count": _as_int(evidence_by_type.get("llm_refusal")),
        "error_count": _as_int(evidence_by_type.get("step_failed")),
        "fallback_count": _as_int(evidence_by_type.get("step_fallback")),
        "capabilities_available": len(capability_resolution.get("available", []) or []),
        "capabilities_missing": len(capability_resolution.get("missing", []) or []),
        "capabilities_degraded": len(capability_resolution.get("degraded", []) or []),
        "tool_forge_created": len(graph_tool_forge.get("created", []) or []),
        "tool_forge_failed": len(graph_tool_forge.get("failed", []) or []),
        "graph_capability_synced": len(graph_capability_sync.get("synced", []) or []),
        "graph_capability_sync_skipped": len(graph_capability_sync.get("skipped", []) or []),
        "duration_seconds": duration_seconds,
        "artifact_path": str(files.get("artifact", "")),
        "evidence_path": str(files.get("evidence", "")),
        "trace_path": str(files.get("trace", "")),
        "prompts_path": str(files.get("prompts", "")),
        "evidence_by_type": evidence_by_type,
        "trace_by_event": trace_by_event,
    }


def _safe_read_json(path: Any) -> dict[str, Any]:
    if not isinstance(path, Path) or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _safe_read_jsonl(path: Any) -> list[dict[str, Any]]:
    if not isinstance(path, Path) or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        label = str(item.get(key, "")).strip()
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    return counts


def _sorted_counts(counts: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _duration_from_trace(trace_rows: list[dict[str, Any]]) -> float | None:
    timestamps: list[datetime] = []
    for item in trace_rows:
        raw = str(item.get("created_at", "")).strip()
        if not raw:
            continue
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            timestamps.append(datetime.fromisoformat(raw))
        except ValueError:
            continue
    if len(timestamps) < 2:
        return None
    timestamps.sort()
    duration = (timestamps[-1] - timestamps[0]).total_seconds()
    return duration if duration >= 0 else None


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _list_run_dir_names(output_dir: Path) -> set[str]:
    if not output_dir.exists():
        return set()
    return {
        path.name
        for path in output_dir.iterdir()
        if path.is_dir() and path.name.startswith("run_")
    }


def _discover_new_run_dir(output_dir: Path, known_run_dirs: set[str]) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = [
        path
        for path in output_dir.iterdir()
        if path.is_dir() and path.name.startswith("run_") and path.name not in known_run_dirs
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    selected = candidates[0]
    known_run_dirs.add(selected.name)
    return selected


def _format_trace_stream_line(row: dict[str, Any]) -> str:
    created_at = _format_stream_timestamp(row.get("created_at"))
    event_type = str(row.get("event_type", "")).strip() or "trace_event"
    payload = row.get("payload")
    details = _summarize_stream_payload(payload if isinstance(payload, dict) else {})
    if details:
        return f"[stream][{created_at}][trace] {event_type} | {details}"
    return f"[stream][{created_at}][trace] {event_type}"


def _format_evidence_stream_line(row: dict[str, Any]) -> str:
    created_at = _format_stream_timestamp(row.get("created_at"))
    record_type = str(row.get("record_type", "")).strip() or "evidence_record"
    summary = str(row.get("summary", "")).strip()
    payload = row.get("payload")
    details = _summarize_stream_payload(payload if isinstance(payload, dict) else {})
    line = f"[stream][{created_at}][evidence] {record_type}"
    if summary:
        line += f" | {summary}"
    if details:
        line += f" | {details}"
    return line


def _format_agent_bus_stream_line(row: dict[str, Any]) -> str:
    created_at = _format_stream_timestamp(row.get("ts") or row.get("created_at"))
    event = str(row.get("event", "")).strip() or "agent_event"
    details = _summarize_stream_payload(row)
    if details:
        return f"[stream][{created_at}][agent] {event} | {details}"
    return f"[stream][{created_at}][agent] {event}"


def _format_prompt_stream_header(row: dict[str, Any]) -> str:
    created_at = _format_stream_timestamp(row.get("created_at"))
    action = str(row.get("action", "")).strip()
    node_id = str(row.get("node_id", "")).strip()
    tier = str(row.get("tier", "")).strip()
    model = str(row.get("response_model", "")).strip()
    chat_kwargs = row.get("chat_kwargs") if isinstance(row.get("chat_kwargs"), dict) else {}
    max_tokens = int(chat_kwargs.get("max_tokens", 0) or 0)
    timeout = float(chat_kwargs.get("timeout", 0.0) or 0.0)
    details = []
    if action:
        details.append(f"action={action}")
    if tier:
        details.append(f"tier={tier}")
    if model:
        details.append(f"model={model}")
    if max_tokens > 0:
        details.append(f"max_tokens={max_tokens}")
    if timeout > 0:
        details.append(f"timeout={timeout:.1f}s")
    suffix = " | " + ", ".join(details) if details else ""
    return f"[stream][{created_at}][prompt] {node_id or 'synapse'}{suffix}"


def _format_prompt_message_lines(row: dict[str, Any]) -> list[str]:
    messages = row.get("messages")
    if not isinstance(messages, list):
        return []
    lines: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")).strip() or "user"
        content = _compact_stream_text(str(item.get("content", "")), limit=320)
        if not content:
            continue
        lines.append(f"  [{role}] {content}")
    return lines


def _format_stream_timestamp(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return "--:--:--"
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return "--:--:--"
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone()
    return stamp.strftime("%H:%M:%S")


def _summarize_stream_payload(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    parts: list[str] = []
    keys = [
        "wave_index",
        "topology",
        "execution_mode",
        "mode",
        "tier",
        "response_model",
        "message_count",
        "step_count",
        "workflow_steps",
        "index",
        "step_id",
        "action",
        "agent_id",
        "node_id",
        "capability_id",
        "status",
        "reason",
        "error",
        "count",
        "completed",
        "size",
    ]
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        rendered = str(value).strip()
        if not rendered:
            continue
        if len(rendered) > 120:
            rendered = rendered[:120].rstrip() + "..."
        parts.append(f"{key}={rendered}")
    if not parts:
        return ""
    return ", ".join(parts)


def _compact_stream_text(value: str, *, limit: int = 320) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


class _RunStreamer:
    def __init__(self, *, output_dir: Path, known_run_dirs: set[str]) -> None:
        self.output_dir = output_dir
        self.known_run_dirs = set(known_run_dirs)
        self.run_dir: Path | None = None
        self.stream_positions = {
            "trace": 0,
            "evidence": 0,
            "agent_bus": 0,
            "prompts": 0,
        }
        self.stream_started = False
        now = time.monotonic()
        self._last_event_at = now
        self._last_heartbeat_at = now

    def poll(self) -> None:
        if self.run_dir is None:
            self.run_dir = _discover_new_run_dir(self.output_dir, self.known_run_dirs)
            if self.run_dir is None:
                return
            if not self.stream_started:
                self.stream_started = True
                print("-" * 72)
                print(f"STREAMING     : {self.run_dir.name}")
                print("-" * 72)
        emitted = 0
        emitted += self._stream_trace_rows()
        emitted += self._stream_evidence_rows()
        emitted += self._stream_agent_bus_rows()
        emitted += self._stream_prompt_rows()
        if emitted > 0:
            self._last_event_at = time.monotonic()
            return
        now = time.monotonic()
        if now - self._last_heartbeat_at >= 1.2:
            self._last_heartbeat_at = now
            print(
                "[stream][%s][heartbeat] running | trace=%d, evidence=%d, agent=%d, prompts=%d"
                % (
                    datetime.now().strftime("%H:%M:%S"),
                    self.stream_positions["trace"],
                    self.stream_positions["evidence"],
                    self.stream_positions["agent_bus"],
                    self.stream_positions["prompts"],
                )
            )

    def _stream_trace_rows(self) -> int:
        if self.run_dir is None:
            return 0
        rows = _safe_read_jsonl(self.run_dir / "trace.jsonl")
        start = self.stream_positions["trace"]
        if start < 0 or start > len(rows):
            start = 0
        emitted = 0
        for row in rows[start:]:
            message = _format_trace_stream_line(row)
            if message:
                print(message)
                emitted += 1
        self.stream_positions["trace"] = len(rows)
        return emitted

    def _stream_evidence_rows(self) -> int:
        if self.run_dir is None:
            return 0
        rows = _safe_read_jsonl(self.run_dir / "evidence.jsonl")
        start = self.stream_positions["evidence"]
        if start < 0 or start > len(rows):
            start = 0
        emitted = 0
        for row in rows[start:]:
            message = _format_evidence_stream_line(row)
            if message:
                print(message)
                emitted += 1
        self.stream_positions["evidence"] = len(rows)
        return emitted

    def _stream_agent_bus_rows(self) -> int:
        if self.run_dir is None:
            return 0
        rows = _safe_read_jsonl(self.run_dir / "agent_bus.jsonl")
        start = self.stream_positions["agent_bus"]
        if start < 0 or start > len(rows):
            start = 0
        emitted = 0
        for row in rows[start:]:
            message = _format_agent_bus_stream_line(row)
            if message:
                print(message)
                emitted += 1
        self.stream_positions["agent_bus"] = len(rows)
        return emitted

    def _stream_prompt_rows(self) -> int:
        if self.run_dir is None:
            return 0
        rows = _safe_read_jsonl(self.run_dir / "prompts.jsonl")
        start = self.stream_positions["prompts"]
        if start < 0 or start > len(rows):
            start = 0
        emitted = 0
        for row in rows[start:]:
            print(_format_prompt_stream_header(row))
            emitted += 1
            for line in _format_prompt_message_lines(row):
                print(line)
                emitted += 1
        self.stream_positions["prompts"] = len(rows)
        return emitted


def _build_agent_response_preview(result: Any, *, max_chars: int = 2200) -> str:
    files = dict(getattr(result, "files", {}) or {})
    selected: list[str] = []
    step_preview = _build_latest_step_preview(files)
    if step_preview:
        selected.append(step_preview)

    artifact_preview = _build_artifact_preview(files)
    if artifact_preview:
        selected.append(artifact_preview)

    preview = "\n\n".join(part for part in selected if part).strip()
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + "..."
    return preview


def _build_latest_step_preview(files: dict[str, Any]) -> str:
    evidence_rows = _safe_read_jsonl(files.get("evidence"))
    for row in reversed(evidence_rows):
        record_type = str(row.get("record_type", "")).strip()
        if record_type not in {"step_completed", "step_fallback", "step_failed"}:
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        result = payload.get("result")
        if isinstance(result, dict):
            step_lines: list[str] = []
            status = str(result.get("status", "")).strip()
            if status:
                step_lines.append(f"status: {status}")
            sections = result.get("sections")
            if isinstance(sections, list):
                for section in sections[:3]:
                    if isinstance(section, str) and section.strip():
                        step_lines.append(section.strip())
            evidence = result.get("evidence")
            if isinstance(evidence, list) and evidence:
                evidence_text = ", ".join(
                    item.strip()
                    for item in evidence[:2]
                    if isinstance(item, str) and item.strip()
                )
                if evidence_text:
                    step_lines.append(f"evidence: {evidence_text}")
            uncertainties = result.get("uncertainties")
            if isinstance(uncertainties, list) and uncertainties:
                uncertainty_text = ", ".join(
                    item.strip()
                    for item in uncertainties[:2]
                    if isinstance(item, str) and item.strip()
                )
                if uncertainty_text:
                    step_lines.append(f"uncertainties: {uncertainty_text}")
            if step_lines:
                return "Output do Synapse:\n" + "\n".join(f"- {line}" for line in step_lines)
        error = str(payload.get("error", "")).strip()
        if error:
            return "Output do Synapse:\n- error: " + error
    return ""


def _build_artifact_preview(files: dict[str, Any]) -> str:
    artifact_path = files.get("artifact")
    if not isinstance(artifact_path, Path) or not artifact_path.exists():
        return ""
    try:
        artifact = artifact_path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if not artifact:
        return ""

    sections = _parse_markdown_sections(artifact)
    preferred_titles = [
        "resposta",
        "resposta final",
        "final answer",
        "answer",
        "summary",
        "goal",
        "step outputs",
        "next actions",
    ]
    selected: list[str] = []
    seen_titles: set[str] = set()
    for wanted in preferred_titles:
        for title, body in sections:
            normalized = title.strip().lower()
            if normalized != wanted:
                continue
            if normalized in seen_titles:
                continue
            compact_body = _compact_block(body)
            if not compact_body:
                continue
            seen_titles.add(normalized)
            selected.append(f"{title}:\n{compact_body}")
            break

    if not selected:
        first_non_empty = ""
        for _, body in sections:
            compact_body = _compact_block(body)
            if compact_body:
                first_non_empty = compact_body
                break
        if first_non_empty:
            selected.append(first_non_empty)

    if not selected:
        selected.append(_compact_block(artifact))

    return "\n\n".join(part for part in selected if part).strip()


def _parse_markdown_sections(markdown: str) -> list[tuple[str, str]]:
    lines = markdown.splitlines()
    sections: list[tuple[str, str]] = []
    title = ""
    buffer: list[str] = []
    pattern = re.compile(r"^##\s+(.+?)\s*$")
    for line in lines:
        match = pattern.match(line)
        if match:
            if title or buffer:
                sections.append((title, "\n".join(buffer).strip()))
            title = match.group(1).strip()
            buffer = []
            continue
        buffer.append(line)
    if title or buffer:
        sections.append((title, "\n".join(buffer).strip()))
    return sections


def _compact_block(value: str) -> str:
    lines = [line.rstrip() for line in value.splitlines()]
    trimmed = [line for line in lines if line.strip()]
    text = "\n".join(trimmed).strip()
    if not text:
        return ""
    if len(text) > 800:
        return text[:800].rstrip() + "..."
    return text


if __name__ == "__main__":
    main()
