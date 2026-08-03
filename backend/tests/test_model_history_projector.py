from __future__ import annotations

import unittest

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agents.middleware.content_filter import ContentFilterMiddleware
from app.infra.llm.history import ModelHistoryProjector


def _tool_call() -> dict:
    return {
        "name": "probe_lookup",
        "args": {"query": "books"},
        "id": "call-1",
        "type": "tool_call",
    }


class ModelHistoryProjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.projector = ModelHistoryProjector()

    def test_projects_assistant_reasoning_without_mutating_source(self) -> None:
        raw_tool_call = {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "probe_lookup",
                "arguments": '{"query":"books"}',
            },
        }
        assistant = AIMessage(
            content=[
                "",
                {"type": "thinking", "thinking": "private-one"},
                {"type": "text", "text": "VISIBLE"},
                {"type": "reasoning", "reasoning": "private-two"},
            ],
            additional_kwargs={
                "reasoning_content": "private-three",
                "reasoning_details": ["private-four"],
                "thinking": "private-five",
                "tool_calls": [raw_tool_call],
            },
            tool_calls=[_tool_call()],
            response_metadata={"model_name": "thinking-model"},
            id="assistant-1",
        )
        messages = (
            SystemMessage(content="policy"),
            HumanMessage(
                content=[
                    {"type": "text", "text": "question"},
                    {"type": "image_url", "image_url": {"url": "safe"}},
                ]
            ),
            assistant,
            ToolMessage(content='{"status":"ok"}', tool_call_id="call-1"),
        )

        projected = self.projector.project(messages)

        self.assertIsInstance(projected, tuple)
        self.assertEqual(len(projected), 4)
        self.assertIs(projected[0], messages[0])
        self.assertIs(projected[1], messages[1])
        self.assertIs(projected[3], messages[3])
        safe_assistant = projected[2]
        self.assertIsInstance(safe_assistant, AIMessage)
        self.assertIsNot(safe_assistant, assistant)
        self.assertEqual(safe_assistant.content, "VISIBLE")
        self.assertEqual(safe_assistant.tool_calls, assistant.tool_calls)
        self.assertEqual(
            safe_assistant.response_metadata,
            assistant.response_metadata,
        )
        self.assertEqual(safe_assistant.id, assistant.id)
        self.assertEqual(
            safe_assistant.additional_kwargs,
            {"tool_calls": [raw_tool_call]},
        )
        self.assertIsInstance(assistant.content, list)
        self.assertIn("reasoning_content", assistant.additional_kwargs)

    def test_empty_tool_call_content_does_not_invent_placeholder(self) -> None:
        assistant = AIMessage(
            content=[{"type": "thinking", "thinking": "private"}],
            tool_calls=[_tool_call()],
        )

        projected = self.projector.project_message(assistant)

        self.assertEqual(projected.content, "")
        self.assertEqual(projected.tool_calls, assistant.tool_calls)

    def test_legacy_filter_delegates_assistant_projection(self) -> None:
        assistant = AIMessage(
            content=[
                {"type": "thinking", "thinking": "private"},
                {"type": "text", "text": "VISIBLE"},
            ],
            additional_kwargs={"reasoning_content": "private"},
        )

        filtered = ContentFilterMiddleware()._filter_message_content(assistant)

        self.assertEqual(filtered.content, "VISIBLE")
        self.assertNotIn("reasoning_content", filtered.additional_kwargs)


if __name__ == "__main__":
    unittest.main()
