"""Verify external research data is safe for Postgres JSONB persistence."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.research.contracts import ResearchStep
from app.services.research.loop import (
    ResearchSearchTask,
    project_research_search_output,
)


def _assert_clean(value: object) -> None:
    if isinstance(value, str):
        assert "\x00" not in value, repr(value)
        value.encode("utf-8", errors="strict")
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            _assert_clean(key)
            _assert_clean(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _assert_clean(nested)


def main() -> None:
    projection = project_research_search_output(
        task=ResearchSearchTask(
            round_index=1,
            objective="animal books",
            query="animal books",
        ),
        provider_output={
            "status": "ok",
            "provider": "test",
            "query": "animal books",
            "result": {
                "results": [
                    {
                        "title": "Animal\x00 books",
                        "url": "https://example.test/books",
                        "content": (
                            "A well reviewed animal book\x00 presents verified "
                            "observations about wildlife.\ud800"
                        ),
                        "score": 0.9,
                    }
                ]
            },
        },
    )
    records = [
        record.model_dump(mode="json")
        for record in projection.source_records
    ]
    assert records, records
    _assert_clean(records)

    step = ResearchStep(
        run_id=uuid4(),
        step_type="search",
        output={"results": records, "nested": {"raw": "bad\x00value\ud800"}},
    )
    _assert_clean(step.output)
    assert step.output["nested"]["raw"] == "bad value?"

    print("research source sanitization verification passed")


if __name__ == "__main__":
    main()
