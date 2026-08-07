from __future__ import annotations

import json

from app.services.memory.version_contracts import (
    MemorySearchReceipt,
    MemoryVersionRecord,
    SearchMemoryRequest,
)
from app.services.memory.versioned_schema_registry import (
    VersionedMemorySchemaRegistry,
)


MAX_HISTORY_RECORDS = 40


class VersionedMemorySearch:
    """Filter, scope and rank canonical facts across their version chains."""

    def __init__(
        self,
        registry: VersionedMemorySchemaRegistry | None = None,
    ) -> None:
        self._registry = registry or VersionedMemorySchemaRegistry()

    def search(
        self,
        records: list[MemoryVersionRecord],
        request: SearchMemoryRequest,
    ) -> MemorySearchReceipt:
        schema_key = ""
        if request.predicate:
            schema = self._registry.resolve_predicate(request.predicate)
            if schema is None:
                return MemorySearchReceipt(
                    status="empty",
                    scope=request.scope,
                )
            schema_key = schema.schema_key

        scoped = records
        if schema_key:
            scoped = [
                record for record in scoped if record.schema_key == schema_key
            ]
        scoped = self._select_scope(scoped, request)

        query = request.query.casefold()
        ranked: list[tuple[int, int, MemoryVersionRecord]] = []
        for index, record in enumerate(scoped):
            searchable = " ".join(
                [
                    record.schema_key,
                    record.evidence_quote,
                    json.dumps(record.value, ensure_ascii=False),
                    json.dumps(record.qualifiers, ensure_ascii=False),
                ]
            ).casefold()
            if query and query not in searchable:
                continue
            score = 2 if query and query in record.evidence_quote.casefold() else 1
            ranked.append((score, -index, record))
        ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
        truncated = len(ranked) > MAX_HISTORY_RECORDS
        memories = [item[2] for item in ranked[:MAX_HISTORY_RECORDS]]
        return MemorySearchReceipt(
            status="completed" if memories else "empty",
            scope=request.scope,
            memories=memories,
            truncated=truncated,
        )

    def _select_scope(
        self,
        records: list[MemoryVersionRecord],
        request: SearchMemoryRequest,
    ) -> list[MemoryVersionRecord]:
        if request.scope == "current":
            return [
                record
                for record in records
                if record.superseded_by is None and not record.is_tombstone
            ]

        chains: dict[str, list[MemoryVersionRecord]] = {}
        for record in records:
            if not record.memory_key:
                continue
            chains.setdefault(record.memory_key, []).append(record)
        ordered = {
            key: sorted(items, key=lambda item: item.version_no)
            for key, items in chains.items()
        }

        if request.scope == "earliest":
            return [
                items[0]
                for items in ordered.values()
                if items and items[0].previous_version_id is None
            ]
        if request.scope == "previous":
            selected: list[MemoryVersionRecord] = []
            for items in ordered.values():
                if len(items) < 2:
                    continue
                depth = max(1, min(int(request.depth), len(items) - 1))
                selected.extend(reversed(items[-1 - depth : -1]))
            return selected

        selected = []
        for items in ordered.values():
            for record in items:
                if _overlaps_window(
                    record,
                    since=request.since,
                    until=request.until,
                ):
                    selected.append(record)
        return selected


def _overlaps_window(
    record: MemoryVersionRecord,
    *,
    since,
    until,
) -> bool:
    if since is not None and record.valid_to is not None:
        if record.valid_to < since:
            return False
    if until is not None and record.valid_from is not None:
        if record.valid_from > until:
            return False
    return True
