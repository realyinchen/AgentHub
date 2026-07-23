"""Verify chat-history tool_info can drive the route-first UI panels.

This check avoids LLM/provider calls. It verifies the runtime data shape between
backend chat history and frontend message rendering:
- final AI messages can receive ordered custom_data.tool_info from prior tool calls
- book-turn-orchestration-v1 payloads survive in tool_info output strings
- frontend source contains the stored-tool parser, book-turn parser, and panel
  wiring needed to render the route-first panel from persisted history
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.utils.message import (
    augment_ai_message_with_tool_info,
    collect_tool_calls_for_final_response,
    messages_to_tool_info,
)

FRONTEND_TYPES = PROJECT_DIR / "frontend" / "src" / "types.ts"
CHAT_MESSAGE_ITEM = (
    PROJECT_DIR
    / "frontend"
    / "src"
    / "features"
    / "chat"
    / "components"
    / "chat-message-item.tsx"
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _route_payload() -> dict[str, Any]:
    return {
        "result_mode": "book_turn_orchestration",
        "contract_version": "book-turn-orchestration-v1",
        "route": "recommendation_history",
        "query": "Why did you not recommend Dune?",
        "user_message": "Why did you not recommend Dune?",
        "history_mode": "suppression_explanation",
        "policy": {
            "intent": {
                "primary_intent": "recommendation_history",
                "intents": ["answer_question", "recommendation_history"],
                "confidence": 1.0,
                "explicit": True,
                "source": "deterministic_rules",
                "signals": [
                    "explicit_recommendation_history_or_suppression_explanation"
                ],
                "metadata": {"contract_version": "turn-intent-v1"},
            },
            "can_answer_question": True,
            "can_write_memory": False,
            "can_manage_memory": False,
            "can_search_memory": True,
            "can_search_books": False,
            "can_recommend_books": False,
            "can_view_recommendation_history": True,
            "can_record_recommendation_signal": False,
            "can_start_research": False,
            "can_use_research_tools": False,
            "max_book_search_calls": 0,
            "requires_verifier": False,
            "allowed_tools": [
                "get_current_time",
                "plan_book_assistant_turn",
                "search_memory",
                "get_recommendation_history",
            ],
            "denied_tools": ["search_books"],
            "response_boundary": (
                "Answer only with recommendation history or suppression "
                "explanation."
            ),
            "metadata": {"contract_version": "turn-policy-v1"},
        },
        "recommended_next_tools": ["get_recommendation_history"],
        "denied_tools": ["search_books"],
        "response_boundary": (
            "Answer only with recommendation history or suppression explanation."
        ),
        "route_steps": [
            {
                "name": "get_recommendation_history",
                "status": "ready",
                "reason": "The user asked for a suppression explanation.",
                "required_inputs": ["user_id", "history_mode"],
            },
            {
                "name": "search_books",
                "status": "blocked_by_route",
                "reason": "History mode must not create fresh recommendations.",
                "required_inputs": [],
            },
        ],
        "personalization_constraints": None,
        "recommendation_research_workflow": None,
        "metadata": {
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "writes_research_state": False,
            "writes_evidence": False,
            "external_call": False,
            "executes_planned_tools": False,
            "uses_app_owned_contracts": True,
        },
    }


def _history_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "result_mode": "recommendation_history",
        "history_mode": "suppression_explanation",
        "user_id": "00000000-0000-0000-0000-000000000001",
        "query": "Why did you not recommend Dune?",
        "book_title": "Dune",
        "records": [],
        "suppressed_records": [
            {
                "record_type": "recommendation_event",
                "event_type": "read",
                "book_id": None,
                "book_title": "Dune",
                "reason": "Already read",
                "suppression_reasons": ["already_read"],
                "signal_polarity": "neutral",
                "signal_strength": 1.0,
                "source": "book_feedback",
                "thread_id": None,
                "request_id": "",
                "message_id": "",
                "metadata": {},
                "created_at": None,
            }
        ],
        "result_count": 1,
        "next_action_hint": "",
        "metadata": {
            "ordinary_recommendation_candidates": False,
            "suppressed_records_are_history_only": True,
        },
    }


def _messages() -> list[Any]:
    route = _route_payload()
    history = _history_payload()
    return [
        HumanMessage(content="Why did you not recommend Dune?"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "plan_book_assistant_turn",
                    "args": {
                        "query": "Why did you not recommend Dune?",
                        "book_title": "Dune",
                    },
                    "id": "call-route",
                }
            ],
        ),
        ToolMessage(content=json.dumps(route), tool_call_id="call-route"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_recommendation_history",
                    "args": {
                        "history_mode": "suppression_explanation",
                        "book_title": "Dune",
                    },
                    "id": "call-history",
                }
            ],
        ),
        ToolMessage(content=json.dumps(history), tool_call_id="call-history"),
        AIMessage(
            content=(
                "Dune was not returned as a fresh recommendation because it is "
                "already in your reading history."
            )
        ),
    ]


def _verify_backend_tool_info_shape() -> None:
    messages = _messages()
    final_index = len(messages) - 1
    tool_info = collect_tool_calls_for_final_response(messages, final_index)

    _assert(len(tool_info) == 2, str(tool_info))
    _assert([item["order"] for item in tool_info] == [0, 1], str(tool_info))
    _assert(
        [item["name"] for item in tool_info]
        == ["plan_book_assistant_turn", "get_recommendation_history"],
        str(tool_info),
    )
    _assert(tool_info[0]["id"] == "call-route", str(tool_info))
    _assert(tool_info[1]["id"] == "call-history", str(tool_info))

    route = json.loads(tool_info[0]["output"])
    history = json.loads(tool_info[1]["output"])
    _assert(route["result_mode"] == "book_turn_orchestration", str(route))
    _assert(route["contract_version"] == "book-turn-orchestration-v1", str(route))
    _assert(route["route"] == "recommendation_history", str(route))
    _assert("search_books" in route["denied_tools"], str(route))
    _assert(history["result_mode"] == "recommendation_history", str(history))
    _assert(history["suppressed_records"], str(history))

    all_tool_info = messages_to_tool_info(messages)
    _assert(all_tool_info == tool_info, str(all_tool_info))

    augmented = augment_ai_message_with_tool_info(list(messages))
    final = augmented[-1]
    _assert(isinstance(final, AIMessage), str(type(final)))
    _assert(
        final.additional_kwargs.get("tool_info") == tool_info,
        str(final.additional_kwargs),
    )


def _verify_frontend_route_panel_wiring() -> None:
    types_source = FRONTEND_TYPES.read_text(encoding="utf-8")
    component_source = CHAT_MESSAGE_ITEM.read_text(encoding="utf-8")

    required_types = [
        'result_mode: "book_turn_orchestration"',
        'contract_version: "book-turn-orchestration-v1"',
        "export type BookTurnPolicy",
        "export type BookTurnOrchestrationResult",
        "recommendation_research_workflow: RecommendationResearchWorkflowResult | null",
    ]
    for snippet in required_types:
        _assert(snippet in types_source, f"frontend types missing: {snippet}")

    required_component_snippets = [
        "function parseStoredToolInfo",
        "function normalizeBookTurnOrchestration",
        'payload.result_mode !== "book_turn_orchestration"',
        'payload.contract_version !== "book-turn-orchestration-v1"',
        "function parseBookTurnOrchestrationResults",
        "function BookTurnOrchestrationPanel",
        "parseBookTurnOrchestrationResults(allTools)",
        "bookTurnOrchestrationResults.map",
        "result.recommended_next_tools",
        "result.policy.can_search_books",
        "result.metadata.executes_planned_tools",
        "result.suppressed_records",
    ]
    for snippet in required_component_snippets:
        _assert(snippet in component_source, f"component missing: {snippet}")

    stored_parser_index = component_source.find("function parseStoredToolInfo")
    book_turn_parser_index = component_source.find(
        "function parseBookTurnOrchestrationResults"
    )
    render_index = component_source.find("bookTurnOrchestrationResults.map")
    _assert(stored_parser_index >= 0, "stored tool parser not found")
    _assert(book_turn_parser_index > stored_parser_index, "book-turn parser order")
    _assert(render_index > book_turn_parser_index, "book-turn render order")


def main() -> None:
    _verify_backend_tool_info_shape()
    _verify_frontend_route_panel_wiring()
    print("chat route panel verification passed")


if __name__ == "__main__":
    main()
