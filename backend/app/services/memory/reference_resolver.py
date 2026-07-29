from __future__ import annotations

import re

from app.services.conversation.contracts import ConversationWindow
from app.services.memory.identity import extract_declared_name, is_valid_person_name
from app.services.memory.write_contracts import (
    MemoryReferenceResolution,
    MemorySourceEvidence,
    MemoryWriteRequest,
)


_MEMORY_COMMAND_RE = re.compile(
    r"^(?:先)?(?:请你|请|帮我)?(?:记住|记一下|记下来|保存(?:下来)?|别忘了)"
    r"\s*[:：]?\s*",
    re.IGNORECASE,
)
_DIRECT_ASSERTION_RE = re.compile(
    r"(?:^|[，,。.!！\s])我(?:现在|以后|平时|通常|一直|还)?"
    r"(?:不)?(?:叫|是|喜欢|偏好|只看|不看|住在|从事|有|养着)|"
    r"\b(?:my\s+name\s+is|i\s+(?:am|like|prefer|live|work|have))\b",
    re.IGNORECASE,
)
_NAME_REFERENCE_RE = re.compile(
    r"^(?:我的)?(?:名字|姓名|称呼)$|\bmy\s+name\b",
    re.IGNORECASE,
)
_DEICTIC_REFERENCE_RE = re.compile(
    r"^(?:这个|那个|这些|那些|它|他|她|这件事|那件事|"
    r"this|that|it|him|her)$",
    re.IGNORECASE,
)
_GENERIC_REFERENCE_RE = re.compile(
    r"^(?:我的)(?:信息|资料|情况|偏好|喜好|习惯|状态)$",
    re.IGNORECASE,
)


class MemoryReferenceResolver:
    """Resolve write targets against user-authored turns; never writes memory."""

    def resolve(
        self,
        request: MemoryWriteRequest,
        window: ConversationWindow,
    ) -> MemoryReferenceResolution:
        utterance = request.utterance.strip()
        continuation = request.clarification
        if continuation is not None:
            target = continuation.target_expression.strip()
            if _NAME_REFERENCE_RE.fullmatch(target):
                name = utterance.strip(" ，,。.!！?？")
                if is_valid_person_name(name):
                    return MemoryReferenceResolution(
                        status="resolved",
                        source=MemorySourceEvidence(
                            source_kind="current_user_assertion",
                            turn_offset=0,
                            excerpt=utterance,
                        ),
                        resolved_text=f"我的名字是{name}",
                        reason_codes=[
                            "name_completed_from_clarification_answer"
                        ],
                    )
                return MemoryReferenceResolution(
                    status="clarification_required",
                    clarification_question="请直接告诉我你的名字，例如“我的名字是冰露”。",
                    reason_codes=["clarification_answer_is_not_a_valid_name"],
                )
            if _DIRECT_ASSERTION_RE.search(utterance):
                return _resolved_current(
                    utterance,
                    "complete_fact_supplied_after_clarification",
                )
            return MemoryReferenceResolution(
                status="clarification_required",
                clarification_question="请用一句完整事实说明你希望我记住什么。",
                reason_codes=["clarification_answer_still_incomplete"],
            )

        body = _MEMORY_COMMAND_RE.sub("", utterance).strip(" ，,。.!！")
        target = (request.target_expression or body).strip(" ，,。.!！")

        if _DIRECT_ASSERTION_RE.search(utterance):
            return _resolved_current(utterance, "current_turn_contains_assertion")

        if not request.explicit:
            return _resolved_current(utterance, "implicit_direct_assertion")

        if target and not (
            _NAME_REFERENCE_RE.fullmatch(target)
            or _DEICTIC_REFERENCE_RE.fullmatch(target)
            or _GENERIC_REFERENCE_RE.fullmatch(target)
        ):
            return _resolved_current(utterance, "explicit_self_contained_fact")

        if _NAME_REFERENCE_RE.fullmatch(target):
            for turn in reversed(window.user_turns):
                if extract_declared_name(turn.content):
                    return MemoryReferenceResolution(
                        status="resolved",
                        source=MemorySourceEvidence(
                            source_kind="prior_user_assertion",
                            turn_offset=turn.turn_offset,
                            excerpt=turn.content,
                        ),
                        resolved_text=turn.content,
                        reason_codes=["name_reference_resolved_from_user_turn"],
                    )
            return MemoryReferenceResolution(
                status="clarification_required",
                clarification_question="你希望我记住的名字是什么？",
                reason_codes=["name_reference_has_no_user_assertion"],
            )

        if _DEICTIC_REFERENCE_RE.fullmatch(target) or _GENERIC_REFERENCE_RE.fullmatch(
            target
        ):
            if window.user_turns:
                turn = window.user_turns[-1]
                return MemoryReferenceResolution(
                    status="resolved",
                    source=MemorySourceEvidence(
                        source_kind="prior_user_assertion",
                        turn_offset=turn.turn_offset,
                        excerpt=turn.content,
                    ),
                    resolved_text=turn.content,
                    reason_codes=["deictic_reference_resolved_to_previous_user_turn"],
                )
            return MemoryReferenceResolution(
                status="clarification_required",
                clarification_question="你希望我记住哪一条具体信息？",
                reason_codes=["referential_request_has_no_user_turn"],
            )

        return MemoryReferenceResolution(
            status="clarification_required",
            clarification_question="请直接说明你希望我长期记住的完整事实。",
            reason_codes=["memory_target_not_resolved"],
        )


def _resolved_current(text: str, reason: str) -> MemoryReferenceResolution:
    return MemoryReferenceResolution(
        status="resolved",
        source=MemorySourceEvidence(
            source_kind="current_user_assertion",
            turn_offset=0,
            excerpt=text,
        ),
        resolved_text=text,
        reason_codes=[reason],
    )
