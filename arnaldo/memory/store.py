from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
import json


@dataclass
class MemoryRecord:
    id: str
    kind: str
    payload: Dict[str, Any]


class MemoryStore:
    """Persist simple episodic/semantic records for future runs."""

    def __init__(self, base_dir: Path = Path("storage/memory")) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def append(self, record: MemoryRecord) -> None:
        target = self.base_dir / f"{record.kind}.jsonl"
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "id": record.id,
                "kind": record.kind,
                "payload": record.payload,
            }, ensure_ascii=True))
            handle.write("\n")

    def load(self, kind: str) -> List[Dict[str, Any]]:
        target = self.base_dir / f"{kind}.jsonl"
        if not target.exists():
            return []
        return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line]
