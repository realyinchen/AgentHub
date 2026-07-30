from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent_core.working_state import WorkingStateRebuilder
from app.services.conversation.journal_contracts import ConversationJournalEvent


USER_ID = uuid.uuid4()
THREAD_ID = uuid.uuid4()


def _event(
    sequence: int,
    *,
    request_id: str,
    exchange_id: uuid.UUID,
    event_type: str,
    role: str,
    content: str,
) -> ConversationJournalEvent:
    return ConversationJournalEvent(
        id=uuid.uuid4(),
        user_id=USER_ID,
        thread_id=THREAD_ID,
        request_id=request_id,
        exchange_id=exchange_id,
        sequence_no=sequence,
        event_type=event_type,
        role=role,
        content=content,
        created_at=datetime.now(timezone.utc),
    )


class WorkingStateRecoveryTests(unittest.TestCase):
    def test_clarification_rebuilds_pending_state(self) -> None:
        exchange_id = uuid.uuid4()
        state = WorkingStateRebuilder().rebuild(
            [
                _event(
                    1,
                    request_id="req-1",
                    exchange_id=exchange_id,
                    event_type="user_message",
                    role="user",
                    content="记住这个名字。",
                ),
                _event(
                    2,
                    request_id="req-1",
                    exchange_id=exchange_id,
                    event_type="clarification_requested",
                    role="assistant",
                    content="请问要记住哪个名字？",
                ),
            ]
        )
        self.assertEqual(state.last_turn_status, "waiting_clarification")
        self.assertEqual(
            state.pending_clarification.question,
            "请问要记住哪个名字？",
        )
        self.assertIsNone(state.active_exchange_id)

    def test_later_user_message_clears_old_pending_clarification(self) -> None:
        first = uuid.uuid4()
        second = uuid.uuid4()
        state = WorkingStateRebuilder().rebuild(
            [
                _event(
                    1,
                    request_id="req-1",
                    exchange_id=first,
                    event_type="user_message",
                    role="user",
                    content="记住名字。",
                ),
                _event(
                    2,
                    request_id="req-1",
                    exchange_id=first,
                    event_type="clarification_requested",
                    role="assistant",
                    content="哪个名字？",
                ),
                _event(
                    3,
                    request_id="req-2",
                    exchange_id=second,
                    event_type="user_message",
                    role="user",
                    content="冰露。",
                ),
            ]
        )
        self.assertIsNone(state.pending_clarification)
        self.assertEqual(state.active_exchange_id, second)
        self.assertEqual(state.last_turn_status, "incomplete")

    def test_failed_turn_is_terminal_and_checkpoint_contains_no_messages(self) -> None:
        exchange_id = uuid.uuid4()
        state = WorkingStateRebuilder().rebuild(
            [
                _event(
                    1,
                    request_id="req-1",
                    exchange_id=exchange_id,
                    event_type="user_message",
                    role="user",
                    content="执行任务。",
                ),
                _event(
                    2,
                    request_id="req-1",
                    exchange_id=exchange_id,
                    event_type="turn_failed",
                    role="system",
                    content="runtime_failed",
                ),
            ],
            active_goal="执行任务",
            active_task_refs=["task-1"],
        )
        self.assertEqual(state.last_turn_status, "failed")
        self.assertIsNone(state.active_exchange_id)
        payload = state.checkpoint_payload()
        self.assertNotIn("messages", payload)
        self.assertNotIn("conversation", payload)
        self.assertEqual(payload["recovery_cursor"], 2)
        self.assertEqual(payload["active_task_refs"], ["task-1"])


if __name__ == "__main__":
    unittest.main()
