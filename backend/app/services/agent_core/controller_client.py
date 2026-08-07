from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage

from app.infra.llm.factory import get_llm
from app.infra.llm.history import model_history_projector
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.prompt_composer import PromptComposer
from app.services.agent_core.prompt_contracts import ControllerModelRequest
from app.services.agent_core.task_plan_proposal import (
    ControllerTaskPlanProposal,
)
from app.utils.message import convert_message_content_to_string


REQUEST_CLARIFICATION_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "request_clarification",
        "description": (
            "Ask one concise question when required information is missing or "
            "a durable fact is ambiguous, incomplete, conflicting, or sensitive."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2000,
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
}

PLAN_TASK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "plan_task",
        "description": (
            "Propose one durable multi-step plan when the goal spans dependent "
            "steps, multiple rounds, clarification, or crash recovery. The "
            "application decides whether this creates or revises a task."
        ),
        "strict": True,
        "parameters": ControllerTaskPlanProposal.model_json_schema(),
    },
}


class ControllerClientError(ValueError):
    """Raised when a Controller response violates its contract."""


class ControllerClient:
    """One model round. It proposes; it never executes."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry | None = None,
        prompt_composer: PromptComposer | None = None,
        model_factory=None,
    ) -> None:
        self._registry = registry or CapabilityRegistry()
        self._prompt_composer = prompt_composer or PromptComposer(self._registry)
        self._model_factory = model_factory or _default_model_factory

    async def decide(self, request: ControllerModelRequest) -> ControllerOutput:
        model = self._model_factory(request.model_name)
        bind_tools = getattr(model, "bind_tools", None)
        if not callable(bind_tools):
            raise ControllerClientError("model does not expose bind_tools")
        schemas = controller_tool_schemas(self._registry)
        runnable = bind_tools(list(schemas), tool_choice="auto")
        messages = model_history_projector.project(
            self._prompt_composer.compose(request)
        )
        response = await asyncio.wait_for(
            runnable.ainvoke(list(messages)),
            timeout=request.timeout_seconds,
        )
        if not isinstance(response, AIMessage):
            raise ControllerClientError(
                f"expected AIMessage, got {type(response).__name__}"
            )
        return self.parse(response)

    def parse(self, response: AIMessage) -> ControllerOutput:
        content = convert_message_content_to_string(response.content).strip()
        calls = _extract_calls(response)
        if not calls:
            if not content:
                raise ControllerClientError("empty direct Controller response")
            return ControllerOutput(mode="direct_answer", text=content)

        clarification = [
            call for call in calls if call.name == "request_clarification"
        ]
        if clarification:
            if len(calls) != 1:
                raise ControllerClientError(
                    "clarification cannot be mixed with capability proposals"
                )
            arguments = clarification[0].arguments
            question = arguments.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ControllerClientError("clarification question is missing")
            if set(arguments) != {"question"}:
                raise ControllerClientError(
                    "clarification contains unexpected arguments"
                )
            return ControllerOutput(
                mode="request_clarification",
                text=question.strip(),
            )

        task_planning = [
            call for call in calls if call.name == "plan_task"
        ]
        if task_planning:
            if len(calls) != 1:
                raise ControllerClientError(
                    "task planning cannot be mixed with capability proposals"
                )
            try:
                proposal = ControllerTaskPlanProposal.model_validate(
                    task_planning[0].arguments
                )
            except Exception as exc:
                raise ControllerClientError(
                    "task plan violates the Controller proposal contract"
                ) from exc
            return ControllerOutput(
                mode="task_plan_proposal",
                progress_text=content,
                task_plan_proposal=proposal.to_task_plan_draft(),
            )

        return ControllerOutput(
            mode="capability_proposals",
            progress_text=content,
            tool_calls=calls,
        )


def _default_model_factory(model_name: str):
    return get_llm(model_name)


def controller_tool_schemas(
    registry: CapabilityRegistry,
) -> tuple[dict[str, Any], ...]:
    """Project only independently enabled model-facing controls."""

    schemas = list(registry.tool_schemas())
    if registry.task_planning_enabled:
        schemas.append(PLAN_TASK_TOOL)
    schemas.append(REQUEST_CLARIFICATION_TOOL)
    return tuple(schemas)


def _extract_calls(response: AIMessage) -> list[ControllerToolCall]:
    raw_calls = list(response.tool_calls or [])
    if not raw_calls:
        raw_calls = _openai_calls(response.additional_kwargs.get("tool_calls"))
    calls: list[ControllerToolCall] = []
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            raise ControllerClientError("tool call is not an object")
        call_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not call_id or not name:
            raise ControllerClientError("tool call id and name are required")
        calls.append(
            ControllerToolCall(
                call_id=call_id,
                name=name,
                arguments=_arguments(raw.get("args")),
            )
        )
    return calls


def _openai_calls(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    calls: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        function = raw.get("function")
        if not isinstance(function, Mapping):
            continue
        calls.append(
            {
                "id": raw.get("id"),
                "name": function.get("name"),
                "args": function.get("arguments"),
            }
        )
    return calls


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ControllerClientError("tool arguments are invalid JSON") from exc
        if isinstance(parsed, Mapping):
            return dict(parsed)
    raise ControllerClientError("tool arguments must be an object")


__all__ = [
    "PLAN_TASK_TOOL",
    "ControllerClient",
    "ControllerClientError",
    "REQUEST_CLARIFICATION_TOOL",
    "controller_tool_schemas",
]
