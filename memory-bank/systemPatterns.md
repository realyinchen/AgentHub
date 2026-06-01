# System Patterns

## 4-Layer Architecture
```
app/
├── infra/              # Layer 1: Infrastructure (config, database, llm, cache, tools)
├── middleware/         # Layer 2: Dynamic Middleware (prompt, memory, model)
├── agents/             # Layer 3: Agent Logic (create_agent + middleware chain)
└── api/                # Layer 4: HTTP Interface (FastAPI routes)
```

- **Infra Layer**: `app/infra/` contains all low-level infrastructure (config, database, llm, cache, tools)
- **Middleware Layer**: `app/middleware/` contains all dynamic injectors (prompt, memory, model)
- **Agent Layer**: `app/agents/` uses `create_agent()` + middleware chain pattern
- **app/support DELETED**: Entire directory removed; functionality migrated to middleware and infra/tools

## Factory Pattern (Simplified)
- `app/infra/database/factory.py` provides singleton instances: `get_database()`, `get_vectorstore()`, `get_checkpointer()`, `get_store()`
- Single `init_all()` function for all database components (called during FastAPI startup)
- Single `dispose_all()` function for cleanup (called during FastAPI shutdown)
- No Protocol-based interfaces — direct concrete implementations for PostgreSQL only
- `app/infra/llm/model_manager.py`: ModelProvider singleton
- `app/infra/cache/manager.py`: CacheManager singleton
- `app/middleware/prompt/service.py`: PromptService singleton

## Database Layer (Simplified)
```
app/infra/database/
├── __init__.py          # Public API exports
├── base.py              # SQLAlchemy DeclarativeBase
├── database.py          # PostgreSQL engine/session management
├── vectorstore.py       # PGVector vector storage
├── checkpointer.py      # LangGraph checkpointing (short-term memory)
├── store.py             # LangGraph Store (long-term memory)
└── factory.py           # Singleton factory functions
```

**Key simplifications:**
- Removed `postgres/` subdirectory (flat structure)
- Removed `protocols.py` (no unnecessary abstraction)
- Removed per-component init functions (use `init_all()` only)
- Removed async locks (FastAPI lifespan guarantees single-call initialization)

## Key Technical Decisions (Phase 2 Additions)

### `create_agent` API (LangChain v1)
**Standard pattern for all agents**:
```python
agent = create_agent(
    model=model_instance,            # Must be instantiated ChatLiteLLM, NOT string
    tools=tools_list,               # List of LangChain tools
    middleware=[mw1, mw2],          # Middleware chain, executed in order
    context_schema=ContextType,     # TypedDict for context validation
    store=store_instance,           # Optional: for long-term memory
)
```

**Why NOT use LangGraph v0 `build_standard_agent_graph` anymore?**
- `create_agent` is LangChain v1 official API
- Built-in middleware system for dynamic injection
- Native Store integration for long-term memory
- Better compatibility with future LangChain releases

### Middleware Chain Pattern
```
[Before Model Call]
    chatbot_dynamic_prompt(@dynamic_prompt)
        ↓ Builds system prompt from MD file + time context + user memory
    dynamic_model(@wrap_model_call)
        ↓ Overrides model_name, thinking_mode from context
        ↓ Executes actual model call
```

**Middleware Types**:
1. `@dynamic_prompt`: Generates system prompt before each model call
2. `@wrap_model_call`: Wraps model call for dynamic parameter injection
3. `@wrap_tool_call`: Wraps tool calls for error handling, logging

### Context Schema Pattern
Each agent defines its own `Context(TypedDict)`:
```python
class ChatbotContext(TypedDict, total=False):
    user_id: str           # For long-term memory lookup
    model_name: str        # Override default model
    thinking_mode: bool    # Enable thinking mode for DeepSeek/Qwen
```

**Context flow through the system**:
```
UserInput.user_id
    ↓
handle_input() → context dict
    ↓
agent.astream_events(..., context=context)
    ↓
request.runtime.context  ← accessed by middleware
```

### Prompt: External-Only Principle
- **NO hardcoded templates anywhere in Python code**
- All prompts live in external files: `data/prompts/<agent_id>.md`
- PromptService reads from MD files, no builtin fallback dictionary
- `@dynamic_prompt` middleware injects at runtime (not compile time)

### Model: Dynamic Override Pattern
- Default model from `ModelManager.get_default_llm_id()`
- Per-request override via `context.model_name` (read by `dynamic_model` middleware)
- Thinking mode also controlled via `context.thinking_mode`
- Same agent can use different models for different requests

### Tool: Lazy Initialization Pattern
```python
def _get_tools():
    try:
        web_search = create_web_search()
        return [get_current_time, web_search]
    except Exception:
        # Fallback: no web search if API key missing
        return [get_current_time]
```

- Tools initialized lazily (not at import time)
- Graceful degradation if optional dependencies missing
- All tools now in `app/infra/tools/`

## Key Technical Decisions (Existing)
- **Config singleton pattern**: `@lru_cache def get_settings()` (FastAPI recommended), replacing module-level settings
- Factory functions cache singleton instances (one per process)
- Session auto-commits on success (safety net for CRUD operations)
- AsyncQdrantClient used for vector search (avoids blocking event loop)
- Lazy class imports via `_import_class()` in factory (avoids circular dependencies)
- Backend type determined by `settings.DATABASE_TYPE` and `settings.VECTORSTORE_TYPE`
- Default config: `sqlite`/`sqlite_vec` (zero external dependency for local development)
- Config validation flow: `.env` load → model validator → computed field (MODE drives DB/VectorStore type)

## Production Standards (PostgreSQL + Qdrant)
### 单例使用规范
- **PostgreSQL Engine**: 必须单例（全局连接池复用）
- **PostgreSQL Session**: 禁止单例（请求级隔离，有事务状态，非线程安全）
- **Qdrant Client**: 推荐单例（无事务、线程安全、连接复用）

### 事务 Commit 规范
- **全局强制**：所有业务代码（API、Services、CRUD）禁止自行 commit/rollback
- **统一处理**：由 `db.session()` 上下文管理器统一 commit/rollback/close
- **唯一例外**：仅离线脚本允许自行 commit

### 实现模式
```python
# db.session() 标准模式（显式事务）
async with db.session() as session:
    # 业务逻辑：add/update/delete
    await crud.do_something(session, ...)
    # 必须显式提交
    await session.commit()
# 上下文退出自动 rollback（未提交的更改）和 close

# db.session_readonly() 只读模式
async with db.session_readonly() as session:
    # 仅查询，无需 commit
    result = await crud.query(session, ...)
# 上下文退出自动 rollback 和 close
```

## Component Relationships (Updated)
```
main.py (lifespan)
  └─ init_all() → init_database() + init_vectorstore() + init_checkpointer() + init_store()
  └─ dispose_all()

API routes
  └─ ChatHandler.handle_input()
       └─ UserInput validation (user_id, model_name, thinking_mode)
       └─ AgentRegistry.get("chatbot") → create_agent instance
       └─ agent.astream_events(..., context=context)
            └─ [middleware chain]
                 └─ chatbot_dynamic_prompt: builds system prompt
                 └─ dynamic_model: overrides model params
            └─ Tool execution: get_current_time, web_search
            └─ Streaming events to SSE response

Middleware
  └─ PromptService: reads MD files, injects time context
  └─ MemoryManager: interfaces with Store for long-term memory
  └─ dynamic_model: reads context, overrides model params
```

## Critical Implementation Paths (Updated)
- **Chat flow**: API → UserInput validation → context dict → agent.astream_events → middleware chain → SSE stream
- **Prompt injection**: `@dynamic_prompt` middleware → PromptService.build_system_prompt → MD file + time context + memory
- **Model override**: `@wrap_model_call` middleware → reads context.model_name → overrides model params
- **Long-term memory**: Store instance passed to create_agent → accessible via `request.runtime.store`

## Design Patterns in Use
- **Singleton**: Factory caches instances in module-level variables
- **Context Manager**: `session()` yields session with auto-commit/rollback
- **Middleware Chain**: Sequential dynamic injection before model calls
- **Lazy Initialization**: Tools initialized on first use with graceful fallback

## Database Abstraction Documentation
- Full database abstraction architecture documentation is in `README.md` (English) and `README.zh.md` (Chinese)
- PostgreSQL-only implementation (no multi-backend abstraction)

## PostgreSQL Production Standards

### Connection Pool Configuration
```python
# backend/app/infra/config.py
POSTGRES_MIN_CONNECTIONS_PER_POOL=2      # Min pool size
POSTGRES_MAX_CONNECTIONS_PER_POOL=10     # Max pool size
```

### Session Semantics
```python
@asynccontextmanager
async def session(self) -> AsyncGenerator[AsyncSession, None]:
    """Read-write session: auto-commit on exit, auto-rollback on exception"""
    session = self._session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
```

### LangChain/LangGraph Integration
- Uses official `AsyncPostgresSaver.from_conn_string()` for checkpointing
- Uses official `AsyncPostgresStore.from_conn_string()` for long-term memory
- Uses official `PGEngine` + `PGVectorStore` for vector storage
- Embedding function injected via `LiteLLMEmbeddingsAdapter` (LangChain `Embeddings` interface)
