from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_shadow_observation import (
    AgentShadowObservationRecord,
)
from app.services.agent_core.shadow_observation_contracts import (
    ShadowObservation,
    ShadowObservationAppend,
)


class ShadowObservationRepository:
    """Append or replay one immutable Shadow observation."""

    async def append(
        self,
        db: AsyncSession,
        candidate: ShadowObservationAppend,
    ) -> ShadowObservation:
        statement = (
            insert(AgentShadowObservationRecord)
            .values(candidate.model_dump(mode="python"))
            .on_conflict_do_nothing(
                index_elements=[
                    AgentShadowObservationRecord.observation_key
                ]
            )
            .returning(AgentShadowObservationRecord)
        )
        result = await db.execute(statement)
        record = result.scalar_one_or_none()
        if record is None:
            replay = await db.execute(
                select(AgentShadowObservationRecord).where(
                    AgentShadowObservationRecord.observation_key
                    == candidate.observation_key
                )
            )
            record = replay.scalar_one()
        return observation_from_record(record)


def observation_from_record(
    record: AgentShadowObservationRecord,
) -> ShadowObservation:
    return ShadowObservation(
        id=record.id,
        observation_key=record.observation_key,
        user_id=record.user_id,
        thread_id=record.thread_id,
        request_id=record.request_id,
        journal_sequence_watermark=(
            record.journal_sequence_watermark
        ),
        model_id=record.model_id,
        certification_id=record.certification_id,
        configuration_fingerprint=(
            record.configuration_fingerprint
        ),
        source_commit_sha=record.source_commit_sha,
        controller_fingerprint=record.controller_fingerprint,
        agent_core_contract_version=(
            record.agent_core_contract_version
        ),
        certification_contract_version=(
            record.certification_contract_version
        ),
        prompt_version=record.prompt_version,
        context_snapshot_hash=record.context_snapshot_hash,
        input_evidence_hash=record.input_evidence_hash,
        controller_status=record.controller_status,
        output_mode=record.output_mode,
        valid=record.valid,
        would_execute=record.would_execute,
        side_effect_count=record.side_effect_count,
        latency_ms=record.latency_ms,
        proposal_summary=dict(record.proposal_summary or {}),
        plan_summary=dict(record.plan_summary or {}),
        checks=list(record.checks or []),
        violation_codes=list(record.violation_codes or []),
        error_hashes=list(record.error_hashes or []),
        created_at=record.created_at,
    )


__all__ = [
    "ShadowObservationRepository",
    "observation_from_record",
]
