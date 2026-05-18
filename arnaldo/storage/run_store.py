from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json


class RunStore:
    def __init__(self, base_dir: Path, run_id: str) -> None:
        self.base_dir = Path(base_dir)
        self.run_id = run_id
        self.run_dir = self.base_dir / run_id

    def create(self) -> "RunStore":
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self

    def path(self, name: str) -> Path:
        return self.run_dir / name

    def write_json(self, name: str, payload: Dict[str, Any]) -> Path:
        path = self.path(name)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return path

    def append_jsonl(self, name: str, payload: Dict[str, Any]) -> Path:
        path = self.path(name)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True))
            handle.write("\n")
        return path

    def write_text(self, name: str, content: str) -> Path:
        path = self.path(name)
        path.write_text(content, encoding="utf-8")
        return path

    def hash_file(self, name: str) -> str:
        path = self.path(name)
        if not path.exists():
            return ""
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()
