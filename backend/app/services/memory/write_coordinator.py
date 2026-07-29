from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.schemas.chat import UserInput
from app.services.conversation.contracts import ConversationWindow
from app.services.memory.committer import MemoryCommitter
from app.services.memory.fact_extractor import MemoryFactExtractor
from app.services.memory.persistence_policy import MemoryPersistencePolicy
from app.services.memory.reference_resolver import MemoryReferenceResolver
from app.services.memory.write_contracts import (
    MemoryClarificationContext,
    MemoryCommitCommand,
    MemoryWriteOutcome,
    MemoryWriteRequest,
)


class MemoryWriteCoordinator:
    """Orchestrate the pre-commit use case without owning domain rules."""

    def __init__(
        self,
        *,
        reference_resolver: MemoryReferenceResolver | None = None,
        fact_extractor: MemoryFactExtractor | None = None,
        persistence_policy: MemoryPersistencePolicy | None = None,
        committer: MemoryCommitter | None = None,
    ) -> None:
        self._references = reference_resolver or MemoryReferenceResolver()
        self._facts = fact_extractor or MemoryFactExtractor()
        self._policy = persistence_policy or MemoryPersistencePolicy()
        self._committer = committer or MemoryCommitter()

    async def process(
        self,
        request: MemoryWriteRequest,
        *,
        user_input: UserInput,
        conversation: ConversationWindow,
        user_id: UUID,
        thread_id: UUID | None,
        model_id: str = "",
    ) -> MemoryWriteOutcome:
        resolution = self._references.resolve(request, conversation)
        if resolution.status == "clarification_required":
            return MemoryWriteOutcome(
                status="clarification_required",
                clarification_question=resolution.clarification_question,
                pending_clarification=_pending_clarification(
                    request,
                    question=resolution.clarification_question,
                    kind="reference",
                ),
                reason_codes=resolution.reason_codes,
            )

        drafts = self._facts.deterministic(
            user_input=user_input,
            resolution=resolution,
        )
        if (
            not drafts
            and request.explicit
            and request.semantic_fallback_allowed
        ):
            try:
                drafts = [
                    await self._facts.semantic(
                        resolution=resolution,
                        model_id=model_id,
                    )
                ]
            except Exception as exc:
                return MemoryWriteOutcome(
                    status="clarification_required",
                    clarification_question=(
                        "我暂时无法可靠地解析这条信息，请直接用完整事实表述一次。"
                    ),
                    pending_clarification=_pending_clarification(
                        request,
                        question=(
                            "我暂时无法可靠地解析这条信息，"
                            "请直接用完整事实表述一次。"
                        ),
                        kind="completeness",
                    ),
                    reason_codes=[
                        "semantic_interpretation_unavailable",
                        type(exc).__name__,
                    ],
                )

        decision = self._policy.decide(request, drafts)
        if decision.status != "commit_ready":
            status = (
                "clarification_required"
                if decision.status == "clarification_required"
                else "rejected"
            )
            return MemoryWriteOutcome(
                status=status,
                clarification_question=decision.clarification_question,
                pending_clarification=(
                    _pending_clarification(
                        request,
                        question=decision.clarification_question,
                        kind="completeness",
                    )
                    if status == "clarification_required"
                    else None
                ),
                reason_codes=decision.reason_codes,
            )

        return await self._committer.commit(
            MemoryCommitCommand(facts=decision.facts),
            user_id=user_id,
            thread_id=thread_id,
        )


def _pending_clarification(
    request: MemoryWriteRequest,
    *,
    question: str,
    kind: Literal["reference", "completeness", "conflict"],
) -> MemoryClarificationContext:
    previous = request.clarification
    return MemoryClarificationContext(
        kind=kind,
        original_utterance=(
            previous.original_utterance
            if previous is not None
            else request.utterance
        ),
        target_expression=(
            request.target_expression
            or (
                previous.target_expression
                if previous is not None
                else ""
            )
        ),
        question=question,
    )
