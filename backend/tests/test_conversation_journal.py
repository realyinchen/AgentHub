from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from app.services.conversation import (
    AppendConversationEvent,
    AppendConversationLifecycleEvent,
    ConversationJournalEvent,
    ConversationShadowEnrollment,
    ConversationReadRequest,
    project_journal_window,
    read_journal_events,
)


def _event(
    *,
    role: str,
    request_id: str,
    sequence_no: int,
    content: str,
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ConversationJournalEvent:
    command = AppendConversationEvent(
        user_id=user_id,
        thread_id=thread_id,
        request_id=request_id,
        role=role,
        content=content,
        receipt_refs=(["action-1"] if role == "assistant" else []),
    )
    return ConversationJournalEvent(
        id=uuid.uuid4(),
        user_id=user_id,
        thread_id=thread_id,
        request_id=request_id,
        exchange_id=command.exchange_id,
        sequence_no=sequence_no,
        event_type=command.event_type,
        role=role,
        content=content,
        receipt_refs=list(command.receipt_refs),
        created_at=datetime.now(timezone.utc),
    )


class ConversationJournalContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user_id = uuid.uuid4()
        self.thread_id = uuid.uuid4()

    def test_exchange_id_is_deterministic_per_request(self) -> None:
        first = AppendConversationEvent(
            user_id=self.user_id,
            thread_id=self.thread_id,
            request_id="req-1",
            role="user",
            content="你好",
        )
        reply = AppendConversationEvent(
            user_id=self.user_id,
            thread_id=self.thread_id,
            request_id="req-1",
            role="assistant",
            content="你好。",
            receipt_refs=["publish-1"],
        )
        self.assertEqual(first.exchange_id, reply.exchange_id)

    def test_user_event_cannot_claim_receipts(self) -> None:
        with self.assertRaises(ValidationError):
            AppendConversationEvent(
                user_id=self.user_id,
                thread_id=self.thread_id,
                request_id="req-1",
                role="user",
                content="你好",
                receipt_refs=["not-owned"],
            )

    def test_only_user_event_can_carry_shadow_enrollment(self) -> None:
        enrollment = ConversationShadowEnrollment(
            source_commit_sha="c" * 40,
            controller_fingerprint="a" * 64,
            prompt_version="controller-prompt-v1",
            model_id=uuid.uuid4(),
            model_name="fixture-controller",
            timezone="Asia/Shanghai",
        )
        command = AppendConversationEvent(
            user_id=self.user_id,
            thread_id=self.thread_id,
            request_id="req-shadow",
            role="user",
            content="hello",
            shadow_enrollment=enrollment,
        )
        self.assertEqual(command.shadow_enrollment, enrollment)
        with self.assertRaises(ValidationError):
            AppendConversationEvent(
                user_id=self.user_id,
                thread_id=self.thread_id,
                request_id="req-shadow",
                role="assistant",
                content="hello",
                shadow_enrollment=enrollment,
            )

    def test_nested_credentials_are_rejected_from_metadata(self) -> None:
        with self.assertRaises(ValidationError):
            AppendConversationEvent(
                user_id=self.user_id,
                thread_id=self.thread_id,
                request_id="req-1",
                role="assistant",
                content="完成",
                metadata={
                    "nested": [
                        {"credentials": {"token": "must-not-persist"}}
                    ]
                },
            )

    def test_lifecycle_event_roles_are_strict(self) -> None:
        clarification = AppendConversationLifecycleEvent(
            user_id=self.user_id,
            thread_id=self.thread_id,
            request_id="req-clarify",
            event_type="clarification_requested",
            role="assistant",
            content="请确认你的名字。",
        )
        self.assertEqual(clarification.role, "assistant")
        with self.assertRaises(ValidationError):
            AppendConversationLifecycleEvent(
                user_id=self.user_id,
                thread_id=self.thread_id,
                request_id="req-failed",
                event_type="turn_failed",
                role="assistant",
                content="runtime_failed",
            )

    def test_failed_lifecycle_event_cannot_claim_receipt(self) -> None:
        with self.assertRaises(ValidationError):
            AppendConversationLifecycleEvent(
                user_id=self.user_id,
                thread_id=self.thread_id,
                request_id="req-failed",
                event_type="turn_failed",
                role="system",
                content="runtime_failed",
                receipt_refs=["not-completed"],
            )

    def test_projection_preserves_journal_sequence(self) -> None:
        events = [
            _event(
                role="assistant",
                request_id="req-1",
                sequence_no=2,
                content="我是这样回答的。",
                thread_id=self.thread_id,
                user_id=self.user_id,
            ),
            _event(
                role="user",
                request_id="req-1",
                sequence_no=1,
                content="你怎么回答的？",
                thread_id=self.thread_id,
                user_id=self.user_id,
            ),
        ]
        window = project_journal_window(events)
        self.assertEqual(
            [turn.role for turn in window.turns],
            ["user", "assistant"],
        )
        self.assertEqual(
            [turn.turn_offset for turn in window.turns],
            [-2, -1],
        )

    def test_exchange_read_returns_exact_published_pair(self) -> None:
        events = [
            _event(
                role="user",
                request_id="req-1",
                sequence_no=1,
                content="你好，我是冰露。",
                thread_id=self.thread_id,
                user_id=self.user_id,
            ),
            _event(
                role="assistant",
                request_id="req-1",
                sequence_no=2,
                content="你好，冰露。",
                thread_id=self.thread_id,
                user_id=self.user_id,
            ),
        ]
        result = read_journal_events(
            events,
            ConversationReadRequest(target="exchange"),
        )
        self.assertIn("你好，我是冰露。", result.answer)
        self.assertIn("你好，冰露。", result.answer)
        self.assertEqual(result.exchanges[0].status, "completed")

    def test_exchange_id_prevents_adjacent_turn_mispairing(self) -> None:
        events = [
            _event(
                role="user",
                request_id="req-incomplete",
                sequence_no=1,
                content="这轮没有发布回答",
                thread_id=self.thread_id,
                user_id=self.user_id,
            ),
            _event(
                role="user",
                request_id="req-complete",
                sequence_no=2,
                content="你怎么回答的？",
                thread_id=self.thread_id,
                user_id=self.user_id,
            ),
            _event(
                role="assistant",
                request_id="req-complete",
                sequence_no=3,
                content="这是正式发布的回答。",
                thread_id=self.thread_id,
                user_id=self.user_id,
            ),
        ]
        result = read_journal_events(
            events,
            ConversationReadRequest(target="exchange"),
        )
        self.assertEqual(
            result.exchanges[0].user.content,
            "你怎么回答的？",
        )
        self.assertEqual(
            result.exchanges[0].assistant.content,
            "这是正式发布的回答。",
        )

    def test_historical_v1_shadow_enrollment_remains_readable(
        self,
    ) -> None:
        event = ConversationJournalEvent.model_validate(
            {
                "id": uuid.uuid4(),
                "user_id": self.user_id,
                "thread_id": self.thread_id,
                "request_id": "legacy-shadow",
                "exchange_id": uuid.uuid4(),
                "sequence_no": 9,
                "event_type": "user_message",
                "role": "user",
                "content": "legacy",
                "shadow_enrollment": {
                    "schema_version": "agent-shadow-enrollment-v1",
                    "controller_fingerprint": "a" * 64,
                    "prompt_version": "controller-prompt-v1",
                    "model_id": uuid.uuid4(),
                    "model_name": "legacy-controller",
                    "timezone": "Asia/Shanghai",
                },
                "created_at": datetime.now(timezone.utc),
            }
        )
        self.assertEqual(
            event.shadow_enrollment.schema_version,
            "agent-shadow-enrollment-v1",
        )
        self.assertFalse(
            hasattr(event.shadow_enrollment, "source_commit_sha")
        )


if __name__ == "__main__":
    unittest.main()
