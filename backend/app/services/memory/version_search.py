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


class VersionedMemorySearch:
    """Filter and rank current canonical facts; it never reads old versions."""

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
                return MemorySearchReceipt(status="empty")
            schema_key = schema.schema_key

        query = request.query.casefold()
        ranked: list[tuple[int, int, MemoryVersionRecord]] = []
        for index, record in enumerate(records):
            if schema_key and record.schema_key != schema_key:
                continue
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
        memories = [item[2] for item in ranked]
        return MemorySearchReceipt(
            status="completed" if memories else "empty",
            memories=memories,
        )
