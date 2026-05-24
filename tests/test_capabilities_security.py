"""Testes de segurança para capabilities de filesystem e shell local."""

from __future__ import annotations

import os
import platform

import pytest

from arnaldo.capabilities.filesystem_search import FilesystemSearchCapability
from arnaldo.capabilities.local_shell import LocalShellCapability
from arnaldo.capabilities.registry import CapabilityExecutor


# ── FilesystemSearchCapability ──────────────────────────────────────


def test_filesystem_rejects_path_traversal() -> None:
    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "../../../etc/passwd"})
    assert not result.success
    assert "não permitidos" in result.error


def test_filesystem_rejects_semicolon() -> None:
    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "foo; rm -rf /"})
    assert not result.success


def test_filesystem_rejects_pipe() -> None:
    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "foo | bar"})
    assert not result.success


def test_filesystem_rejects_dollar() -> None:
    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "$HOME"})
    assert not result.success


def test_filesystem_rejects_empty_pattern() -> None:
    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": ""})
    assert not result.success


def test_filesystem_rejects_whitespace_pattern() -> None:
    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "   "})
    assert not result.success


def test_filesystem_max_depth_capped_at_6() -> None:
    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "nonexistent_xyz_999", "max_depth": 100})
    # Não deve estourar — max_depth é capped internamente
    assert result.success


# ── LocalShellCapability ────────────────────────────────────────────


def test_shell_rejects_unknown_command() -> None:
    cap = LocalShellCapability()
    result = cap.execute({"command": "rm", "args": ["-rf", "/"]})
    assert not result.success
    assert "allowlist" in result.error


def test_shell_rejects_path_traversal_in_args() -> None:
    cap = LocalShellCapability()
    cmd = "where" if platform.system() == "Windows" else "which"
    result = cap.execute({"command": cmd, "args": ["../../etc/passwd"]})
    assert not result.success
    assert ".." in result.error


def test_shell_rejects_delete_arg() -> None:
    cap = LocalShellCapability()
    cmd = "dir" if platform.system() == "Windows" else "find"
    result = cap.execute({"command": cmd, "args": ["-delete"]})
    assert not result.success
    assert "proibida" in result.error


def test_shell_rejects_execdir() -> None:
    cap = LocalShellCapability()
    cmd = "find" if platform.system() != "Windows" else "where"
    result = cap.execute({"command": cmd, "args": [".", "-execdir"]})
    assert not result.success
    assert "proibida" in result.error


def test_shell_allows_format_flag_in_path() -> None:
    """--format é flag legítima, não o comando destrutivo 'format'."""
    cap = LocalShellCapability()
    cmd = "dir" if platform.system() == "Windows" else "ls"
    result = cap.execute({"command": cmd, "args": ["--format=long"]})
    # Não deve ser bloqueado — 'format' exato é proibido, '--format' não é
    assert result.success or "proibida" not in result.error


def test_shell_allows_path_containing_rm_substring() -> None:
    """Path como /usr/share/firmware não deve ser bloqueado por conter 'rm'."""
    cap = LocalShellCapability()
    cmd = "dir" if platform.system() == "Windows" else "ls"
    result = cap.execute({"command": cmd, "args": ["/usr/share/firmware"]})
    # Não deve ser bloqueado por substring match
    assert result.success or "proibida" not in result.error


def test_shell_rejects_rm_exact_as_arg() -> None:
    """'rm' como argumento exato deve ser bloqueado."""
    cap = LocalShellCapability()
    cmd = "dir" if platform.system() == "Windows" else "find"
    result = cap.execute({"command": cmd, "args": [".", "rm"]})
    assert not result.success
    assert "proibida" in result.error


def test_shell_rejects_pipe_in_arg() -> None:
    cap = LocalShellCapability()
    cmd = "where" if platform.system() == "Windows" else "which"
    result = cap.execute({"command": cmd, "args": ["python", "|", "head"]})
    assert not result.success
    assert "proibido" in result.error


def test_shell_rejects_redirect_in_arg() -> None:
    cap = LocalShellCapability()
    cmd = "where" if platform.system() == "Windows" else "which"
    result = cap.execute({"command": cmd, "args": ["python", ">", "output.txt"]})
    assert not result.success


# ── Happy path: FilesystemSearchCapability ──────────────────────────


def test_filesystem_search_finds_file_in_tmp(tmp_path: pytest.TempPathFactory) -> None:
    target = tmp_path / "apps" / "mt5"  # type: ignore[operator]
    target.mkdir(parents=True)
    (target / "terminal.exe").write_text("fake")
    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "*terminal*", "roots": [str(tmp_path)]})
    assert result.success
    assert any("terminal" in str(m).lower() for m in result.data.get("matches", []))
    assert result.source.kind.value == "external_authority"
    assert result.latency_ms >= 0


def test_filesystem_search_empty_results(tmp_path: pytest.TempPathFactory) -> None:
    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "nonexistent_xyz_999", "roots": [str(tmp_path)]})
    assert result.success
    assert result.data.get("matches") == []


# ── Happy path: LocalShellCapability ────────────────────────────────


def test_shell_happy_path_where_python() -> None:
    cap = LocalShellCapability()
    cmd = "where" if platform.system() == "Windows" else "which"
    result = cap.execute({"command": cmd, "args": ["python"]})
    # Pode falhar se python não está no PATH, mas não deve ser bloqueado
    assert result.success or "allowlist" not in result.error
    assert cmd in result.data.get("command", "")


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only")
def test_shell_allows_dir_on_windows() -> None:
    cap = LocalShellCapability()
    result = cap.execute({"command": "dir", "args": ["."]})
    assert result.success
    assert result.data.get("stdout")


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only")
def test_shell_allows_get_childitem_on_windows() -> None:
    cap = LocalShellCapability()
    result = cap.execute({"command": "get-childitem", "args": ["."]})
    assert result.success or "allowlist" not in result.error


@pytest.mark.skipif(platform.system() == "Windows", reason="POSIX-only")
def test_shell_rejects_posix_on_windows_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    cap = LocalShellCapability()
    result = cap.execute({"command": "ls", "args": ["."]})
    assert not result.success


# ── Symlink safety in _search_recursive ──────────────────────────────


def _can_create_symlinks() -> bool:
    """Verifica se o SO/user tem permissão para criar symlinks."""
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src")
            dst = os.path.join(d, "dst")
            os.makedirs(src)
            os.symlink(src, dst, target_is_directory=True)
            return True
    except (OSError, NotImplementedError):
        return False


@pytest.mark.skipif(not _can_create_symlinks(), reason="symlinks not supported")
def test_search_recursive_ignores_symlinks(tmp_path: pytest.TempPathFactory) -> None:
    safe_dir = tmp_path / "safe"  # type: ignore[operator]
    safe_dir.mkdir()
    (safe_dir / "real_file.txt").write_text("real")

    escape_target = tmp_path / "escape_target"  # type: ignore[operator]
    escape_target.mkdir()
    (escape_target / "secret.txt").write_text("secret")

    os.symlink(str(escape_target), str(safe_dir / "escape_link"), target_is_directory=True)

    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "*secret*", "roots": [str(safe_dir)]})
    assert result.success
    matches = [str(m) for m in result.data.get("matches", [])]
    assert not any("secret" in m for m in matches)


@pytest.mark.skipif(not _can_create_symlinks(), reason="symlinks not supported")
def test_search_recursive_finds_real_files_not_symlinks(
    tmp_path: pytest.TempPathFactory,
) -> None:
    safe_dir = tmp_path / "safe"  # type: ignore[operator]
    safe_dir.mkdir()
    (safe_dir / "target.txt").write_text("found")

    outside = tmp_path / "outside"  # type: ignore[operator]
    outside.mkdir()
    (outside / "target.txt").write_text("nope")
    os.symlink(str(outside), str(safe_dir / "link"), target_is_directory=True)

    cap = FilesystemSearchCapability()
    result = cap.execute({"pattern": "*target*", "roots": [str(safe_dir)]})
    assert result.success
    matches = [str(m) for m in result.data.get("matches", [])]
    # Encontra o real, não segue o link
    assert any("safe" in m and "target" in m for m in matches)
    assert not any("outside" in m for m in matches)


# ── GraphEvent emission (I6 compliance) ─────────────────────────────


def test_executor_emits_graph_event_on_success(tmp_path: pytest.TempPathFactory) -> None:
    (tmp_path / "test.txt").write_text("hi")  # type: ignore[operator]
    executor = CapabilityExecutor()
    result = executor.execute(
        "filesystem.local.search",
        {"pattern": "*test*", "roots": [str(tmp_path)]},
    )
    events = executor.drain_events()
    assert len(events) == 1
    ev = events[0]
    assert ev.kind.value == "capability_executed"
    assert ev.metadata["capability_id"] == "filesystem.local.search"
    assert ev.metadata["success"] == result.success


def test_executor_emits_graph_event_on_failure() -> None:
    executor = CapabilityExecutor()
    result = executor.execute("nonexistent.capability", {})
    assert not result.success
    events = executor.drain_events()
    assert len(events) == 1
    ev = events[0]
    assert ev.kind.value == "capability_executed"
    assert ev.metadata["success"] is False
    assert ev.metadata["error"] == "no_implementation"


def test_executor_drain_clears_events(tmp_path: pytest.TempPathFactory) -> None:
    (tmp_path / "a.txt").write_text("a")  # type: ignore[operator]
    executor = CapabilityExecutor()
    executor.execute("filesystem.local.search", {"pattern": "*a*", "roots": [str(tmp_path)]})
    first = executor.drain_events()
    assert len(first) == 1
    second = executor.drain_events()
    assert len(second) == 0


# ── functools.wraps preservation (3.1) ──────────────────────────────


def test_timed_execution_preserves_metadata() -> None:
    cap = FilesystemSearchCapability()
    # O método execute decorado deve manter __name__ e __wrapped__
    assert cap.execute.__name__ == "execute"
    assert hasattr(cap.execute, "__wrapped__")
