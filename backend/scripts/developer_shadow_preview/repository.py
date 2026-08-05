from __future__ import annotations

import asyncio
import uuid
from time import monotonic

from sqlalchemy import text

from app.infra.database import get_database
from app.services.agent_certification import get_agent_mode_admission
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateRawWindow,
    ShadowGateReadRequest,
)
from app.services.agent_core.shadow_gate_repository import ShadowGateRepository
from app.services.agent_core.shadow_observation_key import (
    shadow_audit_request_id,
)
from scripts.developer_shadow_preview.contracts import (
    DeveloperShadowBusinessWrites,
    DeveloperShadowCleanup,
)
from scripts.developer_shadow_preview.admission import (
    DeveloperShadowAdmissionCandidate,
    DeveloperShadowModelProfile,
)


class DeveloperShadowRepositoryError(RuntimeError):
    """Fail-closed persistence error with a stable reason code."""


class DeveloperShadowPreviewRepository:
    """Own all PostgreSQL reads and mock-scope cleanup for one preview."""

    async def read_admission_candidate(
        self,
        *,
        model_id: uuid.UUID,
        source_state: GitSourceState,
    ) -> DeveloperShadowAdmissionCandidate:
        async with get_database().session() as db:
            admission = await get_agent_mode_admission(
                db,
                model_id,
                source_commit_sha=source_state.commit_sha,
            )
            configured = (
                await db.execute(
                    text(
                        """
                        SELECT model_type, thinking, is_active
                        FROM public.models WHERE id = :model_id
                        """
                    ),
                    {"model_id": model_id},
                )
            ).mappings().one_or_none()
        profile = None
        if configured is not None:
            profile = DeveloperShadowModelProfile(
                model_type=str(configured["model_type"]),
                configured_thinking=bool(configured["thinking"]),
                is_active=bool(configured["is_active"]),
            )
        return DeveloperShadowAdmissionCandidate(
            admission=admission,
            model_profile=profile,
        )

    async def seed_mock_user(self, user_id: uuid.UUID) -> None:
        async with get_database().session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO public.users (id, display_name, is_mock_user)
                    VALUES (:user_id, 'Developer Shadow Preview', true)
                    """
                ),
                {"user_id": user_id},
            )

    async def poll_observations(
        self,
        *,
        user_id: uuid.UUID,
        request_ids: list[str],
        timeout_seconds: float,
    ) -> None:
        deadline = monotonic() + timeout_seconds
        while True:
            async with get_database().session() as db:
                count = await db.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM public.agent_shadow_observations
                        WHERE user_id = :user_id
                          AND request_id = ANY(
                            CAST(:request_ids AS varchar[])
                          )
                        """
                    ),
                    {"user_id": user_id, "request_ids": request_ids},
                )
            if int(count or 0) == len(request_ids):
                return
            if monotonic() >= deadline:
                raise DeveloperShadowRepositoryError(
                    "shadow_observation_timeout"
                )
            await asyncio.sleep(1)

    async def read_window(
        self,
        request: ShadowGateReadRequest,
    ) -> ShadowGateRawWindow:
        async with get_database().session() as db:
            return await ShadowGateRepository().read(db, request)

    async def read_business_writes(
        self,
        *,
        user_id: uuid.UUID,
        request_ids: list[str],
        raw: ShadowGateRawWindow,
    ) -> DeveloperShadowBusinessWrites:
        audit_ids = [
            shadow_audit_request_id(turn.observation_key)
            for turn in raw.turns
        ]
        async with get_database().session() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                          (SELECT COUNT(*) FROM public.memory_events
                           WHERE user_id = :user_id) AS memory_events,
                          (SELECT COUNT(*) FROM public.task_states
                           WHERE user_id = :user_id) AS task_states,
                          (SELECT COUNT(*)
                           FROM public.task_plan_versions p
                           JOIN public.task_states t
                             ON t.task_id = p.task_id
                           WHERE t.user_id = :user_id)
                             AS task_plan_versions,
                          (SELECT COUNT(*) FROM public.research_runs
                           WHERE user_id = :user_id) AS research_runs,
                          (SELECT COUNT(*)
                           FROM public.action_execution_receipts
                           WHERE request_id = ANY(
                             CAST(:audit_ids AS varchar[])
                           )) AS shadow_audit_receipts,
                          (SELECT COUNT(*)
                           FROM public.action_execution_receipts
                           WHERE request_id = ANY(
                             CAST(:request_ids AS varchar[])
                           )) AS legacy_request_receipts
                        """
                    ),
                    {
                        "user_id": user_id,
                        "audit_ids": audit_ids,
                        "request_ids": request_ids,
                    },
                )
            ).mappings().one()
        return DeveloperShadowBusinessWrites(**dict(row))

    async def cleanup_mock_scope(
        self,
        *,
        user_id: uuid.UUID,
        request_ids: list[str],
        audit_ids: list[str],
    ) -> DeveloperShadowCleanup:
        errors: list[str] = []
        try:
            await self._delete_test_receipts(request_ids + audit_ids)
        except Exception:
            errors.append("receipt_cleanup_failed")
        try:
            await self._delete_mock_user(user_id)
        except Exception:
            errors.append("mock_user_cleanup_failed")
        try:
            cleanup = await self._cleanup_counts(
                user_id=user_id,
                request_ids=request_ids,
                audit_ids=audit_ids,
            )
        except Exception:
            errors.append("cleanup_verification_failed")
            cleanup = None
        if errors or cleanup is None:
            raise DeveloperShadowRepositoryError(";".join(errors))
        return cleanup

    async def _delete_test_receipts(self, request_ids: list[str]) -> None:
        if not request_ids:
            return
        async with get_database().session() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM public.action_execution_receipts
                    WHERE request_id = ANY(
                      CAST(:request_ids AS varchar[])
                    )
                    """
                ),
                {"request_ids": request_ids},
            )

    async def _delete_mock_user(self, user_id: uuid.UUID) -> None:
        async with get_database().session() as db:
            deleted = await db.execute(
                text(
                    """
                    DELETE FROM public.users
                    WHERE id = :user_id AND is_mock_user = true
                    """
                ),
                {"user_id": user_id},
            )
            if deleted.rowcount != 1:
                raise DeveloperShadowRepositoryError(
                    "mock_user_cleanup_target_missing"
                )

    async def _cleanup_counts(
        self,
        *,
        user_id: uuid.UUID,
        request_ids: list[str],
        audit_ids: list[str],
    ) -> DeveloperShadowCleanup:
        receipt_ids = request_ids + audit_ids
        async with get_database().session() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                          (SELECT COUNT(*) FROM public.users
                           WHERE id = :user_id) AS users,
                          (SELECT COUNT(*) FROM public.conversations
                           WHERE user_id = :user_id) AS conversations,
                          (SELECT COUNT(*) FROM public.conversation_events
                           WHERE user_id = :user_id)
                             AS conversation_events,
                          (SELECT COUNT(*)
                           FROM public.agent_shadow_observations
                           WHERE user_id = :user_id)
                             AS shadow_observations,
                          (SELECT COUNT(*) FROM public.memory_events
                           WHERE user_id = :user_id) AS memory_events,
                          (SELECT COUNT(*) FROM public.task_states
                           WHERE user_id = :user_id) AS task_states,
                          (SELECT COUNT(*)
                           FROM public.task_plan_versions p
                           JOIN public.task_states t
                             ON t.task_id = p.task_id
                           WHERE t.user_id = :user_id)
                             AS task_plan_versions,
                          (SELECT COUNT(*) FROM public.research_runs
                           WHERE user_id = :user_id) AS research_runs,
                          (SELECT COUNT(*)
                           FROM public.action_execution_receipts
                           WHERE request_id = ANY(
                             CAST(:receipt_ids AS varchar[])
                           )) AS request_receipts
                        """
                    ),
                    {
                        "user_id": user_id,
                        "receipt_ids": receipt_ids,
                    },
                )
            ).mappings().one()
        return DeveloperShadowCleanup(**dict(row))


__all__ = [
    "DeveloperShadowPreviewRepository",
    "DeveloperShadowRepositoryError",
]
