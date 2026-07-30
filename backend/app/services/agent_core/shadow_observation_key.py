from __future__ import annotations

from app.services.agent_core.shadow_dispatcher import (
    ShadowControllerCommand,
)
from app.services.agent_core.shadow_evidence import hash_shadow_json
from uuid import UUID


def shadow_observation_key(
    command: ShadowControllerCommand,
    controller_fingerprint: str,
) -> str:
    """Return the stable identity for one request/Controller observation."""

    return hash_shadow_json(
        _identity_material(
            thread_id=command.user_input.thread_id,
            request_id=command.user_input.request_id,
            controller_fingerprint=controller_fingerprint,
        )
    )


def shadow_observation_key_from_identity(
    *,
    thread_id: UUID,
    request_id: str,
    controller_fingerprint: str,
) -> str:
    return hash_shadow_json(
        _identity_material(
            thread_id=thread_id,
            request_id=request_id,
            controller_fingerprint=controller_fingerprint,
        )
    )


def _identity_material(
    *,
    thread_id: UUID,
    request_id: str,
    controller_fingerprint: str,
) -> dict[str, str]:
    return (
        {
            "thread_id": str(thread_id),
            "request_id": request_id,
            "controller_fingerprint": controller_fingerprint,
        }
    )


def shadow_audit_request_id(observation_key: str) -> str:
    """Derive the internal ledger namespace used only by Shadow dry-runs."""

    candidate = str(observation_key or "").strip().lower()
    if (
        len(candidate) != 64
        or any(character not in "0123456789abcdef" for character in candidate)
    ):
        raise ValueError("Shadow observation key must be a SHA-256 hex digest")
    return f"shadow-audit:{candidate}"


__all__ = [
    "shadow_audit_request_id",
    "shadow_observation_key",
    "shadow_observation_key_from_identity",
]
