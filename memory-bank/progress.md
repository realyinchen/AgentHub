# Progress

## What Works
- Phase 1: Architecture foundation (interfaces, factory, config) ✅
- Phase 2: PostgreSQL migration (all business code uses factory) ✅
- Code review fixes: singleton caching, connection pool leak, auto-commit, AsyncQdrantClient ✅

## What's Left to Build
- Phase 3: SQLite backend (db.py, checkpointer.py)
- Phase 4: sqlite-vec vectorstore backend
- Phase 5: Smart database initialization
- Phase 6: Configuration and documentation

## Current Status
Phase 2 complete with code review fixes applied. All Python imports verified. Ready for Phase 3.

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