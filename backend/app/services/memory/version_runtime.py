from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from app.infra.database import get_database
from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.conversation import ConversationEventRepository
from app.services.memory.canonicalizer import MemoryCanonicalizer
from app.services.memory.version_contracts import (
    ForgetMemoryRequest,
    MemoryVersionCommitCommand,
    MemoryVersionForgetCommand,
    RememberMemoryRequest,
    SearchMemoryRequest,
)
from app.services.memory.version_search import VersionedMemorySearch
from app.services.memory.version_store import MemoryVersionStore


async def execute_remember_memory(
    arguments: dict[str, Any],
    *,
    action_id: str,
    context: ExecutionContext,
    user_input: UserInput | None,
) -> dict[str, Any]:
    request = RememberMemoryRequest.model_validate(arguments)
    source_text = _source_text(context=context, user_input=user_input)
    canonical = MemoryCanonicalizer().canonicalize(
        request.assertions,
        source_text=source_text,
    )
    if canonical.status != "ready":
        return canonical.model_dump(mode="json")
    source_event_id, database = await _source_event_id(context)
    if source_event_id is None:
        return _missing_source_result()
    async with database.session() as session:
        receipt = await MemoryVersionStore(session).commit(
            MemoryVersionCommitCommand(
                facts=canonical.facts,
                source_event_id=source_event_id,
                receipt_id=_receipt_id(context, action_id),
            ),
            user_id=context.user_id,
            thread_id=context.thread_id,
        )
    return receipt.model_dump(mode="json")


async def execute_search_memory(
    arguments: dict[str, Any],
    *,
    context: ExecutionContext,
) -> dict[str, Any]:
    request = SearchMemoryRequest.model_validate(arguments)
    database = get_database()
    async with database.session() as session:
        store = MemoryVersionStore(session)
        records = (
            await store.list_current(
                user_id=context.user_id,
                limit=200,
            )
            if request.scope == "current"
            else await store.list_history(
                user_id=context.user_id,
                limit=500,
            )
        )
    return VersionedMemorySearch().search(
        records,
        request,
    ).model_dump(mode="json")


async def execute_forget_memory(
    arguments: dict[str, Any],
    *,
    action_id: str,
    context: ExecutionContext,
    user_input: UserInput | None,
) -> dict[str, Any]:
    request = ForgetMemoryRequest.model_validate(arguments)
    source_text = _source_text(context=context, user_input=user_input)
    resolution = MemoryCanonicalizer().resolve_targets(
        request.targets,
        source_text=source_text,
    )
    if resolution.status != "ready":
        return resolution.model_dump(mode="json")
    source_event_id, database = await _source_event_id(context)
    if source_event_id is None:
        return _missing_source_result()
    async with database.session() as session:
        receipt = await MemoryVersionStore(session).forget(
            MemoryVersionForgetCommand(
                memory_keys=[
                    item.memory_key for item in resolution.targets
                ],
                source_event_id=source_event_id,
                receipt_id=_receipt_id(context, action_id),
                evidence_quote=source_text,
            ),
            user_id=context.user_id,
            thread_id=context.thread_id,
        )
    return receipt.model_dump(mode="json")


async def _source_event_id(
    context: ExecutionContext,
) -> tuple[UUID | None, Any]:
    database = get_database()
    if context.thread_id is None:
        return None, database
    async with database.session() as session:
        source_event = await ConversationEventRepository().get_request_event(
            session,
            user_id=context.user_id,
            thread_id=context.thread_id,
            request_id=context.request_id,
            role="user",
        )
    return (
        source_event.id if source_event is not None else None,
        database,
    )


def _source_text(
    *,
    context: ExecutionContext,
    user_input: UserInput | None,
) -> str:
    return (
        user_input.content
        if user_input is not None
        else str(context.metadata.get("user_message") or "")
    )


def _receipt_id(context: ExecutionContext, action_id: str) -> str:
    return "memory-" + hashlib.sha256(
        f"{context.request_id}:{action_id}".encode("utf-8")
    ).hexdigest()[:40]


def _missing_source_result() -> dict[str, Any]:
    return {
        "result_mode": "memory_mutation_receipt",
        "status": "failed",
        "error": "source user event is not committed",
    }
