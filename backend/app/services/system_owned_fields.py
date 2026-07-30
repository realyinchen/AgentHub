from __future__ import annotations

from typing import Any


SYSTEM_IDENTITY_FIELDS = frozenset(
    {
        "action_id",
        "canonical_hash",
        "chain_id",
        "conversation_id",
        "idempotency_key",
        "lease_expires_at",
        "lease_owner",
        "memory_id",
        "memory_key",
        "origin_request_id",
        "permissions",
        "plan_id",
        "plan_version_id",
        "previous_version_id",
        "receipt_id",
        "request_id",
        "revision_of",
        "schema_key",
        "schema_version",
        "source_commit_sha",
        "source_event_id",
        "state_version",
        "superseded_by",
        "task_id",
        "tenant_id",
        "thread_id",
        "user_id",
        "valid_from",
        "valid_to",
        "version_no",
        "workspace_id",
    }
)

SECRET_FIELDS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "refresh_token",
    }
)

MODEL_CONTROL_FIELDS = frozenset({"operation"})

MODEL_PROPOSAL_FORBIDDEN_FIELDS = frozenset(
    SYSTEM_IDENTITY_FIELDS | SECRET_FIELDS | MODEL_CONTROL_FIELDS
)

ACTION_ARGUMENT_FORBIDDEN_FIELDS = frozenset(
    SYSTEM_IDENTITY_FIELDS | SECRET_FIELDS
)


def find_forbidden_paths(
    value: Any,
    *,
    forbidden_fields: frozenset[str],
    root: str = "arguments",
) -> set[str]:
    """Return nested paths whose keys violate one named policy."""

    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{root}.{key_text}"
            if key_text.casefold() in forbidden_fields:
                found.add(child_path)
            found.update(
                find_forbidden_paths(
                    child,
                    forbidden_fields=forbidden_fields,
                    root=child_path,
                )
            )
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.update(
                find_forbidden_paths(
                    child,
                    forbidden_fields=forbidden_fields,
                    root=f"{root}[{index}]",
                )
            )
    return found


__all__ = [
    "ACTION_ARGUMENT_FORBIDDEN_FIELDS",
    "MODEL_CONTROL_FIELDS",
    "MODEL_PROPOSAL_FORBIDDEN_FIELDS",
    "SECRET_FIELDS",
    "SYSTEM_IDENTITY_FIELDS",
    "find_forbidden_paths",
]
