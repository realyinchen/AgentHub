"""Read-only database verification for the applied R7 migration."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)


async def _run() -> None:
    await init_database_connection()
    try:
        database = get_database()
        async with database.session() as session:
            columns_result = await session.execute(
                text(
                    """
                    SELECT table_name, column_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name IN (
                          'embedding_calibration_reports',
                          'embedding_space_activations'
                      )
                    """
                )
            )
            columns = {
                (row["table_name"], row["column_name"]): row["is_nullable"]
                for row in columns_result.mappings().all()
            }
            required_not_null = {
                ("embedding_calibration_reports", "space_id"),
                ("embedding_calibration_reports", "dataset_sha256"),
                ("embedding_calibration_reports", "source_watermark"),
                ("embedding_calibration_reports", "validation_checks"),
                ("embedding_space_activations", "to_space_id"),
                ("embedding_space_activations", "calibration_report_id"),
                ("embedding_space_activations", "idempotency_key"),
            }
            assert all(columns.get(item) == "NO" for item in required_not_null)

            indexes_result = await session.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'embedding_calibration_reports'
                    """
                )
            )
            indexes = set(indexes_result.scalars().all())
            assert "uq_embedding_calibration_space_dataset" in indexes

            triggers_result = await session.execute(
                text(
                    """
                    SELECT trigger_name
                    FROM information_schema.triggers
                    WHERE event_object_schema = 'public'
                      AND event_object_table IN (
                          'embedding_calibration_reports',
                          'embedding_space_activations'
                      )
                    """
                )
            )
            triggers = set(triggers_result.scalars().all())
            assert "trg_embedding_calibration_append_only" in triggers
            assert "trg_embedding_activation_append_only" in triggers

            foreign_keys_result = await session.execute(
                text(
                    """
                    SELECT COUNT(1)
                    FROM pg_constraint
                    WHERE contype = 'f'
                      AND conrelid IN (
                          'public.embedding_calibration_reports'::regclass,
                          'public.embedding_space_activations'::regclass
                      )
                      AND confdeltype = 'r'
                    """
                )
            )
            restrict_foreign_keys = int(foreign_keys_result.scalar_one())
            assert restrict_foreign_keys == 4

            counts_result = await session.execute(
                text(
                    """
                    SELECT
                        (SELECT COUNT(1)
                         FROM public.embedding_calibration_reports)
                            AS calibration_reports,
                        (SELECT COUNT(1)
                         FROM public.embedding_space_activations)
                            AS activation_receipts,
                        (SELECT COUNT(1)
                         FROM public.embedding_space_bindings)
                            AS active_bindings
                    """
                )
            )
            counts = dict(counts_result.mappings().one())
        print(
            json.dumps(
                {
                    "status": "passed",
                    "migration": "change_026_embedding_generation_gates.sql",
                    "restrict_foreign_keys": restrict_foreign_keys,
                    "append_only_triggers": sorted(triggers),
                    "counts": counts,
                    "mutations_performed": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        await dispose_database()


if __name__ == "__main__":
    asyncio.run(_run())
