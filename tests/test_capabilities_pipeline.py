"""Testes do pipeline de capabilities — circuito completo."""

from __future__ import annotations

from arnaldo.runtime.graph_runtime.capabilities import (
    _collect_tool_execution_targets,
    _collect_tooling_targets,
)


# ── _collect_tooling_targets reconhece todos os prefixos ─────────────


def test_collect_tooling_targets_includes_filesystem() -> None:
    cap_res = {
        "missing": [{"id": "filesystem.local.search"}],
        "degraded": [{"id": "shell.local.readonly"}],
    }
    result = _collect_tooling_targets(cap_res)
    assert "filesystem.local.search" in result["missing"]
    assert "shell.local.readonly" in result["degraded"]


def test_collect_tooling_targets_includes_legacy_prefixes() -> None:
    cap_res = {
        "missing": [{"id": "connector.http.generic"}],
        "degraded": [{"id": "search.public_web"}, {"id": "tool.dynamic.build"}],
    }
    result = _collect_tooling_targets(cap_res)
    assert "connector.http.generic" in result["missing"]
    assert "search.public_web" in result["degraded"]
    assert "tool.dynamic.build" in result["degraded"]


def test_collect_tooling_targets_ignores_unknown_prefix() -> None:
    cap_res = {"missing": [{"id": "random.thing"}], "degraded": []}
    result = _collect_tooling_targets(cap_res)
    assert result["missing"] == []


# ── _collect_tool_execution_targets com builtins ─────────────────────


def test_execution_targets_includes_builtins_without_module_path() -> None:
    cap_res = {
        "available": [{"id": "filesystem.local.search"}],
        "degraded": [],
        "missing": [],
    }
    targets = _collect_tool_execution_targets(cap_res)
    ids = {t["id"] for t in targets}
    assert "filesystem.local.search" in ids


def test_execution_targets_includes_shell_builtin() -> None:
    cap_res = {
        "available": [{"id": "shell.local.readonly"}],
        "degraded": [],
        "missing": [],
    }
    targets = _collect_tool_execution_targets(cap_res)
    ids = {t["id"] for t in targets}
    assert "shell.local.readonly" in ids


def test_execution_targets_skips_unknown_without_module_path() -> None:
    cap_res = {
        "available": [{"id": "filesystem.unknown.thing"}],
        "degraded": [],
        "missing": [],
    }
    targets = _collect_tool_execution_targets(cap_res)
    ids = {t["id"] for t in targets}
    assert "filesystem.unknown.thing" not in ids


def test_execution_targets_uses_explicit_module_path_if_present() -> None:
    cap_res = {
        "available": [
            {
                "id": "connector.custom",
                "module_path": "arnaldo.capabilities.custom.CustomCapability",
            }
        ],
        "degraded": [],
        "missing": [],
    }
    targets = _collect_tool_execution_targets(cap_res)
    found = [t for t in targets if t["id"] == "connector.custom"]
    assert len(found) == 1
    assert found[0]["module_path"] == "arnaldo.capabilities.custom.CustomCapability"


def test_execution_targets_builtin_has_fqn_as_module_path() -> None:
    cap_res = {
        "available": [{"id": "filesystem.local.search"}],
        "degraded": [],
        "missing": [],
    }
    targets = _collect_tool_execution_targets(cap_res)
    found = [t for t in targets if t["id"] == "filesystem.local.search"]
    assert len(found) == 1
    assert "FilesystemSearchCapability" in found[0]["module_path"]
