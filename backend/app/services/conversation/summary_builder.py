from __future__ import annotations

import hashlib
import json

from app.services.conversation.journal_contracts import ConversationJournalEvent
from app.services.conversation.summary_contracts import (
    ConversationSummary,
    ConversationSummaryCandidate,
    SummaryProvider,
)


class SummaryBuildError(ValueError):
    """Raised when journal evidence cannot produce a trustworthy summary."""


class SummaryBuilder:
    """Validate one cumulative summary derivation; it performs no persistence."""

    def __init__(self, provider: SummaryProvider) -> None:
        self._provider = provider

    async def build(
        self,
        *,
        previous: ConversationSummary | None,
        events: list[ConversationJournalEvent],
    ) -> ConversationSummaryCandidate:
        ordered = sorted(events, key=lambda event: event.sequence_no)
        if not ordered:
            raise SummaryBuildError("summary requires journal events")
        self._validate_events(previous, ordered)
        draft = await self._provider.summarize(
            previous=previous,
            events=ordered,
        )
        self._validate_previous_preserved(
            previous,
            draft.structured_content,
        )
        from_sequence = (
            previous.from_sequence
            if previous is not None
            else ordered[0].sequence_no
        )
        to_sequence = ordered[-1].sequence_no
        self._validate_statements(
            draft.structured_content.statements,
            from_sequence=from_sequence,
            to_sequence=to_sequence,
        )
        receipt_refs = {
            receipt
            for event in ordered
            for receipt in event.receipt_refs
        }
        if previous is not None:
            receipt_refs.update(
                previous.structured_content.receipt_refs
            )
        unsupported = sorted(
            set(draft.structured_content.receipt_refs) - receipt_refs
        )
        if unsupported:
            raise SummaryBuildError(
                "summary cites receipts absent from Journal: "
                + ", ".join(unsupported)
            )
        return ConversationSummaryCandidate(
            user_id=ordered[0].user_id,
            thread_id=ordered[0].thread_id,
            from_sequence=from_sequence,
            to_sequence=to_sequence,
            previous_summary_id=previous.id if previous is not None else None,
            structured_content=draft.structured_content,
            source_hash=_source_hash(previous, ordered),
            model_id=draft.model_id,
            prompt_version=draft.prompt_version,
        )

    @staticmethod
    def _validate_events(
        previous: ConversationSummary | None,
        events: list[ConversationJournalEvent],
    ) -> None:
        owner = (events[0].user_id, events[0].thread_id)
        if any((event.user_id, event.thread_id) != owner for event in events):
            raise SummaryBuildError("summary events cross user or thread boundary")
        expected = (
            previous.to_sequence + 1
            if previous is not None
            else events[0].sequence_no
        )
        for event in events:
            if event.sequence_no != expected:
                raise SummaryBuildError("summary event range is not contiguous")
            expected += 1
        if previous is not None and (
            previous.user_id,
            previous.thread_id,
        ) != owner:
            raise SummaryBuildError("previous summary ownership mismatch")
        if events[-1].role != "assistant":
            raise SummaryBuildError(
                "summary cutoff must end at a published assistant event"
            )

    @staticmethod
    def _validate_statements(
        statements,
        *,
        from_sequence: int,
        to_sequence: int,
    ) -> None:
        for statement in statements:
            if any(
                sequence < from_sequence or sequence > to_sequence
                for sequence in statement.source_sequences
            ):
                raise SummaryBuildError(
                    "summary statement cites sequence outside covered range"
                )

    @staticmethod
    def _validate_previous_preserved(previous, current) -> None:
        if previous is None:
            return
        for field in (
            "user_requests",
            "user_statements",
            "decisions",
            "corrections",
            "unresolved",
            "active_tasks",
        ):
            old = {
                (
                    item.text,
                    tuple(item.source_sequences),
                )
                for item in getattr(previous.structured_content, field)
            }
            new = {
                (
                    item.text,
                    tuple(item.source_sequences),
                )
                for item in getattr(current, field)
            }
            if not old.issubset(new):
                raise SummaryBuildError(
                    f"cumulative summary dropped prior {field}"
                )
        if not set(previous.structured_content.receipt_refs).issubset(
            current.receipt_refs
        ):
            raise SummaryBuildError(
                "cumulative summary dropped prior receipt references"
            )


def _source_hash(
    previous: ConversationSummary | None,
    events: list[ConversationJournalEvent],
) -> str:
    material = {
        "previous_source_hash": (
            previous.source_hash if previous is not None else None
        ),
        "events": [
            {
                "id": str(event.id),
                "sequence_no": event.sequence_no,
                "event_type": event.event_type,
                "role": event.role,
                "content": event.content,
                "receipt_refs": event.receipt_refs,
            }
            for event in events
        ],
    }
    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = ["SummaryBuildError", "SummaryBuilder"]
