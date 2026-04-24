# Active Context

## Current Work Focus
Phase 2 code review and fix implementation for the database/vectorstore migration.

## Recent Changes (2026-04-24)
Code review identified and fixed the following issues across the migration codebase:

### P0 Fixes (Critical)
- **factory.py**: Fixed `get_database()`/`get_vectorstore()`/`get_checkpointer()` to cache singleton instances (was creating new instances on every call). Split `_BACKENDS` dict into `_DB_BACKENDS`/`_VS_BACKENDS`/`_CP_BACKENDS`. Changed to lazy import via `_import_class()` instead of string paths.
- **dependencies.py**: Fixed `get_db()` to use factory's `get_database()` instead of creating new `PostgresDatabase()` instances (connection pool leak).
- **postgres/db.py**: Restored auto-commit in `session()` — `await session.commit()` on successful exit, matching old `AsyncDatabaseManager` behavior. Provides safety net for CRUD operations.

### P1 Fixes (Important)
- **interfaces.py**: Changed `VectorstoreInterface.initialize()` and `dispose()` to `async def`. Added `dispose()` to `CheckpointInterface`.
- **postgres/vectorstore.py**: Changed from sync `QdrantClient` to `AsyncQdrantClient` to avoid blocking the FastAPI event loop. Added `_ensure_collection()` for lazy collection creation.

### P2 Fixes (Medium)
- **config.py**: Fixed default values from `sqlite`/`sqlite_vec` to `postgres`/`qdrant` to match existing deployments.
- **postgres/checkpointer.py**: Added `dispose()` method. Simplified `get_saver()` — removed pseudo-context-manager pattern.
- **__init__.py**: Updated exports to match factory.py: `init_all`, `dispose_all`, `get_vectorstore`, `get_checkpointer`, `get_saver`.
- **main.py**: Changed to use `init_all()` and `dispose_all()` instead of manual per-component initialization/cleanup. Removed `async with checkpointer.get_saver()` pattern.

### P3 Fixes (Low)
- **base.py**: Simplified to re-export from `interfaces.py` (removed duplicate interface definitions).
- **test_phase1.py**: Updated to test singleton behavior and lifecycle.
- **vectorstore_retriever.py**: Cleaned up to use `get_vectorstore()` factory function.

## Next Steps
- Phase 3: Implement SQLite backend (db.py, checkpointer.py)
- Phase 4: Implement sqlite-vec vectorstore backend
- Phase 5: Smart database initialization
- Phase 6: Configuration and documentation

## Active Decisions
- Auto-commit in session() is the default behavior (matches old codebase)
- Factory functions return singleton instances (cached per process)
- VectorstoreInterface uses async initialize/dispose (required for AsyncQdrantClient)
- Qdrant uses AsyncQdrantClient instead of sync client (avoids event loop blocking)
- main.py uses `init_all()`/`dispose_all()` for clean lifecycle management