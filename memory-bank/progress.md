# Progress

## What Works
- Phase 1: Architecture foundation (interfaces, factory, config) ✅
- Phase 2: PostgreSQL migration (all business code uses factory) ✅
- Phase 3: SQLite backend (db.py, checkpointer.py, ORM model refactoring) ✅
- Phase 5: Smart database initialization (dual-backend init_database.py, SQL scripts, ORM fixes) ✅
- Code review fixes: singleton caching, connection pool leak, auto-commit, AsyncQdrantClient ✅

## What's Left to Build
- Phase 4: sqlite-vec vectorstore backend
- Phase 6: Configuration and documentation

## Current Status
Phase 3 and Phase 5 complete. SQLite backend fully implemented. `init_database.py` refactored to support both PostgreSQL and SQLite via SQL scripts in `sql/postgres/` and `sql/sqlite/` subdirectories. ORM model compatibility issues resolved (`server_default=func.now()` → `default=utc_now`, `description` primary_key fix). Ready for Phase 4 (vector store abstraction).

## Known Issues
- `VectorstoreInterface.search()` (text-based) raises `NotImplementedError` — needs embedding model integration
- `vectorstore_search` tool calls `vectorstore.search()` which will fail for Qdrant backend — needs embedding model wiring
- CRUD `message_step.py` uses `flush()` without `commit()` in save functions — relies on session auto-commit (safe with current auto-commit semantics)

## Evolution of Project Decisions
- 2026-04-24: Migrated from direct `db_manager`/`checkpointer`/`qdrant_manager` imports to factory pattern
- 2026-04-24: Code review fixed critical singleton caching, connection pool leak, and async client issues
- 2026-04-24: Restored auto-commit in session() to match old behavior and prevent silent data loss
- 2026-04-24: Changed QdrantClient to AsyncQdrantClient to avoid blocking FastAPI event loop
- 2026-04-24: Simplified main.py to use init_all()/dispose_all() for lifecycle management
- 2026-04-25: Refactored ORM models from PostgreSQL dialect types (UUID, JSONB) to SQLAlchemy universal types (Uuid, JSON) for cross-backend compatibility
- 2026-04-25: Implemented SQLite backend (SQLiteDatabase, SqliteCheckpointer) using aiosqlite + langgraph-checkpoint-sqlite
- 2026-04-25: SQLite uses StaticPool for async compatibility, auto-creates data directory and tables via create_all()
- 2026-04-25: Phase 5 complete — init_database.py supports both backends, SQL scripts reorganized into sql/postgres/ and sql/sqlite/ subdirectories
- 2026-04-25: Fixed Agent model (description erroneously set as primary_key, is_active default), Provider/Model models (server_default=func.now() → default=utc_now for SQLite compat)
