from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from pydantic import BaseModel, ConfigDict, Field

from app.infra.llm.factory import create_llm_from_config
from app.infra.llm.history import model_history_projector
from app.services.agent_core.certification_contracts import (
    AGENT_PROBE_CASE_NAMES,
    AGENT_PROBE_REQUIRED_CASE_NAMES,
    AgentCapabilityCertificationOutcome,
    AgentProbeCaseName,
    AgentProbeCaseResult,
)
from app.services.model_probe.contracts import ProbeConfig
from app.services.model_probe.errors import (
    classify_probe_error,
    safe_probe_error,
)
from app.services.agent_core.task_plan_proposal import (
    ControllerTaskPlanProposal,
)
from app.utils.message import convert_message_content_to_string


class _ProbeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _EchoArguments(_ProbeArguments):
    text: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=1, le=3)


class _LookupArguments(_ProbeArguments):
    query: str = Field(min_length=1, max_length=100)
    language: str = Field(pattern="^(zh|en)$")


PROBE_ECHO_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "probe_echo",
        "description": "Return a test echo. This probe has no side effects.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 100},
                "count": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            "required": ["text", "count"],
            "additionalProperties": False,
        },
    },
}

PROBE_LOOKUP_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "probe_lookup",
        "description": "Return a synthetic probe lookup. This probe has no side effects.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 100},
                "language": {"type": "string", "enum": ["zh", "en"]},
            },
            "required": ["query", "language"],
            "additionalProperties": False,
        },
    },
}

PROBE_FAIL_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "probe_fail",
        "description": "A synthetic tool that always returns a handled failure.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "enum": ["certification"]},
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
}

PROBE_PLAN_TASK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "plan_task",
        "description": (
            "Submit one semantic durable task plan. This certification "
            "probe never persists or executes the plan."
        ),
        "strict": True,
        "parameters": ControllerTaskPlanProposal.model_json_schema(),
    },
}


@dataclass(frozen=True)
class AgentProbeRequest:
    case_name: AgentProbeCaseName
    messages: tuple[BaseMessage, ...]
    tools: tuple[dict[str, Any], ...] = ()
    tool_choice: str | None = None


class AgentProbeTransport(Protocol):
    async def invoke(self, request: AgentProbeRequest) -> AIMessage: ...

    def stream(self, request: AgentProbeRequest) -> AsyncIterator[AIMessageChunk]: ...


class LangChainAgentProbeTransport:
    """Use one configured model while keeping probe tools non-executable."""

    def __init__(self, config: ProbeConfig) -> None:
        self._timeout_seconds = config.timeout_seconds
        self._llm = create_llm_from_config(
            provider=config.provider,
            model_id=config.provider_model_id,
            api_key=config.api_key,
            base_url=config.base_url,
            is_openai_compatible=config.is_openai_compatible,
            thinking_mode=config.configured_thinking,
            extra_headers=config.extra_headers,
        )

    async def invoke(self, request: AgentProbeRequest) -> AIMessage:
        runnable = self._bound(request)
        response = await asyncio.wait_for(
            runnable.ainvoke(
                list(model_history_projector.project(request.messages))
            ),
            timeout=self._timeout_seconds,
        )
        if not isinstance(response, AIMessage):
            raise TypeError(f"Expected AIMessage, got {type(response).__name__}")
        return response

    async def stream(
        self,
        request: AgentProbeRequest,
    ) -> AsyncIterator[AIMessageChunk]:
        runnable = self._bound(request)
        iterator = runnable.astream(
            list(model_history_projector.project(request.messages))
        )
        while True:
            try:
                chunk = await asyncio.wait_for(
                    anext(iterator),
                    timeout=self._timeout_seconds,
                )
            except StopAsyncIteration:
                break
            if not isinstance(chunk, AIMessageChunk):
                raise TypeError(
                    f"Expected AIMessageChunk, got {type(chunk).__name__}"
                )
            yield chunk

    def _bound(self, request: AgentProbeRequest):
        if not request.tools:
            return self._llm
        bind_tools = getattr(self._llm, "bind_tools", None)
        if not callable(bind_tools):
            raise TypeError("model transport does not expose bind_tools")
        kwargs: dict[str, Any] = {}
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice
        return bind_tools(list(request.tools), **kwargs)


class AgentCapabilityProbe:
    """Certify proposal behavior without executing any tool or business action."""

    _CASE_NAMES: tuple[AgentProbeCaseName, ...] = (
        AGENT_PROBE_CASE_NAMES
    )

    def __init__(
        self,
        transport_factory=LangChainAgentProbeTransport,
    ) -> None:
        self._transport_factory = transport_factory

    async def run(
        self,
        config: ProbeConfig,
    ) -> AgentCapabilityCertificationOutcome:
        started = time.perf_counter()
        transport = self._transport_factory(config)
        cases: list[AgentProbeCaseResult] = []
        for case_name in self._CASE_NAMES:
            result = await self._run_case(transport, case_name)
            cases.append(result)
            if result.observations.get("failure_scope") == "provider":
                remaining = self._CASE_NAMES[len(cases) :]
                cases.extend(
                    _short_circuited_case(
                        name,
                        triggered_by=case_name,
                        error_category=str(
                            result.observations["error_category"]
                        ),
                    )
                    for name in remaining
                )
                break
        failures = [case.name for case in cases if case.required and not case.passed]
        return AgentCapabilityCertificationOutcome(
            certified=not failures,
            latency_ms=_elapsed_ms(started),
            cases=cases,
            failure_cases=failures,
        )

    async def _run_case(
        self,
        transport: AgentProbeTransport,
        case_name: AgentProbeCaseName,
    ) -> AgentProbeCaseResult:
        started = time.perf_counter()
        required = case_name in AGENT_PROBE_REQUIRED_CASE_NAMES
        try:
            observations = await getattr(self, f"_case_{case_name}")(transport)
            return AgentProbeCaseResult(
                name=case_name,
                required=required,
                passed=True,
                latency_ms=_elapsed_ms(started),
                observations=observations,
            )
        except Exception as exc:
            category = classify_probe_error(exc)
            return AgentProbeCaseResult(
                name=case_name,
                required=required,
                passed=False,
                latency_ms=_elapsed_ms(started),
                error_type=type(exc).__name__,
                error_message=safe_probe_error(exc),
                observations={
                    "executed": True,
                    "error_category": category,
                    "failure_scope": (
                        "provider"
                        if category
                        in {"auth", "rate_limit", "network", "model"}
                        else "case"
                    ),
                },
            )

    async def _case_basic_chat(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        response = await transport.invoke(
            _request(
                "basic_chat",
                "Reply with exactly AGENT_CHAT_OK and do not call a tool.",
            )
        )
        _require_no_calls(response)
        content = _content(response)
        if "AGENT_CHAT_OK" not in content:
            raise ValueError("basic_chat_marker_missing")
        return {"content_chars": len(content), "tool_call_count": 0}

    async def _case_strict_tool_schema(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        response = await transport.invoke(
            _request(
                "strict_tool_schema",
                "Call probe_echo exactly once with text='schema-ok' and count=2. "
                "Do not answer in prose.",
                tools=(PROBE_ECHO_TOOL,),
                tool_choice="auto",
            )
        )
        call = _require_single_call(response, "probe_echo")
        parsed = _EchoArguments.model_validate(call["args"])
        if parsed.text != "schema-ok" or parsed.count != 2:
            raise ValueError("strict_tool_arguments_incorrect")
        return {"tool_call_count": 1, "arguments_valid": True}

    async def _case_streaming_tool_arguments(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        request = _request(
            "streaming_tool_arguments",
            "Call probe_echo exactly once with text='stream-中文-ok' and count=3. "
            "Do not answer in prose.",
            tools=(PROBE_ECHO_TOOL,),
            tool_choice="auto",
        )
        aggregate: AIMessageChunk | None = None
        chunk_count = 0
        async for chunk in transport.stream(request):
            aggregate = chunk if aggregate is None else aggregate + chunk
            chunk_count += 1
        if aggregate is None:
            raise ValueError("stream_returned_no_chunks")
        call = _require_single_call(aggregate, "probe_echo")
        parsed = _EchoArguments.model_validate(call["args"])
        if parsed.text != "stream-中文-ok" or parsed.count != 3:
            raise ValueError("streaming_tool_arguments_incorrect")
        return {
            "chunk_count": chunk_count,
            "tool_call_count": 1,
            "arguments_valid": True,
        }

    async def _case_multiple_tool_calls(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        response = await transport.invoke(
            _request(
                "multiple_tool_calls",
                "Make exactly two tool calls in this response: "
                "probe_echo(text='multi', count=1) and "
                "probe_lookup(query='books', language='en'). No prose.",
                tools=(PROBE_ECHO_TOOL, PROBE_LOOKUP_TOOL),
                tool_choice="auto",
            )
        )
        calls = _extract_tool_calls(response)
        if len(calls) != 2:
            raise ValueError("multiple_tool_call_count_incorrect")
        by_name = {call["name"]: call for call in calls}
        echo = _EchoArguments.model_validate(by_name["probe_echo"]["args"])
        lookup = _LookupArguments.model_validate(by_name["probe_lookup"]["args"])
        if (echo.text, echo.count) != ("multi", 1):
            raise ValueError("multiple_echo_arguments_incorrect")
        if (lookup.query, lookup.language) != ("books", "en"):
            raise ValueError("multiple_lookup_arguments_incorrect")
        return {"tool_call_count": 2, "arguments_valid": True}

    async def _case_tool_message_roundtrip(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        first_request = _request(
            "tool_message_roundtrip",
            "Call probe_lookup with query='roundtrip' and language='en'.",
            tools=(PROBE_LOOKUP_TOOL,),
            tool_choice="auto",
        )
        first = await transport.invoke(first_request)
        call = _require_single_call(first, "probe_lookup")
        _LookupArguments.model_validate(call["args"])
        second = await transport.invoke(
            AgentProbeRequest(
                case_name="tool_message_roundtrip",
                messages=(
                    *first_request.messages,
                    first,
                    ToolMessage(
                        content='{"status":"ok","value":"ROUNDTRIP_OK"}',
                        tool_call_id=call["id"],
                    ),
                ),
                tools=(PROBE_LOOKUP_TOOL,),
                tool_choice="auto",
            )
        )
        _require_no_calls(second)
        if "ROUNDTRIP_OK" not in _content(second):
            raise ValueError("tool_roundtrip_marker_missing")
        return {"rounds": 2, "terminal_tool_call_count": 0}

    async def _case_mixed_text_tool_call(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        response = await transport.invoke(
            _request(
                "mixed_text_tool_call",
                "Write the text MIXED_TEXT_OK and, in the same response, call "
                "probe_echo with text='mixed' and count=1.",
                tools=(PROBE_ECHO_TOOL,),
                tool_choice="auto",
            )
        )
        call = _require_single_call(response, "probe_echo")
        _EchoArguments.model_validate(call["args"])
        if "MIXED_TEXT_OK" not in _content(response):
            raise ValueError("mixed_text_marker_missing")
        return {"content_and_tool_call": True}

    async def _case_multilingual_context(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        response = await transport.invoke(
            AgentProbeRequest(
                case_name="multilingual_context",
                messages=(
                    SystemMessage(content="Follow the user's latest instruction."),
                    HumanMessage(content="Remember this probe word: 冰露。"),
                    AIMessage(content="Understood."),
                    HumanMessage(
                        content="Call probe_lookup with query='冰露 books' "
                        "and language='zh'."
                    ),
                ),
                tools=(PROBE_LOOKUP_TOOL,),
                tool_choice="auto",
            )
        )
        call = _require_single_call(response, "probe_lookup")
        parsed = _LookupArguments.model_validate(call["args"])
        if parsed.query != "冰露 books" or parsed.language != "zh":
            raise ValueError("multilingual_arguments_incorrect")
        return {"multiturn": True, "unicode_arguments": True}

    async def _case_direct_answer_with_tools(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        response = await transport.invoke(
            _request(
                "direct_answer_with_tools",
                "Do not call any tool. Reply with exactly DIRECT_OK.",
                tools=(PROBE_ECHO_TOOL, PROBE_LOOKUP_TOOL),
                tool_choice="auto",
            )
        )
        _require_no_calls(response)
        if "DIRECT_OK" not in _content(response):
            raise ValueError("direct_answer_marker_missing")
        return {"tool_call_count": 0}

    async def _case_tool_failure_termination(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        first_request = _request(
            "tool_failure_termination",
            "Call probe_fail with reason='certification'.",
            tools=(PROBE_FAIL_TOOL,),
            tool_choice="auto",
        )
        first = await transport.invoke(first_request)
        call = _require_single_call(first, "probe_fail")
        if call["args"] != {"reason": "certification"}:
            raise ValueError("failure_tool_arguments_incorrect")
        second = await transport.invoke(
            AgentProbeRequest(
                case_name="tool_failure_termination",
                messages=(
                    *first_request.messages,
                    first,
                    ToolMessage(
                        content=(
                            '{"status":"failed","error":"synthetic_probe_failure",'
                            '"instruction":"Reply with TOOL_FAILED and stop."}'
                        ),
                        tool_call_id=call["id"],
                    ),
                ),
                tools=(PROBE_FAIL_TOOL,),
                tool_choice="auto",
            )
        )
        _require_no_calls(second)
        if "TOOL_FAILED" not in _content(second):
            raise ValueError("tool_failure_was_not_reported")
        return {"rounds": 2, "terminated_without_retry": True}

    async def _case_task_plan_schema(
        self,
        transport: AgentProbeTransport,
    ) -> dict[str, Any]:
        response = await transport.invoke(
            _request(
                "task_plan_schema",
                "Call plan_task exactly once for the goal 'Read the prior "
                "exchange and inspect it'. Use a first step with step_key="
                "'read', title='Read the prior exchange', capability="
                "'conversation_read', and arguments target='exchange', "
                "selection='latest', count=1. Use a second step with step_key="
                "'inspect', title='Inspect the prior exchange', capability="
                "'conversation_read', the same arguments, and depends_on="
                "['read']. "
                "Do not include system IDs or answer in prose.",
                tools=(PROBE_PLAN_TASK_TOOL,),
                tool_choice="auto",
            )
        )
        call = _require_single_call(response, "plan_task")
        proposal = ControllerTaskPlanProposal.model_validate(call["args"])
        if len(proposal.steps) != 2:
            raise ValueError("task_plan_step_count_incorrect")
        step = proposal.steps[0]
        if (
            step.step_key != "read"
            or step.capability != "conversation_read"
            or step.arguments
            != {
                "target": "exchange",
                "selection": "latest",
                "count": 1,
            }
        ):
            raise ValueError("task_plan_arguments_incorrect")
        inspect = proposal.steps[1]
        if (
            inspect.step_key != "inspect"
            or inspect.capability != "conversation_read"
            or inspect.arguments != step.arguments
            or inspect.depends_on != ["read"]
        ):
            raise ValueError("task_plan_dependency_incorrect")
        return {
            "tool_call_count": 1,
            "task_plan_contract": proposal.contract_version,
            "task_plan_step_count": len(proposal.steps),
            "task_plan_dependency_count": 1,
            "system_identity_fields": 0,
        }


def _short_circuited_case(
    case_name: AgentProbeCaseName,
    *,
    triggered_by: AgentProbeCaseName,
    error_category: str,
) -> AgentProbeCaseResult:
    return AgentProbeCaseResult(
        name=case_name,
        required=case_name in AGENT_PROBE_REQUIRED_CASE_NAMES,
        passed=False,
        latency_ms=0,
        error_type="ProbeShortCircuited",
        error_message=f"provider_dependency_short_circuit:{error_category}",
        observations={
            "executed": False,
            "error_category": error_category,
            "failure_scope": "provider",
            "triggered_by": triggered_by,
        },
    )


def _request(
    case_name: AgentProbeCaseName,
    prompt: str,
    *,
    tools: Sequence[dict[str, Any]] = (),
    tool_choice: str | None = None,
) -> AgentProbeRequest:
    return AgentProbeRequest(
        case_name=case_name,
        messages=(
            SystemMessage(
                content=(
                    "You are running an isolated capability certification. "
                    "Follow the probe instruction exactly. Probe tools are inert."
                )
            ),
            HumanMessage(content=prompt),
        ),
        tools=tuple(tools),
        tool_choice=tool_choice,
    )


def _content(message: AIMessage | AIMessageChunk) -> str:
    return convert_message_content_to_string(message.content).strip()


def _require_no_calls(message: AIMessage | AIMessageChunk) -> None:
    if _extract_tool_calls(message):
        raise ValueError("unexpected_tool_call")


def _require_single_call(
    message: AIMessage | AIMessageChunk,
    expected_name: str,
) -> dict[str, Any]:
    calls = _extract_tool_calls(message)
    if len(calls) != 1:
        raise ValueError("expected_exactly_one_tool_call")
    if calls[0]["name"] != expected_name:
        raise ValueError("unexpected_tool_name")
    return calls[0]


def _extract_tool_calls(
    message: AIMessage | AIMessageChunk,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(getattr(message, "tool_calls", None) or []):
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        normalized.append(
            {
                "id": str(raw.get("id") or f"probe-call-{index}"),
                "name": name,
                "args": _arguments(raw.get("args")),
            }
        )
    if normalized:
        return normalized

    for index, raw in enumerate(
        (getattr(message, "additional_kwargs", None) or {}).get("tool_calls", [])
    ):
        if not isinstance(raw, Mapping):
            continue
        function = raw.get("function")
        if not isinstance(function, Mapping):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        normalized.append(
            {
                "id": str(raw.get("id") or f"probe-call-{index}"),
                "name": name,
                "args": _arguments(function.get("arguments")),
            }
        )
    return normalized


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, Mapping):
            return dict(parsed)
    raise ValueError("tool_arguments_are_not_an_object")


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1_000))


__all__ = [
    "AgentCapabilityProbe",
    "AgentProbeRequest",
    "AgentProbeTransport",
    "LangChainAgentProbeTransport",
    "PROBE_ECHO_TOOL",
    "PROBE_FAIL_TOOL",
    "PROBE_LOOKUP_TOOL",
]
