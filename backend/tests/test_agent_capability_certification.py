from __future__ import annotations

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent_core.certification_probe import (
    AgentCapabilityProbe,
    AgentProbeRequest,
    LangChainAgentProbeTransport,
)
from app.services.agent_core.certification_contracts import (
    AGENT_PROBE_REQUIRED_CASE_NAMES,
)
from app.services.model_probe import ProbeConfig


def _config() -> ProbeConfig:
    return ProbeConfig(
        provider="test",
        provider_model_id="agent-capable",
        api_key="not-a-real-key",
        base_url=None,
        is_openai_compatible=True,
        timeout_seconds=1,
        check_thinking=False,
    )


def _tool_call(name: str, arguments: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": arguments,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


class _PassingTransport:
    def __init__(self) -> None:
        self.requests: list[AgentProbeRequest] = []

    async def invoke(self, request: AgentProbeRequest) -> AIMessage:
        self.requests.append(request)
        name = request.case_name
        has_tool_result = any(
            isinstance(message, ToolMessage) for message in request.messages
        )
        if name == "basic_chat":
            return AIMessage(content="AGENT_CHAT_OK")
        if name == "strict_tool_schema":
            return _tool_call(
                "probe_echo",
                {"text": "schema-ok", "count": 2},
                "strict-1",
            )
        if name == "multiple_tool_calls":
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "probe_echo",
                        "args": {"text": "multi", "count": 1},
                        "id": "multi-1",
                        "type": "tool_call",
                    },
                    {
                        "name": "probe_lookup",
                        "args": {"query": "books", "language": "en"},
                        "id": "multi-2",
                        "type": "tool_call",
                    },
                ],
            )
        if name == "tool_message_roundtrip":
            if has_tool_result:
                return AIMessage(content="ROUNDTRIP_OK")
            return _tool_call(
                "probe_lookup",
                {"query": "roundtrip", "language": "en"},
                "roundtrip-1",
            )
        if name == "mixed_text_tool_call":
            response = _tool_call(
                "probe_echo",
                {"text": "mixed", "count": 1},
                "mixed-1",
            )
            response.content = "MIXED_TEXT_OK"
            return response
        if name == "multilingual_context":
            return _tool_call(
                "probe_lookup",
                {"query": "冰露 books", "language": "zh"},
                "multilingual-1",
            )
        if name == "direct_answer_with_tools":
            return AIMessage(content="DIRECT_OK")
        if name == "task_plan_schema":
            return _tool_call(
                "plan_task",
                {
                    "goal": "Read the prior exchange",
                    "steps": [
                        {
                            "step_key": "read",
                            "title": "Read the prior exchange",
                            "capability": "conversation_read",
                            "arguments": {
                                "target": "exchange",
                                "selection": "latest",
                                "count": 1,
                            },
                        },
                        {
                            "step_key": "inspect",
                            "title": "Inspect the prior exchange",
                            "capability": "conversation_read",
                            "arguments": {
                                "target": "exchange",
                                "selection": "latest",
                                "count": 1,
                            },
                            "depends_on": ["read"],
                        }
                    ],
                },
                "plan-task-1",
            )
        if name == "tool_failure_termination":
            if has_tool_result:
                return AIMessage(content="TOOL_FAILED")
            return _tool_call(
                "probe_fail",
                {"reason": "certification"},
                "failure-1",
            )
        raise AssertionError(f"unexpected invoke case: {name}")

    async def stream(self, request: AgentProbeRequest):
        self.requests.append(request)
        if request.case_name != "streaming_tool_arguments":
            raise AssertionError(f"unexpected stream case: {request.case_name}")
        yield AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "probe_echo",
                    "args": '{"text":"stream-中文-ok","count":3}',
                    "id": "stream-1",
                    "index": 0,
                    "type": "tool_call_chunk",
                }
            ],
        )


class _HistoryCaptureModel:
    def __init__(self) -> None:
        self.invoked_messages = None
        self.streamed_messages = None

    async def ainvoke(self, messages):
        self.invoked_messages = messages
        return AIMessage(content="OK")

    async def astream(self, messages):
        self.streamed_messages = messages
        yield AIMessageChunk(content="OK")


class AgentCapabilityProbeTests(unittest.IsolatedAsyncioTestCase):
    def test_transport_uses_configured_thinking_mode(self) -> None:
        model = object()
        with patch(
            "app.services.agent_core.certification_probe."
            "create_llm_from_config",
            return_value=model,
        ) as factory:
            transport = LangChainAgentProbeTransport(
                ProbeConfig(
                    provider="test",
                    provider_model_id="thinking-only",
                    api_key="not-a-real-key",
                    base_url=None,
                    is_openai_compatible=True,
                    timeout_seconds=1,
                    configured_thinking=True,
                )
            )

        self.assertIs(transport._llm, model)
        self.assertTrue(factory.call_args.kwargs["thinking_mode"])

    async def test_transport_projects_history_for_invoke_and_stream(self) -> None:
        model = _HistoryCaptureModel()
        with patch(
            "app.services.agent_core.certification_probe."
            "create_llm_from_config",
            return_value=model,
        ):
            transport = LangChainAgentProbeTransport(_config())
        assistant = AIMessage(
            content=[
                {"type": "thinking", "thinking": "private"},
                {"type": "text", "text": "VISIBLE"},
            ],
            additional_kwargs={"reasoning_content": "private"},
        )
        request = AgentProbeRequest(
            case_name="basic_chat",
            messages=(assistant,),
        )

        await transport.invoke(request)
        chunks = [chunk async for chunk in transport.stream(request)]

        self.assertEqual(len(chunks), 1)
        self.assertEqual(model.invoked_messages[0].content, "VISIBLE")
        self.assertEqual(model.streamed_messages[0].content, "VISIBLE")
        self.assertNotIn(
            "reasoning_content",
            model.invoked_messages[0].additional_kwargs,
        )

    async def test_all_required_cases_must_pass(self) -> None:
        transport = _PassingTransport()
        outcome = await AgentCapabilityProbe(lambda _config: transport).run(
            _config()
        )

        self.assertTrue(outcome.certified)
        self.assertEqual(len(outcome.cases), 10)
        self.assertFalse(outcome.failure_cases)
        self.assertTrue(all(case.passed for case in outcome.cases))
        self.assertEqual(
            {case.name for case in outcome.cases if case.required},
            set(AGENT_PROBE_REQUIRED_CASE_NAMES),
        )
        self.assertTrue(
            all(
                request.tool_choice == "auto"
                for request in transport.requests
                if request.tools
            )
        )
        self.assertEqual(len(transport.requests), 12)

    async def test_one_required_failure_fails_closed(self) -> None:
        class InvalidSchemaTransport(_PassingTransport):
            async def invoke(self, request: AgentProbeRequest) -> AIMessage:
                if request.case_name == "strict_tool_schema":
                    self.requests.append(request)
                    return _tool_call(
                        "probe_echo",
                        {"text": "schema-ok", "count": 99},
                        "invalid-1",
                    )
                return await super().invoke(request)

        outcome = await AgentCapabilityProbe(
            lambda _config: InvalidSchemaTransport()
        ).run(_config())

        self.assertFalse(outcome.certified)
        self.assertEqual(outcome.failure_cases, ["strict_tool_schema"])
        failed = next(
            case for case in outcome.cases if case.name == "strict_tool_schema"
        )
        self.assertFalse(failed.passed)
        self.assertEqual(failed.error_type, "ValidationError")

    async def test_observation_case_failure_does_not_block_r3(self) -> None:
        class InvalidStreamingTransport(_PassingTransport):
            async def stream(self, request: AgentProbeRequest):
                self.requests.append(request)
                if request.case_name != "streaming_tool_arguments":
                    raise AssertionError(
                        f"unexpected stream case: {request.case_name}"
                    )
                if False:
                    yield AIMessageChunk(content="")
                raise ValueError("optional_streaming_failure")

        outcome = await AgentCapabilityProbe(
            lambda _config: InvalidStreamingTransport()
        ).run(_config())

        self.assertTrue(outcome.certified)
        self.assertFalse(outcome.failure_cases)
        failed = next(
            case
            for case in outcome.cases
            if case.name == "streaming_tool_arguments"
        )
        self.assertFalse(failed.required)
        self.assertFalse(failed.passed)

    async def test_provider_wide_failure_short_circuits_remaining_cases(
        self,
    ) -> None:
        RateLimitError = type("RateLimitError", (Exception,), {})

        class RateLimitedTransport(_PassingTransport):
            async def invoke(self, request: AgentProbeRequest) -> AIMessage:
                self.requests.append(request)
                raise RateLimitError("sensitive upstream quota detail")

        transport = RateLimitedTransport()
        outcome = await AgentCapabilityProbe(
            lambda _config: transport
        ).run(_config())

        self.assertFalse(outcome.certified)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(len(outcome.cases), 10)
        self.assertEqual(
            set(outcome.failure_cases),
            set(AGENT_PROBE_REQUIRED_CASE_NAMES),
        )
        first, *remaining = outcome.cases
        self.assertEqual(first.name, "basic_chat")
        self.assertTrue(first.observations["executed"])
        self.assertEqual(
            first.observations["error_category"],
            "rate_limit",
        )
        self.assertEqual(
            first.observations["failure_scope"],
            "provider",
        )
        self.assertTrue(
            all(item.error_type == "ProbeShortCircuited" for item in remaining)
        )
        self.assertTrue(
            all(item.observations["executed"] is False for item in remaining)
        )
        self.assertTrue(
            all(
                item.observations["triggered_by"] == "basic_chat"
                for item in remaining
            )
        )
        self.assertTrue(
            all(
                "sensitive upstream quota detail"
                not in str(item.error_message)
                for item in remaining
            )
        )


if __name__ == "__main__":
    unittest.main()
