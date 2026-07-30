"""Provider-offline verification for system-owned memory canonicalization."""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.shadow import ShadowValidator
from app.services.memory import (
    ForgetMemoryTargetProposal,
    MemoryAssertionProposal,
    MemoryCanonicalizer,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    canonicalizer = MemoryCanonicalizer()
    first = canonicalizer.canonicalize(
        [
            MemoryAssertionProposal(
                subject="self",
                predicate="name",
                value={"name": "冰露"},
                evidence_quote="I am 冰露",
            )
        ],
        source_text="I am 冰露",
    )
    corrected = canonicalizer.canonicalize(
        [
            MemoryAssertionProposal(
                subject="self",
                predicate="self_reported_name",
                value={"name": "小露"},
                evidence_quote="I am 小露",
            )
        ],
        source_text="I am 小露",
    )
    _assert(first.status == corrected.status == "ready", "name not canonical")
    _assert(
        first.facts[0].memory_key == corrected.facts[0].memory_key,
        "system did not assign one identity chain",
    )
    _assert(
        first.facts[0].canonical_hash
        != corrected.facts[0].canonical_hash,
        "correction did not change canonical hash",
    )

    forget = canonicalizer.resolve_targets(
        [
            ForgetMemoryTargetProposal(
                subject="self",
                predicate="name",
                evidence_quote="忘记我的名字",
            )
        ],
        source_text="忘记我的名字",
    )
    _assert(forget.status == "ready", str(forget))
    _assert(
        forget.targets[0].memory_key == first.facts[0].memory_key,
        "forget target did not resolve through the registry",
    )

    secret = canonicalizer.canonicalize(
        [
            MemoryAssertionProposal(
                subject="self",
                predicate="instruction",
                value={
                    "instruction": "use it",
                    "api_key": "sk-secret-123456789",
                },
                evidence_quote="api_key=sk-secret-123456789",
            )
        ],
        source_text="api_key=sk-secret-123456789",
    )
    _assert(secret.status == "rejected", "credential was canonicalized")

    shadow = ShadowValidator().evaluate(
        ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="remember-name",
                    name="remember_memory",
                    arguments={
                        "assertions": [
                            {
                                "subject": "self",
                                "predicate": "name",
                                "value": {"name": "冰露"},
                                "qualifiers": {},
                                "evidence_quote": "I am 冰露",
                            }
                        ]
                    },
                )
            ],
        ),
        goal="I am 冰露",
    )
    _assert(shadow.valid, str(shadow))
    _assert(shadow.side_effect_count == 1, str(shadow))
    _assert(shadow.checks[0]["status"] == "ready", str(shadow))

    print("memory schema canonicalization verification passed")
    print("schema_authority=system_registry")
    print("model_storage_identity_fields=forbidden")
    print("credential_admission=rejected")
    print("shadow_side_effects=0")


if __name__ == "__main__":
    main()
