from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from app.infra.database import get_database
from app.models.base import utc_now
from app.models.memory import MemoryEventRecord
from app.services.memory.contracts import (
    USER_STATE_CATEGORIES,
    MemoryEvent,
    normalize_memory_token,
    normalize_memory_value,
    validate_memory_token,
)
from app.services.memory.providers.postgres import PostgresMemoryProvider
from app.services.memory.semantic_interpreter import (
    UserStateOrganization,
    interpret_user_state,
)


logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()
_SCHEDULED_MEMORY_IDS: set[UUID] = set()
_EXPLICIT_MEMORY_RE = re.compile(
    r"(?:请|帮我|你)?(?:记住|记一下|记下来|别忘了)|\b(?:remember|save|note)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_RE = re.compile(r"(?:^|[，,。.!\s])(?:我|我的|我们)|\b(?:i|i'm|i am|my|we|our)\b", re.IGNORECASE)
_QUESTION_RE = re.compile(
    r"[?？]|(?:为什么|怎么|如何|哪里|哪儿|哪些|哪种|哪个|什么|吗|呢|是否|能不能|会不会)|"
    r"\b(?:why|how|what|where|when|can|could|would|should|do|does|is|are)\b",
    re.IGNORECASE,
)
_REQUEST_RE = re.compile(
    r"(?:帮我|请你|给我|替我|搜索|搜一下|查一下|查询|推荐|研究|分析|总结|翻译|写一|生成)|"
    r"\b(?:please|search|find|recommend|research|analy[sz]e|summari[sz]e|translate|write|create)\b",
    re.IGNORECASE,
)


class UserStateCaptureDecision(BaseModel):
    should_capture: bool = False
    explicit: bool = False
    reason: str = ""


class UserStateCaptureResult(BaseModel):
    status: str
    memory: MemoryEvent | None = None
    duration_ms: int = 0
    organization_scheduled: bool = False


class UserStateConfirmation(BaseModel):
    accept: bool = True
    category: str | None = None
    state_key: str | None = None
    summary: str | None = None
    state_value: dict[str, Any] | None = None
    relation: dict[str, Any] | None = None
    use_when: list[str] | None = None


def decide_user_state_capture(text: str) -> UserStateCaptureDecision:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) < 2 or len(normalized) > 1200:
        return UserStateCaptureDecision(reason="outside_capture_length")

    explicit = bool(_EXPLICIT_MEMORY_RE.search(normalized))
    if explicit:
        return UserStateCaptureDecision(
            should_capture=True,
            explicit=True,
            reason="explicit_memory_request",
        )

    if not _FIRST_PERSON_RE.search(normalized):
        return UserStateCaptureDecision(reason="not_user_state")
    if _QUESTION_RE.search(normalized):
        return UserStateCaptureDecision(reason="question_not_state")
    if _REQUEST_RE.search(normalized):
        return UserStateCaptureDecision(reason="task_request_not_state")
    return UserStateCaptureDecision(
        should_capture=True,
        explicit=False,
        reason="first_person_declarative_state",
    )


async def persist_raw_user_state(
    *,
    user_id: UUID,
    thread_id: UUID | None,
    raw_text: str,
    explicit: bool,
    organizer_model_id: str = "",
    schedule_organization: bool = True,
    route_type: str = "slow_path",
) -> UserStateCaptureResult:
    """Reject the retired raw-first write path.

    Legacy pending records may still be organized for migration, but no new
    durable row may be created before semantic resolution.
    """
    started = time.perf_counter()
    text = " ".join(str(raw_text or "").split()).strip()
    if not text:
        return UserStateCaptureResult(status="skipped")
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.warning(
        "raw-first memory write rejected route_type=%s explicit=%s duration_ms=%d",
        route_type,
        explicit,
        duration_ms,
    )
    return UserStateCaptureResult(
        status="rejected_raw_first",
        memory=None,
        duration_ms=duration_ms,
        organization_scheduled=False,
    )


def schedule_user_state_organization(memory_id: UUID, user_id: UUID) -> bool:
    if memory_id in _SCHEDULED_MEMORY_IDS:
        return False
    try:
        _SCHEDULED_MEMORY_IDS.add(memory_id)
        task = asyncio.create_task(
            organize_user_state(memory_id=memory_id, user_id=user_id),
            name=f"organize-user-state-{memory_id}",
        )
    except RuntimeError:
        _SCHEDULED_MEMORY_IDS.discard(memory_id)
        return False
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(
        lambda completed: (
            _BACKGROUND_TASKS.discard(completed),
            _SCHEDULED_MEMORY_IDS.discard(memory_id),
        )
    )
    return True


async def schedule_pending_user_state_organization(
    user_id: UUID,
    *,
    limit: int = 10,
) -> int:
    db = get_database()
    async with db.session() as session:
        result = await session.execute(
            select(MemoryEventRecord.id)
            .where(
                MemoryEventRecord.user_id == user_id,
                MemoryEventRecord.type == "state",
                MemoryEventRecord.is_deleted.is_(False),
                MemoryEventRecord.superseded_by.is_(None),
                MemoryEventRecord.metadata_json["user_state"]["status"].astext
                == "pending",
            )
            .order_by(MemoryEventRecord.created_at.asc())
            .limit(max(1, min(limit, 25)))
        )
        ids = list(result.scalars().all())
    return sum(schedule_user_state_organization(item, user_id) for item in ids)


async def organize_user_state(*, memory_id: UUID, user_id: UUID) -> None:
    started = time.perf_counter()
    try:
        record = await _load_record(memory_id=memory_id, user_id=user_id)
        if record is None:
            return
        user_state = dict((record.metadata_json or {}).get("user_state") or {})
        if user_state.get("status") != "pending":
            return
        proposal = await interpret_user_state(
            str(user_state.get("raw_text") or record.value),
            requested_model_id=str(user_state.get("organizer_model_id") or ""),
        )
        await apply_user_state_organization(
            memory_id=memory_id,
            user_id=user_id,
            proposal=proposal,
        )
        logger.info(
            "memory_organization memory_id=%s status=completed duration_ms=%d",
            memory_id,
            int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        logger.warning("Memory organization failed for %s: %s", memory_id, exc)
        await _record_organization_error(memory_id=memory_id, user_id=user_id, error=exc)


async def apply_user_state_organization(
    *,
    memory_id: UUID,
    user_id: UUID,
    proposal: UserStateOrganization,
) -> MemoryEvent:
    db = get_database()
    async with db.session() as session:
        record = await session.get(MemoryEventRecord, memory_id)
        if record is None or record.user_id != user_id:
            raise LookupError("user state memory not found")

        metadata = dict(record.metadata_json or {})
        user_state = dict(metadata.get("user_state") or {})
        state_key = proposal.state_key or _fallback_state_key(proposal)
        conflicts = await _find_state_key_conflicts(
            session=session,
            record=record,
            state_key=state_key,
            state_value=proposal.state_value,
            summary=proposal.summary,
        )
        needs_confirmation = proposal.needs_confirmation or bool(conflicts)
        question = proposal.confirmation_question
        if needs_confirmation and not question:
            question = f"我理解为“{proposal.summary}”，是否准确？"
        valid_until = None
        if proposal.category == "short_term":
            ttl_hours = proposal.ttl_hours or 72
            valid_until = utc_now() + timedelta(hours=ttl_hours)

        user_state.update(
            {
                "status": "needs_confirmation" if needs_confirmation else "active",
                "category": proposal.category,
                "state_key": state_key,
                "summary": proposal.summary,
                "raw_text": str(user_state.get("raw_text") or record.value),
                "state_value": proposal.state_value,
                "relation": proposal.relation,
                "use_when": proposal.use_when,
                "valid_until": valid_until.isoformat() if valid_until else None,
                "confirmation_question": question,
                "organizer_confidence": proposal.confidence,
                "organized_at": utc_now().isoformat(),
                "organization_attempts": int(user_state.get("organization_attempts") or 0)
                + 1,
                "conflict_with": [str(item.id) for item in conflicts],
            }
        )
        metadata["user_state"] = user_state
        record.type = _legacy_type(proposal.category)
        record.subject = _legacy_subject(proposal)
        record.value = proposal.summary
        record.confidence = proposal.confidence
        record.metadata_json = metadata
        record.updated_at = utc_now()
        await session.flush()
        await session.refresh(record)
        return PostgresMemoryProvider(session)._event_from_record(record)


async def confirm_user_state(
    *,
    user_id: UUID,
    memory_id: UUID,
    confirmation: UserStateConfirmation,
) -> MemoryEvent:
    db = get_database()
    async with db.session() as session:
        record = await session.get(MemoryEventRecord, memory_id)
        if record is None or record.user_id != user_id:
            raise LookupError("user state memory not found")
        metadata = dict(record.metadata_json or {})
        user_state = dict(metadata.get("user_state") or {})
        if not confirmation.accept:
            user_state["status"] = "forgotten"
            user_state["confirmed_at"] = utc_now().isoformat()
            metadata["user_state"] = user_state
            record.metadata_json = metadata
            record.is_deleted = True
            record.deleted_at = utc_now()
            record.updated_at = utc_now()
            await session.flush()
            await session.refresh(record)
            return PostgresMemoryProvider(session)._event_from_record(record)

        updates = confirmation.model_dump(exclude_none=True, exclude={"accept"})
        for key, value in updates.items():
            if key == "category" and value is not None:
                value = validate_memory_token("category", value, USER_STATE_CATEGORIES)
            user_state[key] = value
        user_state["status"] = "active"
        user_state["confirmation_question"] = ""
        user_state["confirmed_at"] = utc_now().isoformat()
        metadata["user_state"] = user_state
        record.metadata_json = metadata
        record.value = str(user_state.get("summary") or confirmation.summary or record.value)
        record.updated_at = utc_now()

        conflict_ids = user_state.get("conflict_with") or []
        for conflict_id in conflict_ids:
            try:
                conflict = await session.get(MemoryEventRecord, UUID(str(conflict_id)))
            except (TypeError, ValueError):
                continue
            if conflict is None or conflict.user_id != user_id or conflict.id == record.id:
                continue
            conflict.superseded_by = record.id
            conflict_metadata = dict(conflict.metadata_json or {})
            conflict_state = dict(conflict_metadata.get("user_state") or {})
            conflict_state["status"] = "superseded"
            conflict_metadata["user_state"] = conflict_state
            conflict.metadata_json = conflict_metadata
            conflict.updated_at = utc_now()
        await session.flush()
        await session.refresh(record)
        return PostgresMemoryProvider(session)._event_from_record(record)


async def _load_record(*, memory_id: UUID, user_id: UUID) -> MemoryEventRecord | None:
    db = get_database()
    async with db.session() as session:
        record = await session.get(MemoryEventRecord, memory_id)
        if record is None or record.user_id != user_id:
            return None
        session.expunge(record)
        return record


async def _find_state_key_conflicts(
    *,
    session: Any,
    record: MemoryEventRecord,
    state_key: str,
    state_value: dict[str, Any],
    summary: str,
) -> list[MemoryEventRecord]:
    result = await session.execute(
        select(MemoryEventRecord)
        .where(
            MemoryEventRecord.user_id == record.user_id,
            MemoryEventRecord.id != record.id,
            MemoryEventRecord.is_deleted.is_(False),
            MemoryEventRecord.superseded_by.is_(None),
        )
        .order_by(MemoryEventRecord.updated_at.desc())
        .limit(200)
    )
    desired = json.dumps(state_value, ensure_ascii=False, sort_keys=True) or summary
    conflicts: list[MemoryEventRecord] = []
    for item in result.scalars().all():
        existing = dict((item.metadata_json or {}).get("user_state") or {})
        if existing.get("status") not in {None, "active"}:
            continue
        if str(existing.get("state_key") or "") != state_key:
            continue
        current_value = existing.get("state_value") or item.value
        current = (
            json.dumps(current_value, ensure_ascii=False, sort_keys=True)
            if isinstance(current_value, (dict, list))
            else str(current_value)
        )
        if current != desired:
            conflicts.append(item)
    return conflicts


async def _record_organization_error(*, memory_id: UUID, user_id: UUID, error: Exception) -> None:
    try:
        db = get_database()
        async with db.session() as session:
            record = await session.get(MemoryEventRecord, memory_id)
            if record is None or record.user_id != user_id:
                return
            metadata = dict(record.metadata_json or {})
            user_state = dict(metadata.get("user_state") or {})
            user_state["organization_attempts"] = int(
                user_state.get("organization_attempts") or 0
            ) + 1
            user_state["last_organization_error"] = str(error)[:500]
            user_state["last_organization_attempt_at"] = utc_now().isoformat()
            metadata["user_state"] = user_state
            record.metadata_json = metadata
            record.updated_at = utc_now()
    except Exception:
        logger.exception("Unable to record memory organization error")


def _fallback_state_key(proposal: UserStateOrganization) -> str:
    raw = normalize_memory_token(proposal.summary)
    token = re.sub(r"[^\w\u4e00-\u9fff]+", ".", raw).strip(".")
    return f"{proposal.category}.{token[:100] or 'state'}"


def _legacy_type(category: str) -> str:
    return {
        "profile": "preference",
        "preference": "preference",
        "relation": "entity",
        "feedback": "feedback",
        "short_term": "state",
    }[category]


def _legacy_subject(proposal: UserStateOrganization) -> str:
    if proposal.category == "relation":
        return "entity"
    if proposal.category == "feedback" and proposal.state_value.get("book_title"):
        return "book"
    if proposal.category == "preference":
        return "content"
    return "user"
