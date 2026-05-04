from __future__ import annotations

from typing import Any, Dict, List

from arnaldo.contracts import Capability, to_dict


class CapabilityRegistry:
    """Typed map of what this local runtime can currently do."""

    def __init__(self) -> None:
        self._capabilities = {capability.id: capability for capability in default_capabilities()}

    def resolve(self, needs: List[Dict[str, Any]]) -> Dict[str, Any]:
        available = []
        missing = []
        for need in needs:
            capability_id = need["id"]
            capability = self._capabilities.get(capability_id)
            if capability:
                available.append(to_dict(capability))
            elif need.get("required", False):
                missing.append(
                    {
                        "id": capability_id,
                        "reason": "capability_not_registered",
                        "severity": "high",
                    }
                )
        return {
            "available": available,
            "missing": missing,
        }


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
        risk={"level": "low", "reasons": ["local_deterministic"]},
        policies={
            "requires_approval": False,
            "allowed_data_classes": ["public", "user_provided"],
        },
    )
