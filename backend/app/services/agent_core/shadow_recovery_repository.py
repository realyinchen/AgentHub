from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_shadow_observation import (
    AgentShadowObservationRecord,
)
from app.models.conversation_event import ConversationEventRecord
from app.services.agent_core.shadow_recovery_contracts import (
    PendingShadowEnrollment,
)
from app.services.conversation.journal_contracts import (
    ConversationShadowEnrollment,
)


class ShadowEnrollmentRecoveryRepository:
    """Read durable Shadow enrollments that have no matching observation."""

    async def list_pending(
        self,
        db: AsyncSession,
        *,
        controller_fingerprint: str,
        prompt_version: str,
        source_commit_sha: str,
        limit: int,
    ) -> list[PendingShadowEnrollment]:
        bounded_limit = max(1, min(int(limit), 1_000))
        enrollment = ConversationEventRecord.shadow_enrollment_json
        statement = (
            select(ConversationEventRecord)
            .outerjoin(
                AgentShadowObservationRecord,
                and_(
                    AgentShadowObservationRecord.thread_id
                    == ConversationEventRecord.thread_id,
                    AgentShadowObservationRecord.request_id
                    == ConversationEventRecord.request_id,
                    AgentShadowObservationRecord.controller_fingerprint
                    == controller_fingerprint,
                ),
            )
            .where(
                ConversationEventRecord.event_type == "user_message",
                enrollment.is_not(None),
                enrollment["schema_version"].astext
                == "agent-shadow-enrollment-v2",
                enrollment["source_commit_sha"].astext
                == source_commit_sha,
                enrollment["controller_fingerprint"].astext
                == controller_fingerprint,
                enrollment["prompt_version"].astext == prompt_version,
                AgentShadowObservationRecord.id.is_(None),
            )
            .order_by(
                ConversationEventRecord.created_at.asc(),
                ConversationEventRecord.id.asc(),
            )
            .limit(bounded_limit)
        )
        result = await db.execute(statement)
        return [
            _pending(record)
            for record in result.scalars().all()
        ]


def _pending(
    record: ConversationEventRecord,
) -> PendingShadowEnrollment:
    if record.shadow_enrollment_json is None:
        raise ValueError("pending Shadow event has no enrollment")
    return PendingShadowEnrollment(
        user_id=record.user_id,
        thread_id=record.thread_id,
        request_id=record.request_id,
        content=record.content,
        journal_sequence_watermark=record.sequence_no,
        enrollment=ConversationShadowEnrollment.model_validate(
            record.shadow_enrollment_json
        ),
    )


__all__ = ["ShadowEnrollmentRecoveryRepository"]
