"""Streaming e apresentação de resultados para a CLI."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from .formatting import (
    format_agent_bus_stream_line,
    format_evidence_stream_line,
    format_prompt_stream_header,
    format_prompt_message_lines,
    format_trace_stream_line,
)
from .utils import (
    discover_new_run_dir,
    safe_pop_due_proactive_messages,
    safe_read_jsonl,
)


class RunStreamer:
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
        self._heartbeat_idle_threshold = 3.0
        self._heartbeat_interval = 5.0

    def poll(self) -> None:
        if self.run_dir is None:
            self.run_dir = discover_new_run_dir(self.output_dir, self.known_run_dirs)
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
        idle_seconds = now - self._last_event_at
        if idle_seconds < self._heartbeat_idle_threshold:
            return
        if now - self._last_heartbeat_at < self._heartbeat_interval:
            return
        self._last_heartbeat_at = now
        waiting_on = "llm" if self.stream_positions["prompts"] > 0 else "runtime"
        print(
            "[stream][%s][heartbeat] waiting_on=%s, idle=%.1fs | trace=%d, evidence=%d, agent=%d, prompts=%d"
            % (
                datetime.now().strftime("%H:%M:%S"),
                waiting_on,
                idle_seconds,
                self.stream_positions["trace"],
                self.stream_positions["evidence"],
                self.stream_positions["agent_bus"],
                self.stream_positions["prompts"],
            )
        )

    def _stream_trace_rows(self) -> int:
        if self.run_dir is None:
            return 0
        rows = safe_read_jsonl(self.run_dir / "trace.jsonl")
        start = self.stream_positions["trace"]
        if start < 0 or start > len(rows):
            start = 0
        emitted = 0
        for row in rows[start:]:
            message = format_trace_stream_line(row)
            if message:
                print(message)
                emitted += 1
        self.stream_positions["trace"] = len(rows)
        return emitted

    def _stream_evidence_rows(self) -> int:
        if self.run_dir is None:
            return 0
        rows = safe_read_jsonl(self.run_dir / "evidence.jsonl")
        start = self.stream_positions["evidence"]
        if start < 0 or start > len(rows):
            start = 0
        emitted = 0
        for row in rows[start:]:
            message = format_evidence_stream_line(row)
            if message:
                print(message)
                emitted += 1
        self.stream_positions["evidence"] = len(rows)
        return emitted

    def _stream_agent_bus_rows(self) -> int:
        if self.run_dir is None:
            return 0
        rows = safe_read_jsonl(self.run_dir / "agent_bus.jsonl")
        start = self.stream_positions["agent_bus"]
        if start < 0 or start > len(rows):
            start = 0
        emitted = 0
        for row in rows[start:]:
            message = format_agent_bus_stream_line(row)
            if message:
                print(message)
                emitted += 1
        self.stream_positions["agent_bus"] = len(rows)
        return emitted

    def _stream_prompt_rows(self) -> int:
        if self.run_dir is None:
            return 0
        rows = safe_read_jsonl(self.run_dir / "prompts.jsonl")
        start = self.stream_positions["prompts"]
        if start < 0 or start > len(rows):
            start = 0
        emitted = 0
        for row in rows[start:]:
            print(format_prompt_stream_header(row))
            emitted += 1
            for line in format_prompt_message_lines(row):
                print(line)
                emitted += 1
        self.stream_positions["prompts"] = len(rows)
        return emitted


class ProactiveNotifier:
    def __init__(self, *, kernel: Any, poll_interval: float = 2.0) -> None:
        self.kernel = kernel
        self.poll_interval = max(0.5, float(poll_interval))
        self._lock = Lock()
        self._session_id: str | None = None
        self._prompt_mode = False
        self._stop = Event()
        self._thread: Thread | None = None

    def set_session_id(self, session_id: str | None) -> None:
        with self._lock:
            self._session_id = session_id

    def enable_prompt_mode(self) -> None:
        with self._lock:
            self._prompt_mode = True

    def disable_prompt_mode(self) -> None:
        with self._lock:
            self._prompt_mode = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run, name="arnaldo-proactive-notifier", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._flush_due_messages()
            self._stop.wait(self.poll_interval)

    def _flush_due_messages(self) -> None:
        with self._lock:
            session_id = self._session_id
            prompt_mode = self._prompt_mode
        if not session_id or not prompt_mode:
            return
        messages = safe_pop_due_proactive_messages(self.kernel, session_id)
        if not messages:
            return
        print("")
        for message in messages:
            print(f"arnaldo(proativo)> {message}")
        print("voce> ", end="", flush=True)
