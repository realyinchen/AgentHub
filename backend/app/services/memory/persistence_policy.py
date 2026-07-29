from __future__ import annotations

from app.services.memory.fact_validator import MemoryFactValidator
from app.services.memory.write_contracts import (
    MemoryFactDraft,
    MemoryWriteDecision,
    MemoryWriteRequest,
)


class MemoryPersistencePolicy:
    """Turn validated drafts into a fail-closed pre-commit decision."""

    def __init__(self, validator: MemoryFactValidator | None = None) -> None:
        self._validator = validator or MemoryFactValidator()

    def decide(
        self,
        request: MemoryWriteRequest,
        drafts: list[MemoryFactDraft],
    ) -> MemoryWriteDecision:
        if not drafts:
            if request.explicit:
                return MemoryWriteDecision(
                    status="clarification_required",
                    clarification_question=(
                        "我还不能确定要保存的完整事实，请直接说明希望我记住什么。"
                    ),
                    reason_codes=["no_complete_fact_extracted"],
                )
            return MemoryWriteDecision(
                status="rejected",
                reason_codes=["implicit_text_has_no_commit_ready_fact"],
            )

        resolved = []
        invalid_reasons: list[str] = []
        clarification = ""
        for draft in drafts:
            reasons = self._validator.reasons(draft)
            if reasons:
                invalid_reasons.extend(reasons)
                clarification = clarification or draft.clarification_question
                continue
            resolved.append(self._validator.resolve(draft))

        if invalid_reasons:
            if request.explicit:
                return MemoryWriteDecision(
                    status="clarification_required",
                    clarification_question=clarification
                    or _clarification_for(invalid_reasons),
                    reason_codes=list(dict.fromkeys(invalid_reasons)),
                )
            return MemoryWriteDecision(
                status="rejected",
                reason_codes=list(dict.fromkeys(invalid_reasons)),
            )

        return MemoryWriteDecision(
            status="commit_ready",
            facts=resolved,
            reason_codes=["all_precommit_gates_passed"],
        )


def _clarification_for(reasons: list[str]) -> str:
    reason_set = set(reasons)
    if "durability_not_long_term" in reason_set or "not_long_term_category" in reason_set:
        return "这似乎是临时状态。你希望保存多久，还是只在当前会话中使用？"
    if "unresolved_reference" in reason_set or "referential_value_not_resolved" in reason_set:
        return "其中仍有未明确的指代，请直接说明具体对象和值。"
    if "source_not_user_assertion" in reason_set:
        return "这条信息不是你直接陈述的事实，请确认是否确实要长期保存。"
    return "我还不能无歧义地理解这条信息，请用完整陈述再说一次。"
