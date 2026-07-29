from __future__ import annotations

from app.services.book_intent import TurnIntent, TurnPolicy
from app.services.routing.config import CANDIDATE_ADMISSION_THRESHOLD
from app.services.routing.contracts import IntentCandidate, ProposedAction


_ROUTING_OPERATIONS = frozenset(
    {
        "process_memory_write_request",
        "recall_recent_conversation",
        "search_memory",
        "record_book_feedback",
        "record_recommendation_signal",
        "web_search",
        "search_books",
        "get_recommendation_history",
        "start_research",
        "plan_research_search",
        "acquire_research_sources",
        "collect_research_sources",
        "add_evidence",
        "evaluate_research_gaps",
        "build_research_report",
        "finalize_research_answer",
        "synthesize_research_answer",
        "publish_research_answer",
    }
)


def compile_execution_policy(
    *,
    primary_intent: str,
    candidates: list[IntentCandidate],
    actions: list[ProposedAction],
) -> TurnPolicy:
    """Compile runtime admission from the already-made routing decision.

    This is deliberately not another text classifier. It projects admitted
    candidate/action state into the established TurnPolicy shape consumed by
    SystemRuntime.
    """

    admitted = [
        item
        for item in candidates
        if item.confidence >= CANDIDATE_ADMISSION_THRESHOLD
    ]
    operations = {action.operation for action in actions}
    turn_intents = _turn_intents(admitted)
    mapped_primary = _turn_intent_name(primary_intent)
    if mapped_primary not in turn_intents:
        turn_intents.insert(0, mapped_primary)

    can_write_memory = bool(
        operations.intersection(
            {
                "process_memory_write_request",
                "record_book_feedback",
                "record_recommendation_signal",
            }
        )
    )
    can_search_books = "search_books" in operations
    can_start_research = "start_research" in operations
    can_search_memory = "search_memory" in operations
    can_use_web_search = bool(
        operations.intersection({"web_search", "acquire_research_sources"})
    )
    allowed_tools = sorted(operations)
    denied_tools = sorted(_ROUTING_OPERATIONS.difference(operations))

    evidence = [
        evidence
        for candidate in admitted
        for evidence in candidate.evidence
    ]
    source = (
        "model_router"
        if any(candidate.source == "router_model" for candidate in admitted)
        else "deterministic_rules"
    )
    intent = TurnIntent(
        primary_intent=mapped_primary,
        intents=turn_intents,
        confidence=max((item.confidence for item in admitted), default=0.0),
        explicit=any(item.source == "rule" for item in admitted),
        source=source,
        signals=evidence,
        metadata={
            "memory_lookup": "search_memory" in operations,
            "web_search": can_use_web_search,
            "web_search_recommended": can_use_web_search,
        },
    )
    return TurnPolicy(
        intent=intent,
        can_answer_question=True,
        can_write_memory=can_write_memory,
        can_manage_memory=False,
        can_search_memory=can_search_memory,
        can_search_books=can_search_books,
        can_recommend_books=can_search_books,
        can_view_recommendation_history=(
            "get_recommendation_history" in operations
        ),
        can_record_recommendation_signal=(
            "record_recommendation_signal" in operations
        ),
        can_start_research=can_start_research,
        can_use_research_tools=can_start_research,
        can_use_web_search=can_use_web_search,
        max_book_search_calls=1 if can_search_books else 0,
        requires_verifier=can_start_research,
        allowed_tools=allowed_tools,
        denied_tools=denied_tools,
        response_boundary=_response_boundary(
            primary_intent=primary_intent,
            operations=operations,
        ),
        metadata={
            "contract_version": "routing-execution-policy-v1",
            "derived_from_routing_decision": True,
        },
    )


def _turn_intents(candidates: list[IntentCandidate]) -> list[str]:
    result: list[str] = []
    for candidate in candidates:
        mapped = _turn_intent_name(candidate.intent)
        if mapped not in result:
            result.append(mapped)
    return result


def _turn_intent_name(intent: str) -> str:
    return {
        "memory_update": "update_memory",
        "reading_feedback": "update_memory",
        "recommend_books": "recommend_books",
        "recommendation_history": "recommendation_history",
        "deep_research": "deep_search",
    }.get(intent, "answer_question")


def _response_boundary(
    *,
    primary_intent: str,
    operations: set[str],
) -> str:
    if operations.intersection(
        {"publish_research_answer", "finalize_research_answer"}
    ):
        return (
            "Project the final answer only from verified research receipts. "
            "Do not emit or simulate tool-call markup."
        )
    if primary_intent == "memory_lookup":
        return (
            "Answer from the completed memory receipt. If the requested fact "
            "is absent, say it is not recorded."
        )
    if primary_intent == "conversation_recall":
        return (
            "Answer only from the current-thread conversation receipt. "
            "Do not substitute durable memory."
        )
    if primary_intent in {"memory_update", "reading_feedback"}:
        return "Confirm only the memory action proven by the runtime receipt."
    if "search_books" in operations:
        return (
            "Recommend books from completed memory, web, and book-search "
            "receipts while honoring current constraints."
        )
    if operations.intersection({"web_search", "acquire_research_sources"}):
        return "Answer current or external facts from the completed web receipt."
    return "Answer the user's stated question without inventing tool execution."
