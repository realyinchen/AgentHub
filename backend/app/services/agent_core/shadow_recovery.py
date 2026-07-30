from __future__ import annotations

from app.infra.database import get_database
from app.schemas.chat import UserInput
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.prompt_composer import (
    CONTROLLER_PROMPT_VERSION,
)
from app.services.agent_core.shadow_dispatcher import (
    ShadowControllerCommand,
)
from app.services.agent_core.shadow_recovery_contracts import (
    PendingShadowEnrollment,
)
from app.services.agent_core.shadow_recovery_repository import (
    ShadowEnrollmentRecoveryRepository,
)


class ShadowRecoveryProjector:
    """Rebuild a command only from one immutable Journal enrollment."""

    def project(
        self,
        pending: PendingShadowEnrollment,
    ) -> ShadowControllerCommand:
        enrollment = pending.enrollment
        return ShadowControllerCommand(
            user_input=UserInput(
                content=pending.content,
                user_id=pending.user_id,
                thread_id=pending.thread_id,
                request_id=pending.request_id,
                model_name=enrollment.model_name,
                model_uuid=str(enrollment.model_id),
                timezone=enrollment.timezone,
            ),
            model_name=enrollment.model_name,
            journal_sequence_watermark=(
                pending.journal_sequence_watermark
            ),
            controller_fingerprint=(
                enrollment.controller_fingerprint
            ),
            source_commit_sha=enrollment.source_commit_sha,
        )


class ShadowEnrollmentRecoverySource:
    """Load and project unfinished enrollments for the current build."""

    def __init__(
        self,
        *,
        repository: ShadowEnrollmentRecoveryRepository | None = None,
        projector: ShadowRecoveryProjector | None = None,
        database_provider=None,
        source_commit_sha: str,
    ) -> None:
        self._repository = (
            repository or ShadowEnrollmentRecoveryRepository()
        )
        self._projector = projector or ShadowRecoveryProjector()
        self._database_provider = database_provider or get_database
        self._source_commit_sha = source_commit_sha

    async def pending(
        self,
        *,
        limit: int,
    ) -> list[ShadowControllerCommand]:
        database = self._database_provider()
        async with database.session() as db:
            records = await self._repository.list_pending(
                db,
                controller_fingerprint=(
                    current_controller_fingerprint()
                ),
                prompt_version=CONTROLLER_PROMPT_VERSION,
                source_commit_sha=self._source_commit_sha,
                limit=limit,
            )
        return [
            self._projector.project(record)
            for record in records
        ]


__all__ = [
    "ShadowEnrollmentRecoverySource",
    "ShadowRecoveryProjector",
]
