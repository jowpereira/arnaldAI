from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import importlib.util
import json
import py_compile
import re

from arnaldo.contracts import Capability, new_id, utc_now


class ToolForge:
    """Generates minimal connector scaffolds for missing capabilities."""

    def __init__(
        self,
        base_dir: Path = Path("storage/tool_forge"),
        module_dir: str = "generated",
        index_name: str = "index.json",
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir = self.base_dir / module_dir
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / index_name
        if not self.index_path.exists():
            self.index_path.write_text("[]", encoding="utf-8")

    def forge_missing(self, missing: List[Dict[str, Any]], session_id: str) -> Dict[str, Any]:
        created = []
        failed = []
        capabilities = []
        for item in missing:
            capability_id = item["id"]
            result = self._forge_capability(
                capability_id, session_id, reason=item.get("reason", "missing_capability")
            )
            if result["status"] == "failed":
                failed.append(result)
                continue
            created.append(result)
            capabilities.append(
                self._build_generated_capability(
                    capability_id, result["module_path"], result["status"]
                )
            )

        self._append_index(created + failed)
        return {
            "created": created,
            "failed": failed,
            "capabilities": capabilities,
        }

    def _forge_capability(self, capability_id: str, session_id: str, reason: str) -> Dict[str, Any]:
        timestamp = utc_now()
        safe_name = sanitize_module_name(capability_id)
        module_path = self.generated_dir / f"{safe_name}.py"
        metadata_path = self.generated_dir / f"{safe_name}.json"
        module_path.write_text(render_scaffold(capability_id, timestamp), encoding="utf-8")
        metadata = {
            "id": new_id("tool"),
            "created_at": timestamp,
            "session_id": session_id,
            "capability_id": capability_id,
            "reason": reason,
            "module_path": str(module_path),
            "status": "scaffolded",
        }
        test_result = self._smoke_test(module_path)
        if not test_result["ok"]:
            metadata["status"] = "failed"
            metadata["error"] = test_result["error"]
            metadata_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=True), encoding="utf-8"
            )
            return metadata

        metadata["status"] = "draft"
        metadata["test"] = str(test_result.get("mode", "py_compile_ok"))
        smoke_status = str(test_result.get("status", "")).strip()
        if smoke_status:
            metadata["smoke_status"] = smoke_status
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        return metadata

    def _smoke_test(self, module_path: Path) -> Dict[str, Any]:
        try:
            py_compile.compile(str(module_path), doraise=True)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        try:
            module_name = "tool_forge_smoke_%s" % sanitize_module_name(module_path.stem)
            spec = importlib.util.spec_from_file_location(module_name, str(module_path))
            if spec is None or spec.loader is None:
                return {"ok": False, "error": "spec_creation_failed"}
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            runner = getattr(module, "run", None)
            if not callable(runner):
                return {"ok": False, "error": "run_not_callable"}
            output = runner(
                {
                    "request": "tool_forge_smoke_test",
                    "capability_id": "tool_forge.smoke",
                    "context": {"source": "tool_forge"},
                }
            )
            if not isinstance(output, dict):
                return {"ok": False, "error": "run_output_not_dict"}
            status = str(output.get("status", "")).strip()
            if not status:
                return {"ok": False, "error": "run_output_missing_status"}
            return {"ok": True, "mode": "py_compile_and_run_ok", "status": status}
        except Exception as exc:
            return {"ok": False, "error": "run_failed: %s" % exc}

    def _build_generated_capability(
        self, capability_id: str, module_path: str, status: str
    ) -> Capability:
        return Capability(
            id=capability_id,
            name=f"Generated {capability_id}",
            description="Conector gerado automaticamente pelo ToolForge.",
            inputs={"payload": "object"},
            outputs={"status": "object", "data": "object"},
            risk={
                "level": "medium",
                "health": "degraded" if status == "draft" else "error",
                "reasons": ["auto_generated_scaffold"],
            },
            policies={
                "requires_approval": False,
                "maturity": status,
                "module_path": module_path,
            },
        )

    def _append_index(self, entries: List[Dict[str, Any]]) -> None:
        current = json.loads(self.index_path.read_text(encoding="utf-8"))
        current.extend(entries)
        self.index_path.write_text(
            json.dumps(current, indent=2, ensure_ascii=True), encoding="utf-8"
        )


def sanitize_module_name(capability_id: str) -> str:
    normalized = capability_id.strip().lower().replace(".", "_")
    return re.sub(r"[^a-z0-9_]+", "_", normalized)


def render_scaffold(capability_id: str, created_at: str) -> str:
    # Sanitiza inputs para prevenir injeção de código via string interpolation
    safe_id = re.sub(r"[^a-zA-Z0-9_.\-]+", "_", capability_id.strip())
    safe_ts = re.sub(r"[^a-zA-Z0-9_:+.\-]+", "_", created_at.strip())
    return '''from __future__ import annotations

from typing import Any, Dict

TOOL_META = {
    "capability_id": %s,
    "created_at": %s,
    "status": "draft",
}


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Connector scaffold. Replace this body with real integration logic."""
    return {
        "status": "not_implemented",
        "capability_id": TOOL_META["capability_id"],
        "received_keys": sorted(payload.keys()),
        "message": "scaffold gerado automaticamente; implemente a chamada real do conector",
    }
''' % (
        repr(safe_id),
        repr(safe_ts),
    )
