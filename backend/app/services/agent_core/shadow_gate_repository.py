from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_shadow_observation import (
    AgentShadowObservationRecord,
)
from app.models.conversation_event import ConversationEventRecord
from app.models.task import ActionExecutionReceiptRecord
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateRawTurn,
    ShadowGateRawWindow,
    ShadowGateReadRequest,
    ShadowLegacyTerminal,
)
from app.services.agent_core.shadow_observation_key import (
    shadow_audit_request_id,
    shadow_observation_key_from_identity,
)
from app.services.agent_core.shadow_observation_repository import (
    observation_from_record,
)
from app.services.agent_core.shadow_observation_contracts import (
    ShadowObservation,
)


class ShadowGateRepository:
    """Read one immutable Shadow evidence window without evaluating it."""

    async def read(
        self,
        db: AsyncSession,
        request: ShadowGateReadRequest,
    ) -> ShadowGateRawWindow:
        enrollment = ConversationEventRecord.shadow_enrollment_json
        filters = [
            ConversationEventRecord.event_type == "user_message",
            ConversationEventRecord.created_at >= request.window_started_at,
            ConversationEventRecord.created_at < request.window_ended_at,
            enrollment.is_not(None),
            enrollment["schema_version"].astext
            == "agent-shadow-enrollment-v2",
            enrollment["source_commit_sha"].astext == request.commit_sha,
            enrollment["controller_fingerprint"].astext
            == request.controller_fingerprint,
            enrollment["prompt_version"].astext == request.prompt_version,
        ]
        if request.thread_id is not None:
            filters.append(
                ConversationEventRecord.thread_id == request.thread_id
            )
        if request.request_ids:
            filters.append(
                ConversationEventRecord.request_id.in_(request.request_ids)
            )
        result = await db.execute(
            select(ConversationEventRecord)
            .where(*filters)
            .order_by(
                ConversationEventRecord.created_at.asc(),
                ConversationEventRecord.id.asc(),
            )
        )
        enrollments = list(result.scalars().all())
        if not enrollments:
            return ShadowGateRawWindow(request=request)

        identities = [
            (item.thread_id, item.request_id)
            for item in enrollments
        ]
        keys = {
            identity: shadow_observation_key_from_identity(
                thread_id=identity[0],
                request_id=identity[1],
                controller_fingerprint=request.controller_fingerprint,
            )
            for identity in identities
        }
        terminals = await self._terminal_events(db, identities)
        observations = await self._observations(
            db,
            list(keys.values()),
        )
        receipt_counts = await self._receipt_counts(
            db,
            list(keys.values()),
        )
        turns = []
        for record in enrollments:
            identity = (record.thread_id, record.request_id)
            key = keys[identity]
            turns.append(
                ShadowGateRawTurn(
                    observation_key=key,
                    enrolled_at=record.created_at,
                    journal_sequence_watermark=record.sequence_no,
                    terminal_events=terminals.get(identity, []),
                    observation=observations.get(key),
                    audit_receipt_count=receipt_counts.get(key, 0),
                )
            )
        return ShadowGateRawWindow(
            request=request,
            turns=turns,
        )

    async def _terminal_events(
        self,
        db: AsyncSession,
        identities: list[tuple],
    ) -> dict[tuple, list[ShadowLegacyTerminal]]:
        result = await db.execute(
            select(ConversationEventRecord).where(
                tuple_(
                    ConversationEventRecord.thread_id,
                    ConversationEventRecord.request_id,
                ).in_(identities),
                ConversationEventRecord.event_type.in_(
                    (
                        "assistant_published",
                        "clarification_requested",
                        "turn_failed",
                    )
                ),
            )
        )
        mapped: dict[tuple, list[ShadowLegacyTerminal]] = defaultdict(list)
        for record in result.scalars().all():
            mapped[(record.thread_id, record.request_id)].append(
                ShadowLegacyTerminal(
                    event_type=record.event_type,
                    sequence_no=record.sequence_no,
                    summary=_legacy_terminal_summary(record),
                )
            )
        return dict(mapped)

    async def _observations(
        self,
        db: AsyncSession,
        keys: list[str],
    ) -> dict[str, ShadowObservation]:
        result = await db.execute(
            select(AgentShadowObservationRecord).where(
                AgentShadowObservationRecord.observation_key.in_(keys)
            )
        )
        return {
            record.observation_key: observation_from_record(record)
            for record in result.scalars().all()
        }

    async def _receipt_counts(
        self,
        db: AsyncSession,
        keys: list[str],
    ) -> dict[str, int]:
        audit_ids = {
            shadow_audit_request_id(key): key
            for key in keys
        }
        result = await db.execute(
            select(
                ActionExecutionReceiptRecord.request_id,
                func.count(ActionExecutionReceiptRecord.id),
            )
            .where(
                ActionExecutionReceiptRecord.request_id.in_(
                    list(audit_ids)
                )
            )
            .group_by(ActionExecutionReceiptRecord.request_id)
        )
        return {
            audit_ids[request_id]: int(count)
            for request_id, count in result.all()
        }


def _legacy_terminal_summary(
    record: ConversationEventRecord,
) -> dict:
    if record.event_type != "assistant_published":
        return {"terminal_kind": record.event_type}
    metadata = dict(record.metadata_json or {})
    chat_message = metadata.get("chat_message")
    chat = chat_message if isinstance(chat_message, dict) else {}
    custom_data = chat.get("custom_data")
    custom = custom_data if isinstance(custom_data, dict) else {}
    trace_value = custom.get("runtime_trace")
    trace = trace_value if isinstance(trace_value, dict) else {}
    tool_value = custom.get("tool_info")
    tools = tool_value if isinstance(tool_value, list) else []
    return {
        "terminal_kind": "assistant_published",
        "runtime_trace": {
            key: trace[key]
            for key in (
                "route_type",
                "intent",
                "planner_used",
                "plan_source",
                "receipt_status",
            )
            if key in trace
        },
        "operations": [
            str(item.get("name"))
            for item in tools
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
        ],
    }


__all__ = ["ShadowGateRepository"]
