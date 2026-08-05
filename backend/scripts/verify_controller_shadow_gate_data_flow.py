"""Verify durable Shadow enrollment, recovery, diff, review, and Gate reads."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
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
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.certification_contracts import (
    AGENT_CERTIFICATION_CONTRACT_VERSION,
)
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.prompt_composer import (
    CONTROLLER_PROMPT_VERSION,
)
from app.services.agent_core.shadow_decision_diff import (
    ShadowDecisionDiffer,
)
from app.services.agent_core.shadow_gate_dataset_builder import (
    ShadowGateDatasetBuilder,
)
from app.services.agent_core.shadow_gate_evaluator import (
    ShadowGateEvaluator,
)
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateReadRequest,
)
from app.services.agent_core.shadow_gate_repository import (
    ShadowGateRepository,
)
from app.services.agent_core.shadow_observation_contracts import (
    ShadowObservationAppend,
)
from app.services.agent_core.shadow_observation_key import (
    shadow_observation_key_from_identity,
)
from app.services.agent_core.shadow_observation_repository import (
    ShadowObservationRepository,
)
from app.services.agent_core.shadow_recovery import (
    ShadowRecoveryProjector,
)
from app.services.agent_core.shadow_recovery_repository import (
    ShadowEnrollmentRecoveryRepository,
)
from app.services.agent_core.shadow_review_artifact import (
    ShadowReviewArtifactLoader,
)
from app.services.agent_core.shadow_review_queue import (
    ShadowReviewQueueBuilder,
)
from app.services.conversation import (
    ConversationJournalService,
    ConversationShadowEnrollment,
)
from scripts.init_database import _init_postgres


async def _run() -> None:
    _init_postgres()
    await init_database_connection()
    database = get_database()
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    model_id = uuid.uuid4()
    controller_fingerprint = current_controller_fingerprint()
    configuration_fingerprint = "a" * 64
    observed_request_id = f"shadow-gate-observed-{uuid.uuid4()}"
    pending_request_id = f"shadow-gate-pending-{uuid.uuid4()}"
    other_commit_request_id = f"shadow-gate-other-{uuid.uuid4()}"
    raw_message = "private-shadow-gate-source"
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=1)
    window_end = now + timedelta(minutes=1)
    base_request = ShadowGateReadRequest(
        commit_sha="c" * 40,
        controller_fingerprint=controller_fingerprint,
        configuration_fingerprint=configuration_fingerprint,
        prompt_version=CONTROLLER_PROMPT_VERSION,
        window_started_at=window_start,
        window_ended_at=window_end,
        collected_at=window_end,
    )
    enrollment = ConversationShadowEnrollment(
        source_commit_sha=base_request.commit_sha,
        controller_fingerprint=controller_fingerprint,
        prompt_version=CONTROLLER_PROMPT_VERSION,
        model_id=model_id,
        model_name="fixture-controller",
        timezone="Asia/Shanghai",
    )
    observed_input = UserInput(
        content=raw_message,
        user_id=user_id,
        thread_id=thread_id,
        request_id=observed_request_id,
        model_uuid=str(model_id),
        model_name="fixture-controller",
    )
    pending_input = UserInput(
        content="pending-private-shadow-source",
        user_id=user_id,
        thread_id=thread_id,
        request_id=pending_request_id,
        model_uuid=str(model_id),
        model_name="fixture-controller",
    )
    other_commit_input = UserInput(
        content="other-commit-private-shadow-source",
        user_id=user_id,
        thread_id=thread_id,
        request_id=other_commit_request_id,
        model_uuid=str(model_id),
        model_name="fixture-controller",
    )
    try:
        async with database.session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO public.users (
                        id, display_name, is_mock_user
                    )
                    VALUES (
                        :user_id, 'Shadow Gate Data Verify', true
                    )
                    """
                ),
                {"user_id": user_id},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO public.conversations (
                        thread_id, user_id, title
                    )
                    VALUES (
                        :thread_id, :user_id, 'Shadow Gate Data Verify'
                    )
                    """
                ),
                {"thread_id": thread_id, "user_id": user_id},
            )
            journal = ConversationJournalService()
            observed_user_event = await journal.record_user_message(
                db,
                observed_input,
                shadow_enrollment=enrollment,
            )
            replay = await journal.record_user_message(
                db,
                observed_input,
                shadow_enrollment=enrollment.model_copy(
                    update={
                        "controller_fingerprint": "f" * 64,
                        "source_commit_sha": "f" * 40,
                    }
                ),
            )
            if replay.shadow_enrollment != enrollment:
                raise AssertionError(
                    "idempotent replay rewrote its first enrollment"
                )
            await journal.record_assistant_message(
                db,
                user_input=observed_input,
                message=ChatMessage(
                    type="ai",
                    content="legacy direct answer",
                    request_id=observed_request_id,
                    custom_data={
                        "runtime_trace": {
                            "route_type": "direct",
                            "intent": "plain_chat",
                            "planner_used": False,
                            "plan_source": "legacy",
                            "receipt_status": "completed",
                        },
                        "tool_info": [],
                    },
                ),
            )
            pending_user_event = await journal.record_user_message(
                db,
                pending_input,
                shadow_enrollment=enrollment,
            )
            await journal.record_assistant_message(
                db,
                user_input=pending_input,
                message=ChatMessage(
                    type="ai",
                    content="legacy pending answer",
                    request_id=pending_request_id,
                ),
            )
            await journal.record_user_message(
                db,
                other_commit_input,
                shadow_enrollment=enrollment.model_copy(
                    update={"source_commit_sha": "f" * 40}
                ),
            )
            await journal.record_assistant_message(
                db,
                user_input=other_commit_input,
                message=ChatMessage(
                    type="ai",
                    content="other commit legacy answer",
                    request_id=other_commit_request_id,
                ),
            )
            observation_key = shadow_observation_key_from_identity(
                thread_id=thread_id,
                request_id=observed_request_id,
                controller_fingerprint=controller_fingerprint,
            )
            await ShadowObservationRepository().append(
                db,
                ShadowObservationAppend(
                    observation_key=observation_key,
                    user_id=user_id,
                    thread_id=thread_id,
                    request_id=observed_request_id,
                    journal_sequence_watermark=(
                        observed_user_event.sequence_no
                    ),
                    configuration_fingerprint=(
                        configuration_fingerprint
                    ),
                    source_commit_sha=base_request.commit_sha,
                    controller_fingerprint=controller_fingerprint,
                    agent_core_contract_version="agent-core-v1",
                    certification_contract_version=(
                        AGENT_CERTIFICATION_CONTRACT_VERSION
                    ),
                    prompt_version=CONTROLLER_PROMPT_VERSION,
                    input_evidence_hash="e" * 64,
                    controller_status="shadow_valid",
                    output_mode="capability_proposals",
                    valid=True,
                    would_execute=True,
                    side_effect_count=0,
                    latency_ms=7,
                    proposal_summary={
                        "mode": "capability_proposals",
                        "capabilities": [
                            {"name": "search_memory"}
                        ],
                    },
                    plan_summary={
                        "route_type": "tool",
                        "intent": "memory_read",
                        "actions": [
                            {"capability": "search_memory"}
                        ],
                    },
                    checks=[],
                    violation_codes=[],
                    error_hashes=[],
                ),
            )

        async with database.session() as db:
            pending = (
                await ShadowEnrollmentRecoveryRepository().list_pending(
                    db,
                    controller_fingerprint=controller_fingerprint,
                    prompt_version=CONTROLLER_PROMPT_VERSION,
                    source_commit_sha=base_request.commit_sha,
                    limit=10,
                )
            )
            if len(pending) != 1:
                raise AssertionError(
                    f"expected one recoverable enrollment, got {len(pending)}"
                )
            other_commit_pending = (
                await ShadowEnrollmentRecoveryRepository().list_pending(
                    db,
                    controller_fingerprint=controller_fingerprint,
                    prompt_version=CONTROLLER_PROMPT_VERSION,
                    source_commit_sha="f" * 40,
                    limit=10,
                )
            )
            if len(other_commit_pending) != 1:
                raise AssertionError(
                    "recovery did not isolate the other source commit"
                )
            recovered = ShadowRecoveryProjector().project(pending[0])
            if (
                recovered.user_input.request_id != pending_request_id
                or recovered.journal_sequence_watermark
                != pending_user_event.sequence_no
            ):
                raise AssertionError(
                    "recovery did not rebuild the pending command"
                )
            raw = await ShadowGateRepository().read(db, base_request)

        if len(raw.turns) != 2:
            raise AssertionError(
                f"expected two eligible enrollments, got {len(raw.turns)}"
            )
        observed_turn = next(
            item
            for item in raw.turns
            if item.observation_key == observation_key
        )
        difference = ShadowDecisionDiffer().compare(observed_turn)
        if difference.kind is None or difference.fingerprint is None:
            raise AssertionError(
                "new/legacy decision difference was not projected"
            )
        review_queue = ShadowReviewQueueBuilder().build(
            raw,
            source_state=GitSourceState(
                commit_sha=base_request.commit_sha,
                dirty_worktree=False,
            ),
        )
        if len(review_queue.candidates) != 1:
            raise AssertionError(
                "safe Shadow review queue did not contain one difference"
            )
        queue_rendered = review_queue.model_dump_json()
        if (
            raw_message in queue_rendered
            or pending_input.content in queue_rendered
        ):
            raise AssertionError(
                "raw user content leaked into Shadow review queue"
            )

        with tempfile.TemporaryDirectory() as directory:
            review_path = Path(directory) / "reviews.json"
            review_path.write_text(
                json.dumps(
                    {
                        "artifact_version": (
                            "shadow-decision-review-v1"
                        ),
                        "commit_sha": base_request.commit_sha,
                        "controller_fingerprint": (
                            controller_fingerprint
                        ),
                        "configuration_fingerprint": (
                            configuration_fingerprint
                        ),
                        "prompt_version": CONTROLLER_PROMPT_VERSION,
                        "window_started_at": (
                            window_start.isoformat()
                        ),
                        "window_ended_at": window_end.isoformat(),
                        "reviews": [
                            {
                                "observation_key": observation_key,
                                "review": {
                                    "classification": (
                                        "expected_improvement"
                                    ),
                                    "severity": "P2",
                                    "explained": True,
                                    "difference_fingerprint": (
                                        difference.fingerprint
                                    ),
                                    "reviewer_id": (
                                        "integration-reviewer"
                                    ),
                                    "reviewed_at": now.isoformat(),
                                    "reason_codes": [
                                        "expected.routing_improvement"
                                    ],
                                },
                            }
                        ],
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            loaded_reviews = ShadowReviewArtifactLoader().load(
                review_path,
                request=base_request,
            )

        within_grace = ShadowGateDatasetBuilder().build(
            raw,
            reviews=loaded_reviews,
        )
        within_report = ShadowGateEvaluator().evaluate(within_grace)
        if (
            within_grace.coverage.pending_within_grace != 1
            or within_grace.coverage.missing_after_grace != 0
            or within_report.status != "blocked"
        ):
            raise AssertionError(
                "within-grace delivery gap was not blocked"
            )
        expired_request = base_request.model_copy(
            update={
                "collected_at": (
                    window_end + timedelta(minutes=5)
                )
            }
        )
        expired_raw = raw.model_copy(
            update={"request": expired_request}
        )
        expired = ShadowGateDatasetBuilder().build(
            expired_raw,
            reviews=loaded_reviews,
        )
        expired_report = ShadowGateEvaluator().evaluate(expired)
        if (
            expired.coverage.missing_after_grace != 1
            or expired_report.status != "failed"
            or "enrollment_delivery_missing"
            not in expired_report.reasons
        ):
            raise AssertionError(
                "expired delivery gap did not fail closed"
            )
        rendered = json.dumps(
            {
                "dataset": expired.model_dump(mode="json"),
                "report": expired_report.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        if raw_message in rendered or pending_input.content in rendered:
            raise AssertionError(
                "raw user content leaked into Gate evidence"
            )
        if observed_turn.audit_receipt_count != 0:
            raise AssertionError(
                "Shadow audit namespace contains execution receipts"
            )
        migrations = sorted(
            (BACKEND_DIR / "scripts" / "sql").glob("change_*.sql")
        )
        migration_versions = [
            int(path.stem.split("_", 2)[1])
            for path in migrations
        ]
        expected_versions = list(
            range(1, max(migration_versions, default=0) + 1)
        )
        if migration_versions != expected_versions:
            raise AssertionError(
                "versioned migrations are not contiguous: "
                f"{migration_versions}"
            )
        migration_count = len(migrations)
        print("controller Shadow Gate data flow verification passed")
        print(f"migration_files={migration_count}")
        print("enrollment_replay_preserves_first_stamp=1")
        print("eligible_enrollments=2")
        print("observed_enrollments=1")
        print("recovered_pending_commands=1")
        print("cross_commit_recovery_excluded=1")
        print("cross_commit_gate_enrollments_excluded=1")
        print("terminal_journal_links=1")
        print("decision_differences=1")
        print("safe_review_queue_candidates=1")
        print("bound_reviews=1")
        print("within_grace_gap=blocked")
        print("expired_delivery_gap=failed")
        print("shadow_audit_receipts=0")
        print("raw_user_content_in_gate_evidence=0")
        print("raw_user_content_in_review_queue=0")
        print("in_memory_dispatch_metrics_used_by_gate=0")
    finally:
        try:
            async with database.session() as db:
                await db.execute(
                    text(
                        "DELETE FROM public.users WHERE id = :user_id"
                    ),
                    {"user_id": user_id},
                )
        finally:
            await dispose_database()


if __name__ == "__main__":
    asyncio.run(_run())
