"""
Verify Phase O2 durable app-provider configuration.

This check uses local PostgreSQL and no external network. It verifies:
- app_provider_configs persists app-provider config separately from LLM providers
- API/service responses never echo submitted API keys
- encrypted API keys are stored encrypted and resolved through credentials_ref
- runtime provider loading reads DB-backed mem0/gbrain config
- provider health refresh updates structured telemetry without writing memory/evidence

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_provider_config_db_flow.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.crud import app_provider_config as app_provider_config_crud
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.memory import MemoryCandidate, get_memory_orchestrator
from app.services.provider_config import (
    AppProviderConfigUpdate,
    check_provider_health_in_db,
    ensure_default_provider_configs_in_db,
    get_provider_config_from_db,
    list_provider_configs_from_db,
    resolve_provider_api_key,
    update_provider_config_in_db,
)
from app.services.research.observation_providers import (
    ObservationProviderRequest,
    get_default_observation_provider_from_db,
)
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _snapshot_provider(provider_key: str) -> dict[str, Any]:
    db = get_database()
    async with db.session() as session:
        await ensure_default_provider_configs_in_db(session)
        record = await app_provider_config_crud.get_app_provider_config(
            session,
            provider_key,
        )
        _assert(record is not None, f"{provider_key} config should exist")
        assert record is not None
        return {
            "provider_type": record.provider_type,
            "scope": record.scope,
            "enabled": record.enabled,
            "display_name": record.display_name,
            "capabilities": deepcopy(record.capabilities),
            "settings": deepcopy(record.settings),
            "credentials_ref": record.credentials_ref,
            "encrypted_api_key": record.encrypted_api_key,
            "health_status": record.health_status,
            "health_error_type": record.health_error_type,
            "health_error": record.health_error,
            "health_duration_ms": record.health_duration_ms,
            "health_checked_at": record.health_checked_at,
            "metadata_json": deepcopy(record.metadata_json),
        }


async def _restore_provider(provider_key: str, snapshot: dict[str, Any]) -> None:
    db = get_database()
    async with db.session() as session:
        await app_provider_config_crud.update_app_provider_config(
            session,
            provider_key,
            snapshot,
        )


async def _insert_temp_user_and_thread(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO public.users (id, display_name, is_mock_user)
                VALUES (:user_id, :display_name, true)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"user_id": user_id, "display_name": "Provider Config DB Verify"},
        )
        await session.execute(
            text(
                """
                INSERT INTO public.conversations (thread_id, user_id, title)
                VALUES (:thread_id, :user_id, :title)
                ON CONFLICT (thread_id) DO NOTHING
                """
            ),
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "title": "Provider Config DB Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _memory_event_count(user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.memory_events WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _run_db_provider_config_flow() -> None:
    mem0_snapshot = await _snapshot_provider("mem0")
    gbrain_snapshot = await _snapshot_provider("gbrain")
    tavily_snapshot = await _snapshot_provider("tavily")
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        db = get_database()
        async with db.session() as session:
            listed = await list_provider_configs_from_db(session)
            keys = {provider.provider_key for provider in listed.providers}
            _assert(
                {"mem0", "gbrain", "tavily"}.issubset(keys),
                "default app providers required",
            )

            mem0 = await update_provider_config_in_db(
                session,
                "mem0",
                AppProviderConfigUpdate(
                    enabled=True,
                    api_key="phase-o2-secret",
                    settings={
                        "live_response": {
                            "results": [
                                {
                                    "memory": "quiet family saga",
                                    "categories": ["style"],
                                    "score": 0.91,
                                }
                            ]
                        }
                    },
                ),
            )
            _assert(mem0 is not None, "mem0 update should succeed")
            assert mem0 is not None
            serialized = json.dumps(mem0.model_dump(mode="json"), ensure_ascii=False)
            _assert("phase-o2-secret" not in serialized, "API key must not be echoed")
            _assert(mem0.credentials_ref == "db:global:mem0", "DB credential ref required")
            _assert(mem0.credential_status == "configured", "DB credential should be configured")
            _assert(
                resolve_provider_api_key(mem0) == "phase-o2-secret",
                "DB credential should resolve inside process",
            )

            record = await app_provider_config_crud.get_app_provider_config(session, "mem0")
            _assert(record is not None, "mem0 record should exist")
            assert record is not None
            _assert(record.encrypted_api_key, "encrypted key should be stored")
            _assert(
                record.encrypted_api_key != "phase-o2-secret",
                "stored key must be encrypted",
            )

            health = await check_provider_health_in_db(session, "mem0")
            _assert(health is not None, "health should return config")
            assert health is not None
            _assert(health.health.status == "ok", "configured enabled mem0 health should be ok")

            tavily = await update_provider_config_in_db(
                session,
                "tavily",
                AppProviderConfigUpdate(
                    enabled=True,
                    api_key="tvly-phase-o2-secret",
                    settings={
                        "max_results": 4,
                        "search_depth": "basic",
                        "include_answer": True,
                        "include_raw_content": False,
                        "force_health_status": "ok",
                    },
                ),
            )
            _assert(tavily is not None, "tavily update should succeed")
            assert tavily is not None
            serialized_tavily = json.dumps(
                tavily.model_dump(mode="json"),
                ensure_ascii=False,
            )
            _assert(
                "tvly-phase-o2-secret" not in serialized_tavily,
                "Tavily API key must not be echoed",
            )
            _assert(
                tavily.credentials_ref == "db:global:tavily",
                "Tavily DB credential ref required",
            )
            _assert(
                tavily.credential_status == "configured",
                "Tavily DB credential should be configured",
            )
            _assert(
                resolve_provider_api_key(tavily) == "tvly-phase-o2-secret",
                "Tavily DB credential should resolve inside process",
            )
            tavily_record = await app_provider_config_crud.get_app_provider_config(
                session,
                "tavily",
            )
            _assert(tavily_record is not None, "tavily record should exist")
            assert tavily_record is not None
            _assert(tavily_record.encrypted_api_key, "Tavily encrypted key required")
            _assert(
                tavily_record.encrypted_api_key != "tvly-phase-o2-secret",
                "stored Tavily key must be encrypted",
            )
            tavily_health = await check_provider_health_in_db(session, "tavily")
            _assert(tavily_health is not None, "Tavily health should return config")
            assert tavily_health is not None
            _assert(
                tavily_health.health.status == "ok",
                "configured enabled Tavily health should be ok",
            )

            gbrain = await update_provider_config_in_db(
                session,
                "gbrain",
                AppProviderConfigUpdate(
                    enabled=True,
                    api_key="phase-o2-gbrain-secret",
                    settings={
                        "live_response": {
                            "results": [
                                {
                                    "answer": "A source-backed gbrain observation.",
                                    "title": "Phase O2 source",
                                    "url": "https://example.test/phase-o2",
                                    "score": 0.75,
                                }
                            ]
                        }
                    },
                ),
            )
            _assert(gbrain is not None, "gbrain update should succeed")
            missing = await update_provider_config_in_db(
                session,
                "gbrain",
                AppProviderConfigUpdate(
                    clear_credentials=True,
                    enabled=True,
                    settings={},
                ),
            )
            _assert(missing is not None, "gbrain clear credentials should succeed")
            missing_health = await check_provider_health_in_db(session, "gbrain")
            _assert(missing_health is not None, "gbrain health should return config")
            assert missing_health is not None
            _assert(
                missing_health.health.status == "missing_credentials",
                "enabled provider without credentials should report missing credentials",
            )

            await update_provider_config_in_db(
                session,
                "gbrain",
                AppProviderConfigUpdate(
                    enabled=True,
                    api_key="phase-o2-gbrain-secret",
                    settings={
                        "live_response": {
                            "results": [
                                {
                                    "answer": "A source-backed gbrain observation.",
                                    "title": "Phase O2 source",
                                    "url": "https://example.test/phase-o2",
                                    "score": 0.75,
                                }
                            ]
                        }
                    },
                ),
            )

        memory = get_memory_orchestrator()
        saved = await memory.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="quiet family saga",
                polarity="like",
                source_text="I like quiet family saga.",
                source_kind="user_message",
            )
        )
        _assert(saved.memory is not None, "setup memory should be saved")
        before_count = await _memory_event_count(user_id)
        result = await memory.search_memory(
            user_id=user_id,
            thread_id=thread_id,
            query="quiet family",
            memory_types=["preference"],
            limit=10,
        )
        _assert("mem0" in result.provider_sources, "DB-enabled mem0 should run")
        _assert(
            await _memory_event_count(user_id) == before_count,
            "mem0 recall must not write memory events",
        )

        provider = await get_default_observation_provider_from_db()
        observation_result = await provider.observe(
            ObservationProviderRequest(
                run_id=uuid.uuid4(),
                query="phase o2 gbrain observation",
            )
        )
        _assert(
            observation_result.provider_name == "gbrain",
            "DB-enabled gbrain should be selected",
        )
        _assert(
            observation_result.observations[0].metadata["provider_source"] == "gbrain",
            "gbrain observation should preserve provider source",
        )
        _assert(
            await _memory_event_count(user_id) == before_count,
            "gbrain observation must not write memory events",
        )

        db = get_database()
        async with db.session() as session:
            fetched = await get_provider_config_from_db(session, "mem0")
            _assert(fetched is not None, "mem0 fetch should work")
            assert fetched is not None
            _assert(
                "phase-o2-secret"
                not in json.dumps(fetched.model_dump(mode="json"), ensure_ascii=False),
                "fetched config must not echo secrets",
            )

        print("provider config DB verification passed")
        print(f"user_id={user_id}")
        print(f"thread_id={thread_id}")
    finally:
        await _restore_provider("mem0", mem0_snapshot)
        await _restore_provider("gbrain", gbrain_snapshot)
        await _restore_provider("tavily", tavily_snapshot)
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_db_provider_config_flow()
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help="Skip SQL migration and only run behavior checks.",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
