from __future__ import annotations

from uuid import UUID
from typing import Callable, Literal

from app.schemas.chat import UserInput
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.prompt_composer import (
    CONTROLLER_PROMPT_VERSION,
)
from app.services.agent_core.release_identity import (
    require_release_commit_sha,
)
from app.services.conversation.journal_contracts import (
    ConversationShadowEnrollment,
    StoredConversationShadowEnrollment,
)
from app.services.agent_core.contracts import AgentCoreModel


ShadowEnrollmentMode = Literal["off", "shadow", "live"]


class ShadowEnrollmentPreparation(AgentCoreModel):
    user_input: UserInput
    resolved_model_name: str | None = None
    enrollment: ConversationShadowEnrollment | None = None


def prepare_shadow_enrollment(
    user_input: UserInput,
    *,
    mode: ShadowEnrollmentMode,
    model_resolver: Callable[[str | None], str | None],
    source_commit_sha: str | None,
) -> ShadowEnrollmentPreparation:
    """Resolve and stamp only the Shadow path; off/live remain untouched."""

    if mode != "shadow":
        return ShadowEnrollmentPreparation(user_input=user_input)
    release_commit = require_release_commit_sha(source_commit_sha)
    requested_model = user_input.model_uuid or user_input.model_name
    resolved_model_name = model_resolver(requested_model)
    if not resolved_model_name:
        return ShadowEnrollmentPreparation(user_input=user_input)
    prepared_input = (
        user_input
        if user_input.model_name == resolved_model_name
        else user_input.model_copy(
            update={"model_name": resolved_model_name}
        )
    )
    return ShadowEnrollmentPreparation(
        user_input=prepared_input,
        resolved_model_name=resolved_model_name,
        enrollment=build_shadow_enrollment(
            prepared_input,
            resolved_model_name=resolved_model_name,
            source_commit_sha=release_commit,
        ),
    )


def build_shadow_enrollment(
    user_input: UserInput,
    *,
    resolved_model_name: str,
    source_commit_sha: str,
) -> ConversationShadowEnrollment | None:
    """Stamp one eligible user event without copying conversation identity."""

    try:
        model_id = UUID(str(user_input.model_uuid or ""))
    except (TypeError, ValueError):
        return None
    model_name = str(resolved_model_name or "").strip()
    if not model_name:
        return None
    return ConversationShadowEnrollment(
        source_commit_sha=require_release_commit_sha(
            source_commit_sha
        ),
        controller_fingerprint=current_controller_fingerprint(),
        prompt_version=CONTROLLER_PROMPT_VERSION,
        model_id=model_id,
        model_name=model_name,
        timezone=user_input.timezone,
    )


def is_current_shadow_enrollment(
    enrollment: StoredConversationShadowEnrollment | None,
    *,
    source_commit_sha: str,
) -> bool:
    """Return whether an immutable stamp belongs to this Controller build."""

    return bool(
        enrollment is not None
        and isinstance(enrollment, ConversationShadowEnrollment)
        and enrollment.source_commit_sha
        == require_release_commit_sha(source_commit_sha)
        and enrollment.controller_fingerprint
        == current_controller_fingerprint()
        and enrollment.prompt_version == CONTROLLER_PROMPT_VERSION
    )


__all__ = [
    "build_shadow_enrollment",
    "is_current_shadow_enrollment",
    "prepare_shadow_enrollment",
    "ShadowEnrollmentPreparation",
]
