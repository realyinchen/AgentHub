# Active Context

## Current Focus

**PR-A Complete** (May 22, 2026)

Working through the 20-item TODO from the architecture review (`backend/TODO.md`). PR-A (zero-risk safety deletions) is complete. Next: PR-B (delete `CheckpointTraceReader` facade + fix `stream.py` private attribute access).

### P3 Changes Summary

**Model Architecture Reorganization** (May 20, 2026)

1. **`model_manager.py` — removed per-request LLM caching**
   - Deleted `_llm_cache` (was caching `ChatLiteLLMRouter` instances per model+thinking_mode)
   - Deleted `get_llm()` (was constructing cached Router instances)
   - Deleted `get_random_active_model()` (unused except in `stream.py`)
   - Deleted `get_embedding_model_instance()` (was unused)
   - Added `get_router_sync()` — synchronous Router accessor for use inside `@wrap_model_call` middleware (avoids async refresh)
   - `refresh()` now pre-builds the Router at end, so `get_router_sync()` works immediately after startup
   - **Why**: Per-request LLM caching was redundant — the Router instance is already cached. Each runtime model switch (via `dynamic_model` middleware) needs a fresh `ChatLiteLLMRouter` bound with the correct `extra_body`, but the underlying Router backing it is shared. This is the correct pattern: one Router instance, many lightweight bound instances.

2. **`factory.py` — added `get_llm()` unified entry point**
   - New `get_llm(model_id, thinking_mode, temperature)` builds a `ChatLiteLLMRouter` bound to the pre-built Router
   - This is the recommended entry point for runtime model switching (used by `dynamic_model` middleware)
   - `get_chat_litellm()` kept for special cases requiring direct model access (e.g., agent-creation time default model without Router)
   - Exported in `__init__.py` as `from app.infra.llm import get_llm`

3. **Deleted `middleware/fallback.py`**
   - Custom fallback middleware (`@wrap_model_call` + manual fallback selection)` was removed
   - Model fallback is now handled entirely by the LiteLLM Router's built-in `fallbacks` + `num_retries` (configured in `ModelManager._build_fallbacks()`)
   - The Router automatically falls back to same-type models on rate-limit/quota/403/429 errors
   - **Why**: Custom fallback middleware was duplicating functionality already built into the LiteLLM Router. The Router approach is more reliable (handles transient errors, connection issues, timeouts) and simpler (no custom deactivation logic, no async background tasks).

4. **Updated `dynamic_model` middleware** (`middleware/model/dynamic.py`)
   - Now uses `get_llm()` (via Router) instead of `get_chat_litellm()` (direct)
   - Gets built-in fallback + retry from the Router automatically
   - Removed dependency on `fallback_model` middleware

5. **Updated `chatbot.py` agent**
   - Removed `fallback_model` from middleware chain
   - Router handles fallback transparently

6. **Updated `stream.py`**
   - Replaced `get_random_active_model()` with `ModelManager.get_default_llm_id()` + fallback iteration
   - Removed unused `get_model_manager` import

7. **Updated `provider.py` API**
   - Added `ModelManager.refresh()` call after provider update (API key / base_url changes invalidate the cache)

8. **Dead code cleanup**
   - Removed `_record_fallback_event()`, `_deactivate_model()`, `_get_fallback_model_id()`, `_is_fallback_error()` (were in deleted `fallback.py`)
   - Removed `_llm_cache` attribute from `ModelManager`

### P2 Changes Summary (previous)

1. **`infra/database/` 4-layer abstraction → 3 flat files**
   - Deleted `interfaces.py` (ABC layer: `DatabaseInterface`, `VectorstoreInterface`, `CheckpointInterface`, `StoreInterface`) — over-abstracted for only 2 backends
   - Deleted entire `backends/` directory (8 files: `postgres/{db,vectorstore,checkpointer,store}.py` + `sqlite/{db,vectorstore,checkpointer,store}.py`)
   - Created `_postgres.py` (~410 lines): merged all 4 PostgreSQL backends
   - Created `_sqlite.py` (~400 lines): merged all 4 SQLite backends
   - Rewrote `factory.py`: `threading.Lock` → `asyncio.Lock`, strict `init_xxx() / get_xxx()` separation (lifespan-init / handler-get)
   - `__init__.py` public API unchanged — 31 upstream imports work without modification
   - `base.py` keeps only `Base(DeclarativeBase)` for ORM models
   - **Behavior change**: `get_xxx()` now raises `RuntimeError` if `init_xxx()` wasn't called (was: lazy first-call init). Acceptable because `main.py` lifespan always inits, and no scripts use these directly (verified via search_files)

2. **`infra/llm/` package + `core/model_manager.py` → single `__init__.py`**
   - Deleted `infra/llm/{router,model_manager,streaming,utils}.py` (4 files)
   - **Major finding**: `streaming.py` (497 lines) was entirely dead code after P1's migration to `astream_events(v3)` — no external imports
   - Deleted `core/model_manager.py` (deprecation shim with no active callers)
   - Merged everything into `infra/llm/__init__.py` (~370 lines): `build_extra_body`, `ModelManager` (with `LLMRouter` as internal methods), `get_chat_litellm`, `is_thinking_mode_available`
   - Also deleted other dead code: `bind_tools_with_extra_body`, `async_to_sync` decorator, sync wrappers `embedding_model()` / `get_llm()`

3. **Step 10 (merge `LLMConfig` into `Settings`) — SKIPPED**
   - Project-wide search confirmed **no `LLMConfig` class exists** anywhere
   - `docs.md` reference was based on stale project state
   - `Settings` in `infra/config.py` already centralizes all config (DB, Qdrant, LangSmith, API keys, encryption key)

4. **Step 11 (`agents/chatbot/` dir → file) — SKIPPED**
   - `app/agents/` is already `__init__.py + base.py + chatbot.py + types.py` — chatbot is already a single file
   - No `chatbot/` subdirectory exists

5. **`POST /models/refresh` removed**
   - All CRUD endpoints (create/update/delete/set-default) already auto-call `await ModelManager.refresh()`
   - Removed redundant `POST /models/refresh` endpoint
   - Removed `RefreshResponse` schema (no other usages)
   - Removed frontend wrapper `refreshModelsCache()` in `frontend/src/lib/api.ts` (was never called)

### P2 Verification

Verified via temp import script: **14/14 core modules import cleanly**:
- `infra.{database,llm}`
- `api.v1.{chat,model,stream,trace,dependencies}`
- `middleware.{fallback,memory.manager,memory.long_term,model.dynamic}`
- `agents.{base,chatbot}`
- `main`

### Key Benefits

- **Database layer**: 4-layer abstraction → 3 files; all `threading.Lock` → `asyncio.Lock`
- **LLM layer**: 5 Python files → 1 `__init__.py`; ~700 lines of dead code deleted
- **API layer**: -1 endpoint, -1 schema, -1 frontend wrapper
- **Public API stability**: `from app.infra.database import ...` and `from app.infra.llm import ...` unchanged — zero breakage for upstream callers
- All API contracts and Agent functionality preserved

### Files Changed in P2

- 🆕 `app/infra/database/_postgres.py` — merged postgres backends
- 🆕 `app/infra/database/_sqlite.py` — merged sqlite backends
- ✏️ `app/infra/database/factory.py` — asyncio.Lock, strict init/get separation
- ✏️ `app/infra/database/__init__.py` — public API export (unchanged)
- ✏️ `app/infra/database/base.py` — slimmed down to just `Base`
- ✏️ `app/api/v1/dependencies.py` — removed `DatabaseInterface` import
- 🗑️ `app/infra/database/interfaces.py` — deleted
- 🗑️ `app/infra/database/backends/` — entire directory deleted (8 files)
- ✏️ `app/infra/llm/__init__.py` — consolidated single-file module
- 🗑️ `app/infra/llm/{router,model_manager,streaming,utils}.py` — deleted
- 🗑️ `app/core/model_manager.py` — deleted (deprecation shim)
- ✏️ `app/api/v1/model.py` — removed `POST /refresh` endpoint
- ✏️ `app/schemas/model.py` — removed `RefreshResponse`
- ✏️ `frontend/src/lib/api.ts` — removed `refreshModelsCache()`

### P1 Recap (May 20, 2026 — earlier today)

P1 ("用官方范式替代自造轮子") replaced custom code with LangChain official patterns:
- `FallbackExecutor` → `@wrap_model_call` middleware (`app/middleware/fallback.py`)
- `astream_events(version="v2")` → `version="v3"` with typed projections
- Middleware chain: `chatbot_dynamic_prompt` → `dynamic_model` → `fallback_model` → `SummarizationMiddleware`
- ChatbotContext dataclass for typed runtime context
- v3 BetaWarning accepted per user decision

### PR-A Changes Summary (May 22, 2026)

1. **Deleted `app/tools/` directory (N1)** — 5 dead .py files + `__pycache__/`
   - `from app.tools` had zero callers in the entire codebase
   - The real tools live in `app/infra/tools/` (used by `chatbot.py`)
   - **Why**: Eliminates 5 misleading files that mirrored the actual `infra/tools/` structure

2. **Fixed double commit in `agent.py` (F-I)** — `await db.commit()` → `await db.flush()`
   - `get_db()` dependency uses `db.session()` which auto-commits on context exit
   - The explicit `db.commit()` was a redundant second commit, violating project rule "business code must not commit/rollback directly"
   - `flush()` still pushes the UPDATE to DB so `refresh()` can read server-side fields
   - **Why**: Aligns with `systemPatterns.md` transaction commit convention; prevents potential transaction-semantic confusion

### Next Steps (from TODO.md)

**PR-B** (low risk, high ROI):
- P3/P19: Delete `CheckpointTraceReader` facade class (6 callers → direct delegation)
- N2: Add `ModelManager.get_first_active_llm_id()` public method, replace `stream.py`'s access to `_models_cache` private attribute

**PR-C** (medium risk, needs regression):
- N3: Unify `chat_title.generate_title` to use `get_system_default_llm()` instead of bypassing the LLM factory

## Recent Decisions (PR-A / P2)

1. **PR-A: Dead tools dir is safe to delete** — `grep "from app.tools"` = 0 real matches; `chatbot.py` uses `app.infra.tools.*` exclusively
2. **PR-A: `flush()` is the correct fix** — SQLAlchemy `flush()` pushes pending SQL to the DB connection (same transaction), making data available for `refresh()`. The actual commit is left to the `session()` context manager per project convention

1. **Strict init/get separation** — `get_database()` now raises if `init_database()` hasn't run. More predictable than lazy init; suitable for high-concurrency prod (no runtime lock overhead). Safe because `main.py` lifespan always calls `init_all()`
2. **Keep package directory `infra/llm/` over flat `infra/llm.py`** — `from app.infra.llm import ...` works the same way; single `__init__.py` is logically the same as a single file, but doesn't require changing package vs. module decision (could collide with cached `__pycache__/llm.cpython-*.pyc`)
3. **Deleted `streaming.py` outright** — 497 lines, zero external imports. Was leftover from before P1's `astream_events(v3)` migration
4. **Skipped Steps 10 & 11** — Both based on stale `docs.md` content; current code already in desired state. Documented as skipped with rationale

## Active Branches

- Main development on `main` branch