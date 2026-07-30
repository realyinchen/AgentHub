"""Verify non-business Shadow telemetry, replay, and Journal linkage."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)
from app.schemas.chat import ChatMessage, UserInput
from app.services.agent_core.context_assembler import (
    ConversationContextLoader,
)
from app.services.agent_core.gateway import AgentControllerAttempt
from app.services.agent_core.shadow_dispatcher import (
    ShadowControllerCommand,
)
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.shadow_observation_projector import (
    ShadowObservationProjector,
)
from app.services.agent_core.shadow_observation_key import (
    shadow_audit_request_id,
)
from app.services.agent_core.shadow_observation_repository import (
    ShadowObservationRepository,
)
from app.services.conversation import ConversationJournalService
from scripts.init_database import _init_postgres


async def _run() -> None:
    _init_postgres()
    await init_database_connection()
    database = get_database()
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    request_id = f"shadow-observation-{uuid.uuid4()}"
    raw_message = "private-shadow-source-text"
    prior_input = UserInput(
        content="prior-visible-turn",
        user_id=user_id,
        thread_id=thread_id,
        request_id=f"prior-{uuid.uuid4()}",
    )
    user_input = UserInput(
        content=raw_message,
        user_id=user_id,
        thread_id=thread_id,
        request_id=request_id,
    )
    future_input = UserInput(
        content="future-must-not-enter-shadow",
        user_id=user_id,
        thread_id=thread_id,
        request_id=f"future-{uuid.uuid4()}",
    )
    attempt = AgentControllerAttempt(
        mode="shadow",
        status="denied",
        reason="certification_missing",
    )
    projector = ShadowObservationProjector()
    repository = ShadowObservationRepository()
    try:
        async with database.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.users (
                        id,
                        display_name,
                        is_mock_user
                    )
                    VALUES (
                        :user_id,
                        'Shadow Observation Verify',
                        true
                    )
                    """
                ),
                {"user_id": user_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO public.conversations (
                        thread_id,
                        user_id,
                        title
                    )
                    VALUES (
                        :thread_id,
                        :user_id,
                        'Shadow Observation Verify'
                    )
                    """
                ),
                {
                    "thread_id": thread_id,
                    "user_id": user_id,
                },
            )
            journal = ConversationJournalService()
            await journal.record_user_message(
                session,
                prior_input,
            )
            await journal.record_assistant_message(
                session,
                user_input=prior_input,
                message=ChatMessage(
                    type="ai",
                    content="prior-visible-reply",
                    request_id=prior_input.request_id,
                ),
            )
            user_event = await journal.record_user_message(
                session,
                user_input,
            )
            await journal.record_user_message(
                session,
                future_input,
            )
            await journal.record_assistant_message(
                session,
                user_input=future_input,
                message=ChatMessage(
                    type="ai",
                    content="future-must-not-enter-shadow-reply",
                    request_id=future_input.request_id,
                ),
            )

            material = await ConversationContextLoader().load(
                session,
                user_id=user_id,
                thread_id=thread_id,
                exclude_request_id=request_id,
                through_sequence=user_event.sequence_no,
            )

        bounded_content = [
            event.content for event in material.events
        ]
        if bounded_content != [
            "prior-visible-turn",
            "prior-visible-reply",
        ]:
            raise AssertionError(
                "Shadow context crossed its Journal sequence watermark: "
                f"{bounded_content}"
            )

        command = ShadowControllerCommand(
            user_input=user_input,
            model_name="fixture-controller",
            journal_sequence_watermark=user_event.sequence_no,
            controller_fingerprint=(
                current_controller_fingerprint()
            ),
            source_commit_sha="c" * 40,
        )
        first_candidate = projector.project(
            command,
            attempt,
            latency_ms=3,
        )
        replay_candidate = projector.project(
            command,
            attempt,
            latency_ms=99,
        )
        async with database.session() as session:
            first = await repository.append(
                session,
                first_candidate,
            )
            replay = await repository.append(
                session,
                replay_candidate,
            )

        if first.id != replay.id:
            raise AssertionError(
                "same request/controller fingerprint duplicated observation"
            )

        async with database.session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS observation_count,
                        COUNT(e.id) AS journal_links,
                        MIN(o.journal_sequence_watermark)
                            AS observation_watermark,
                        MIN(o.source_commit_sha) AS source_commit_sha,
                        MIN(e.sequence_no) AS journal_watermark,
                        MIN(o.proposal_summary::text) AS proposal_text,
                        MIN(o.plan_summary::text) AS plan_text
                    FROM public.agent_shadow_observations o
                    LEFT JOIN public.conversation_events e
                      ON e.thread_id = o.thread_id
                     AND e.request_id = o.request_id
                     AND e.event_type = 'user_message'
                    WHERE o.observation_key = :observation_key
                    """
                ),
                {"observation_key": first.observation_key},
            )
            row = result.one()
            column = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name =
                          'agent_capability_certifications'
                      AND column_name = 'controller_fingerprint'
                    """
                )
            )
            controller_column_count = int(column.scalar_one())
            audit_receipts = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM public.action_execution_receipts
                    WHERE request_id = :audit_request_id
                    """
                ),
                {
                    "audit_request_id": shadow_audit_request_id(
                        first.observation_key
                    )
                },
            )
            audit_receipt_count = int(
                audit_receipts.scalar_one()
            )

        serialized_projection = json.dumps(
            {
                "proposal": row.proposal_text,
                "plan": row.plan_text,
            },
            ensure_ascii=False,
        )
        if int(row.observation_count) != 1:
            raise AssertionError("observation replay was not idempotent")
        if int(row.journal_links) != 1:
            raise AssertionError(
                "observation cannot join its authoritative Journal source"
            )
        if int(row.observation_watermark) != int(row.journal_watermark):
            raise AssertionError(
                "observation watermark differs from user Journal source"
            )
        if row.source_commit_sha != "c" * 40:
            raise AssertionError(
                "observation lost its deployment source commit"
            )
        if raw_message in serialized_projection:
            raise AssertionError(
                "raw user input leaked into Shadow telemetry"
            )
        if controller_column_count != 1:
            raise AssertionError(
                "certification controller fingerprint migration missing"
            )
        if audit_receipt_count != 0:
            raise AssertionError(
                "Shadow audit request id produced execution Receipts"
            )

        migration_count = len(
            list((BACKEND_DIR / "scripts" / "sql").glob("*.sql"))
        )
        print("controller shadow observation verification passed")
        print(f"migration_files={migration_count}")
        print("observation_rows=1")
        print("replay_rows=1")
        print("journal_links=1")
        print("journal_watermark_match=1")
        print("source_commit_match=1")
        print("future_journal_events_in_shadow_context=0")
        print("raw_user_content_in_telemetry=0")
        print("controller_fingerprint_column=1")
        print("shadow_audit_receipts=0")
    finally:
        await dispose_database()


if __name__ == "__main__":
    asyncio.run(_run())
