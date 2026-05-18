from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
import json

from arnaldo.contracts import new_id, to_dict, utc_now


@dataclass
class SandboxState:
    version: str
    id: str
    run_id: str
    session_id: str
    created_at: str
    mode: str
    root_path: str
    workspace_path: str
    artifacts_path: str
    cache_path: str
    temp_path: str
    network_mode: str
    filesystem_mode: str
    allowed_external_messages: bool


class SandboxManager:
    """Creates managed sandbox directories and runtime metadata per run."""

    def __init__(self, base_dir: Path = Path("storage/sandboxes")) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def provision(
        self,
        run_id: str,
        session_id: str,
        policy_constraints: Dict[str, Any] | None = None,
    ) -> SandboxState:
        constraints = policy_constraints or {}
        root = self.base_dir / run_id
        workspace = root / "workspace"
        artifacts = root / "artifacts"
        cache = root / "cache"
        temp = root / "tmp"

        for target in [root, workspace, artifacts, cache, temp]:
            target.mkdir(parents=True, exist_ok=True)

        network_mode = str(constraints.get("network", "read"))
        filesystem_mode = str(constraints.get("filesystem", "workspace_write"))
        allowed_external_messages = constraints.get("external_messages", "blocked") == "allowed"
        mode = "managed_open" if allowed_external_messages else "managed_guarded"

        state = SandboxState(
            version="sandbox/v0",
            id=new_id("sandbox"),
            run_id=run_id,
            session_id=session_id,
            created_at=utc_now(),
            mode=mode,
            root_path=str(root),
            workspace_path=str(workspace),
            artifacts_path=str(artifacts),
            cache_path=str(cache),
            temp_path=str(temp),
            network_mode=network_mode,
            filesystem_mode=filesystem_mode,
            allowed_external_messages=allowed_external_messages,
        )
        self._write_manifest(root, state)
        return state

    def _write_manifest(self, root: Path, state: SandboxState) -> None:
        (root / "sandbox.json").write_text(
            json.dumps(to_dict(state), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
