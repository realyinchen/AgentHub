from __future__ import annotations

from app.services.agent_core.contracts import PublishedAnswer
from app.services.agent_core.publication.contracts import (
    CommittedPublication,
    PublicExecutionGraph,
    TrustedStreamEvent,
)


class TrustedStreamSequencer:
    """Issue ordered public events; it performs no execution or persistence."""

    def __init__(self, *, request_id: str) -> None:
        self._request_id = str(request_id or "").strip()
        if not self._request_id:
            raise ValueError("trusted stream requires request_id")
        self._sequence = 0
        self._started = False
        self._terminal = False

    def turn_started(self) -> TrustedStreamEvent:
        if self._sequence:
            raise ValueError("turn.started must be the first event")
        self._started = True
        return self._event("turn.started", {})

    def graph_snapshot(
        self,
        graph: PublicExecutionGraph,
    ) -> TrustedStreamEvent:
        self._require_open()
        return self._event(
            "graph.snapshot",
            {"graph": graph.model_dump(mode="json")},
        )

    def answer_completed(
        self,
        *,
        answer: PublishedAnswer,
        committed: CommittedPublication | None,
    ) -> TrustedStreamEvent:
        self._require_open()
        if (
            committed is None
            or committed.journal_event.event_type
            != "assistant_published"
            or committed.journal_event.request_id != self._request_id
        ):
            raise ValueError(
                "answer.completed requires a committed assistant_published event"
            )
        if committed.journal_event.content != answer.content:
            raise ValueError(
                "committed publication content does not match the answer"
            )
        self._terminal = True
        return self._event(
            "answer.completed",
            {
                "answer": answer.model_dump(mode="json"),
                "message": committed.message.model_dump(mode="json"),
                "journal_sequence": (
                    committed.journal_event.sequence_no
                ),
            },
        )

    def clarification_required(
        self,
        *,
        answer: PublishedAnswer,
        committed: CommittedPublication,
    ) -> TrustedStreamEvent:
        self._require_open()
        if (
            answer.status != "clarification_required"
            or committed.journal_event.event_type
            != "clarification_requested"
        ):
            raise ValueError(
                "clarification event requires a committed clarification"
            )
        self._terminal = True
        return self._event(
            "clarification.required",
            {
                "answer": answer.model_dump(mode="json"),
                "message": committed.message.model_dump(mode="json"),
                "journal_sequence": (
                    committed.journal_event.sequence_no
                ),
            },
        )

    def turn_failed(
        self,
        *,
        committed: CommittedPublication,
        message: str,
    ) -> TrustedStreamEvent:
        self._require_open()
        if committed.journal_event.event_type != "turn_failed":
            raise ValueError(
                "turn.failed requires a committed turn_failed event"
            )
        safe_code = str(
            committed.journal_event.content or "turn_failed"
        ).strip().lower()
        if not safe_code.replace("_", "").replace("-", "").isalnum():
            safe_code = "turn_failed"
        self._terminal = True
        return self._event(
            "turn.failed",
            {
                "code": safe_code[:128],
                "message": str(message or "本轮未能安全完成。").strip()[:500],
            },
        )

    def _require_open(self) -> None:
        if not self._started:
            raise ValueError("turn.started must precede stream events")
        if self._terminal:
            raise ValueError("trusted stream is already terminal")

    def _event(
        self,
        event_type: str,
        content: dict,
    ) -> TrustedStreamEvent:
        self._sequence += 1
        return TrustedStreamEvent(
            sequence=self._sequence,
            type=event_type,
            request_id=self._request_id,
            content=content,
        )


__all__ = ["TrustedStreamSequencer"]
