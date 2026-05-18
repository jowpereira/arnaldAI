from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from arnaldo.contracts import Capability, to_dict


class CapabilityRegistry:
    """Typed map of what this local runtime can currently do."""

    def __init__(
        self,
        capabilities: Optional[List[Capability]] = None,
        registry_path: Path = Path("storage/capability_registry.json"),
    ) -> None:
        base = capabilities if capabilities is not None else default_capabilities()
        self.registry_path = Path(registry_path)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._capabilities: Dict[str, Capability] = {capability.id: capability for capability in base}
        self._default_ids = set(self._capabilities.keys())
        self._load_dynamic_capabilities()

    def resolve(self, needs: List[Dict[str, Any]]) -> Dict[str, Any]:
        available = []
        missing = []
        degraded = []
        for need in needs:
            capability_id = need["id"]
            capability = self._capabilities.get(capability_id)
            if capability:
                health = capability.risk.get("health", "stable")
                bucket = degraded if health != "stable" else available
                bucket.append(to_dict(capability))
            elif need.get("required", False):
                missing.append(
                    {
                        "id": capability_id,
                        "reason": "capability_not_registered",
                        "severity": "high",
                    }
                )
            else:
                degraded.append(
                    {
                        "id": capability_id,
                        "reason": "optional_capability_not_registered",
                        "severity": "low",
                        "risk": {
                            "level": "low",
                            "health": "degraded",
                            "reasons": ["optional_missing"],
                        },
                        "policies": {
                            "requires_approval": False,
                            "maturity": "scaffolded",
                        },
                    }
                )
        return {
            "available": available,
            "missing": missing,
            "degraded": degraded,
        }

    def register(self, capability: Capability, persist: bool = True) -> None:
        self._capabilities[capability.id] = capability
        if persist:
            self._persist_dynamic_capabilities()

    def remove(self, capability_id: str, persist: bool = True) -> None:
        self._capabilities.pop(capability_id, None)
        if persist:
            self._persist_dynamic_capabilities()

    def list_all(self) -> List[Capability]:
        return list(self._capabilities.values())

    def get(self, capability_id: str) -> Optional[Capability]:
        return self._capabilities.get(capability_id)

    def _load_dynamic_capabilities(self) -> None:
        if not self.registry_path.exists():
            return
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        for item in payload:
            capability = capability_from_dict(item)
            self._capabilities[capability.id] = capability

    def _persist_dynamic_capabilities(self) -> None:
        dynamic = [
            to_dict(capability)
            for capability_id, capability in self._capabilities.items()
            if capability_id not in self._default_ids
        ]
        self.registry_path.write_text(
            json.dumps(dynamic, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )


def default_capabilities() -> List[Capability]:
    return [
        capability("intent.structure", "Structure Intent", "transformar pedido humano em contrato declarativo"),
        capability("work.decompose", "Decompose Work", "quebrar trabalho em passos verificaveis"),
        capability("organization.generate", "Generate Organization", "criar organizacao temporaria generica"),
        capability("artifact.draft", "Draft Artifact", "gerar artefato textual inicial"),
        capability("validation.critic_review", "Critic Review", "apontar lacunas e riscos"),
        capability("evidence.record", "Record Evidence", "registrar eventos e decisoes em ledger local"),
    ]


def capability(capability_id: str, name: str, description: str) -> Capability:
    return Capability(
        id=capability_id,
        name=name,
        description=description,
        inputs={"contract": "object"},
        outputs={"result": "object"},
        risk={"level": "low", "reasons": ["local_deterministic"], "health": "stable"},
        policies={
            "requires_approval": False,
            "allowed_data_classes": ["public", "user_provided"],
        },
    )


def capability_from_dict(payload: Dict[str, Any]) -> Capability:
    return Capability(
        id=payload["id"],
        name=payload["name"],
        description=payload["description"],
        inputs=payload.get("inputs", {}),
        outputs=payload.get("outputs", {}),
        risk=payload.get("risk", {}),
        policies=payload.get("policies", {}),
    )
