"""Compile book-catalog reads selected by resolved book goals."""

from __future__ import annotations

import re
from typing import Any

from app.services.routing.capabilities import scoped_action_key, traced_reason
from app.services.routing.contracts import ProposedAction
from app.services.routing.interaction_contracts import InteractionDecision


def compile_book_actions(
    text: str,
    interaction: InteractionDecision,
    fast_path: Any | None = None,
) -> list[ProposedAction]:
    """Compile book actions from goal decisions, never from raw-text intent."""

    del text, fast_path
    actions: list[ProposedAction] = []
    clause_count = len(interaction.clauses)
    global_prohibited = set(interaction.prohibited_capabilities)

    for index, clause in enumerate(interaction.clauses):
        prohibited = global_prohibited | set(clause.prohibited_capabilities)
        if clause.goal.kind in {"recommend_books", "find_books"}:
            if "book_catalog_search" in prohibited:
                continue
            actions.append(
                ProposedAction(
                    action_key=scoped_action_key(
                        "search_books",
                        clause,
                        clause_index=index,
                        clause_count=clause_count,
                    ),
                    capability="book",
                    operation="search_books",
                    arguments={
                        "query": _catalog_query(interaction, index),
                        "limit": 5,
                        "allow_additional_search": False,
                    },
                    reason=traced_reason(
                        "Retrieve fresh book candidates for the resolved recommendation goal.",
                        clause,
                    ),
                )
            )
        elif clause.goal.kind == "review_recommendation_history":
            actions.append(
                ProposedAction(
                    action_key=scoped_action_key(
                        "recommendation_history",
                        clause,
                        clause_index=index,
                        clause_count=clause_count,
                    ),
                    capability="book",
                    operation="get_recommendation_history",
                    arguments={"query": clause.text, "limit": 20},
                    reason=traced_reason(
                        "Read recommendation history for the resolved history goal.",
                        clause,
                    ),
                )
            )
    return actions


def _catalog_query(
    interaction: InteractionDecision,
    clause_index: int,
) -> str:
    clause = interaction.clauses[clause_index]
    if not re.search(r"类似|相似|同类|similar", clause.text, re.I):
        return clause.text
    for previous in reversed(interaction.clauses[:clause_index]):
        match = re.search(
            r"(?:豆瓣)?(?:关于|有关)(?P<subject>[^，。！？?,;]{1,80}?)(?:的)?"
            r"(?:评论|评价|口碑|书评|reviews?)",
            previous.text,
            re.I,
        )
        if match:
            subject = str(match.group("subject") or "").strip()
            return f"{subject} 类似书籍 推荐"
    return clause.text
