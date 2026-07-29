"""Verify that ContextPack is a pure PlanReceipt projection."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.book_intent import build_turn_policy
from app.services.context_pack import ContextBuilder, render_context_pack_prompt


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _memory(user_id: uuid.UUID, value: str, *, status: str = "active") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": "state",
        "subject": "user",
        "value": value,
        "polarity": "neutral",
        "confidence": 1.0,
        "user_id": str(user_id),
        "source": "chat_turn",
        "state_status": status,
        "raw_text": value,
        "metadata": {
            "user_state": {
                "status": status,
                "raw_text": value,
                "category": None,
            }
        },
    }


async def _run() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    active = _memory(user_id, "I keep my red coat in the left wardrobe.")
    denied = _memory(user_id, "I like an obsolete preference.", status="superseded")
    run_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    receipt = {
        "result_mode": "plan_receipt",
        "contract_version": "plan-receipt-v1",
        "plan_id": "plan-context-test",
        "request_id": "request-context-test",
        "route_type": "slow_path",
        "intent": "memory_lookup",
        "planner_used": False,
        "status": "completed",
        "actions": [
            {
                "action_id": "memory-read",
                "capability": "memory",
                "operation": "search_memory",
                "status": "completed",
                "business_input": {"query": "red coat"},
                "output": {
                    "status": "completed",
                    "memories": [active],
                    "denied_memories": [denied],
                },
                "system_executed": True,
            },
            {
                "action_id": "research-state",
                "capability": "research",
                "operation": "inspect_research_state",
                "status": "completed",
                "business_input": {},
                "output": {
                    "status": "completed",
                    "run": {
                        "id": str(run_id),
                        "objective": "Verify receipt projection",
                        "status": "running",
                        "mode": "deep_research",
                    },
                    "state": {
                        "known_facts": ["Receipt projection is explicit."],
                        "evidence_ids": [str(evidence_id)],
                        "gaps": ["Need one more source."],
                    },
                },
                "system_executed": True,
            },
        ],
    }

    builder = ContextBuilder()
    no_receipt = await builder.build(
        user_id=user_id,
        thread_id=thread_id,
        user_message="What do you remember?",
        messages=[HumanMessage(content="What do you remember?")],
    )
    _assert(not no_receipt.current_memories, "ContextPack performed a hidden memory read")
    _assert(no_receipt.research_state_slice is None, "ContextPack performed a hidden research read")

    pack = await builder.build(
        user_id=user_id,
        thread_id=thread_id,
        user_message="What do you remember?",
        messages=[HumanMessage(content="What do you remember?")],
        thread_summary="Old summary: I like an obsolete preference.",
        plan_receipt=receipt,
    )
    rendered = render_context_pack_prompt(pack)
    _assert(len(pack.current_memories) == 1, str(pack.current_memories))
    _assert(active["raw_text"] in rendered, rendered)
    _assert("[excluded_memory]" in pack.thread_summary, pack.thread_summary)
    _assert(pack.research_state_slice is not None, str(pack))
    _assert(pack.research_state_slice.run_id == run_id, str(pack.research_state_slice))
    _assert(pack.research_state_slice.evidence_ids == [evidence_id], str(pack.research_state_slice))
    _assert("System Runtime Receipt" in rendered, rendered)
    _assert(pack.metadata["hidden_memory_reads"] is False, str(pack.metadata))
    _assert(pack.metadata["hidden_research_reads"] is False, str(pack.metadata))

    routed_policy = build_turn_policy("Answer this directly.").model_copy(
        update={
            "can_write_memory": False,
            "can_search_memory": False,
            "allowed_tools": [],
            "denied_tools": [
                "process_memory_write_request",
                "search_memory",
            ],
            "response_boundary": "Use the already-routed direct-answer policy.",
            "metadata": {
                "contract_version": "routing-execution-policy-v1",
                "derived_from_routing_decision": True,
            },
        }
    )
    conflicting_legacy_policy = build_turn_policy("Remember that my name is Ada.")
    authoritative_pack = await builder.build(
        user_id=user_id,
        thread_id=thread_id,
        user_message="Remember that my name is Ada.",
        turn_policy=conflicting_legacy_policy,
        action_plan={
            "result_mode": "action_plan",
            "policy": routed_policy.model_dump(mode="json"),
            "metadata": {},
        },
    )
    _assert(
        authoritative_pack.turn_policy == routed_policy,
        "legacy policy overrode ActionPlan.policy",
    )
    _assert(
        authoritative_pack.metadata["policy_source"] == "action_plan.policy",
        str(authoritative_pack.metadata),
    )
    _assert(
        authoritative_pack.metadata["routing_policy_authoritative"] is True,
        str(authoritative_pack.metadata),
    )

    embedded_policy = routed_policy.model_copy(
        update={"response_boundary": "Use embedded RoutingDecision policy."}
    )
    embedded_pack = await builder.build(
        user_id=user_id,
        thread_id=thread_id,
        user_message="Remember this contradictory raw text.",
        action_plan={
            "result_mode": "action_plan",
            "policy": {},
            "metadata": {
                "routing_decision": {
                    "policy": embedded_policy.model_dump(mode="json"),
                    "requirements": {
                        "direct_answer_allowed": True,
                        "external_search_required": False,
                    },
                    "constraints": [
                        {
                            "field": "external_search",
                            "operator": "equals",
                            "value": False,
                            "source": "rule",
                            "reason": "User prohibited external search.",
                        }
                    ],
                }
            },
        },
    )
    _assert(
        embedded_pack.turn_policy == embedded_policy,
        "embedded RoutingDecision policy was not consumed",
    )
    _assert(
        embedded_pack.metadata["policy_source"]
        == "action_plan.routing_decision.policy",
        str(embedded_pack.metadata),
    )
    _assert(
        "routing_requirement:external_search_required=no"
        in embedded_pack.current_turn_constraints,
        str(embedded_pack.current_turn_constraints),
    )
    _assert(
        "routing_constraint:external_search:equals:false"
        in embedded_pack.current_turn_constraints,
        str(embedded_pack.current_turn_constraints),
    )
    embedded_rendered = render_context_pack_prompt(embedded_pack)
    _assert(
        "policy_source: action_plan.routing_decision.policy" in embedded_rendered,
        embedded_rendered,
    )
    _assert(
        "Never infer a replacement capability policy from raw text"
        in embedded_rendered,
        embedded_rendered,
    )

    fallback_pack = await builder.build(
        user_id=user_id,
        thread_id=thread_id,
        user_message="Remember that this is the legacy no-plan path.",
    )
    _assert(
        fallback_pack.metadata["policy_source"] == "legacy_raw_text_fallback",
        str(fallback_pack.metadata),
    )
    _assert(
        fallback_pack.metadata["routing_policy_authoritative"] is False,
        str(fallback_pack.metadata),
    )

    try:
        await builder.build(
            user_id=user_id,
            thread_id=thread_id,
            user_message="Remember this, but do not trust invalid plan policy.",
            action_plan={
                "result_mode": "action_plan",
                "policy": {"invalid": "policy"},
            },
        )
    except ValueError as exc:
        _assert(
            "refusing legacy raw-text reclassification" in str(exc),
            str(exc),
        )
    else:
        raise AssertionError("invalid ActionPlan policy silently fell back to raw text")
    print("ContextPack receipt projection verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_run())


if __name__ == "__main__":
    main()
