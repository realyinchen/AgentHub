from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent_core.certification_contracts import (
    AgentModeAdmission,
)
from app.services.conversation import ConversationJournalEvent
from app.services.conversation.summary_builder import SummaryBuildError
from app.services.conversation.summary_llm_provider import LLMSummaryProvider


class _SummaryModel:
    def __init__(self) -> None:
        self.schemas = None
        self.messages = None

    def bind_tools(self, schemas, **_kwargs):
        self.schemas = schemas
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "submit_conversation_summary",
                    "id": "summary-1",
                    "type": "tool_call",
                    "args": {
                        "user_requests": [
                            {
                                "text": "用户要求准确回忆上一轮。",
                                "source_sequences": [1],
                            }
                        ],
                        "user_statements": [],
                        "decisions": [],
                        "corrections": [],
                        "unresolved": [],
                        "active_tasks": [],
                        "receipt_refs": [],
                    },
                }
            ],
        )


def _admission(admitted: bool = True) -> AgentModeAdmission:
    return AgentModeAdmission(
        admitted=admitted,
        certification_id="cert-1" if admitted else None,
        reason=None if admitted else "certification_missing",
        configuration_fingerprint="a" * 64,
        controller_fingerprint="b" * 64,
        source_commit_sha="c" * 40,
    )


def _events() -> list[ConversationJournalEvent]:
    exchange_id = uuid.uuid4()
    common = {
        "user_id": uuid.uuid4(),
        "thread_id": uuid.uuid4(),
        "request_id": "request-1",
        "exchange_id": exchange_id,
        "created_at": datetime.now(timezone.utc),
    }
    return [
        ConversationJournalEvent(
            id=uuid.uuid4(),
            sequence_no=1,
            event_type="user_message",
            role="user",
            content="刚才我说什么了？",
            **common,
        ),
        ConversationJournalEvent(
            id=uuid.uuid4(),
            sequence_no=2,
            event_type="assistant_published",
            role="assistant",
            content="你问了刚才说什么。",
            **common,
        ),
    ]


class LLMSummaryProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_certified_model_returns_structured_draft(self) -> None:
        model = _SummaryModel()
        draft = await LLMSummaryProvider(
            model_name="fixture-model",
            admission=_admission(),
            model_factory=lambda _name: model,
        ).summarize(previous=None, events=_events())

        self.assertEqual(draft.model_id, "fixture-model")
        self.assertEqual(
            draft.structured_content.user_requests[0].source_sequences,
            [1],
        )
        self.assertTrue(
            any(
                isinstance(message, HumanMessage)
                and "journal_sequence=1" in str(message.content)
                for message in model.messages
            )
        )
        self.assertEqual(
            model.schemas[0]["function"]["name"],
            "submit_conversation_summary",
        )

    def test_denied_model_cannot_summarize(self) -> None:
        with self.assertRaisesRegex(
            SummaryBuildError,
            "not_admitted",
        ):
            LLMSummaryProvider(
                model_name="fixture-model",
                admission=_admission(False),
            )


if __name__ == "__main__":
    unittest.main()
