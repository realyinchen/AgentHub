# Active Context

## Current Focus

OpenAI-Compatible LLM provider integration. System now supports any OpenAI Chat Completions API compatible endpoint (vLLM, Ollama, LM Studio, LiteLLM Proxy, etc.) alongside the existing DashScope provider.

## Recent Changes

### 2026-06-15 — Local / Self-Hosted LLM Provider

**New Provider: `local`**
- Added `local` provider to `000_init_database.sql` (idempotent INSERT, `is_openai_compatible=true`)
- `factory.py` added special-casing: when `is_openai_compatible=true`, LiteLLM model name is `openai/{short_model_id}` (protocol prefix hardcoded), otherwise `{provider}/{short_model_id}`
- Provider name `local` is semantically clear (self-hosted/on-premise) and doesn't conflict with future official OpenAI provider
- `base_url` configured per-provider in Web UI, shared by all models under that provider
- `extra_body.enable_thinking` + `drop_params=True` handles thinking mode gracefully (unrecognized params dropped)
- Test script `backend/scripts/test_openai_compatible_llm.py` validates 6 combinations (sync/async × streaming/non-streaming × thinking on/off)
- README.zh.md updated with "接入本地 / 自托管 LLM" configuration guide

**Design Decision:**
- Provider identifier is `local` (not `openai`) — avoids confusion with official OpenAI, leaves room for future `openai` provider
- `is_openai_compatible` field now drives factory routing: when true, `openai/` protocol prefix is hardcoded regardless of provider name
- This means any future OpenAI-compatible provider (e.g. `deepseek`, `zhipu`) only needs `is_openai_compatible=true` in DB — no factory.py changes needed

### 2026-06-12 — Logging Format Standardization

**Logging System Overhaul:**
- Console format: `TIMESTAMP LEVEL user_id=xxx thread_id=xxx request_id=xxxx [filename] log content`
- JSON format (prod): `{"timestamp", "level", "user_id", "thread_id", "request_id", "code_file_path", "message"}`
- `request_id`, `user_id`, `thread_id` auto-injected via `ContextVar` + `logging.Filter` — no manual prefix in log messages
- `user_id` set in `get_current_user` (auth.py), `thread_id` set in `build_agent_kwargs` (request.py)
- Cleaned all manual `[request_id=...][thread_id=...]` prefixes from log messages across the codebase

**Files Changed:**
- `backend/app/utils/logging.py` — Added `user_id_context`/`thread_id_context` ContextVars, updated `RequestIdFilter` and `JsonFormatter`
- `backend/app/infra/auth.py` — Set `user_id_context` in `get_current_user`
- `backend/app/utils/request.py` — Set `thread_id_context` in `build_agent_kwargs`, cleaned log prefixes
- `backend/app/services/streaming.py` — Cleaned manual log prefixes
- `backend/app/services/chat.py` — Cleaned manual log prefixes
- `backend/app/api/v1/chat/run.py` — Cleaned manual log prefixes
- `backend/app/api/v1/chat/history.py` — Cleaned manual log prefixes
- `backend/run_backend.py` — Updated console formatter
- `backend/app/main.py` — Updated console formatter

### v0.0.2 (2026-06-08) — Authentication Refactoring

**Authentication System Overhaul:**
- Moved from client-side `user_id` storage to server-side JWT cookie authentication
- Backend: All API endpoints now use `get_current_user` dependency to extract user from JWT
- Frontend: Removed localStorage/URL-based user ID management, added `credentials: "include"` to all requests
- Added automatic 401 handling with redirect to `/login` page
- Auth endpoints now return `JSONResponse` with consistent JSON format

**Files Changed:**
- `backend/app/api/v1/auth.py` — JSONResponse format, auth status endpoint
- `backend/app/api/v1/chat/*.py` — Removed `user_id` query params, use `get_current_user`
- `backend/app/api/v1/models.py` — User extraction from JWT
- `backend/app/api/v1/traces.py` — User extraction from JWT
- `backend/app/infra/auth.py` — Added `get_current_user` function
- `frontend/src/lib/api.ts` — Cookie-based auth, 401 handling, deprecated client-side user ID functions
- `frontend/src/hooks/use-user.ts` — Complete refactor to use API-based authentication
- `frontend/src/App.tsx` — Updated for new auth flow

### v0.0.1 (2026-06-05) — Initial Release

**Completed Features:**
- Supervisor Agent basic conversation capabilities
- Dynamic model switching (runtime LLM switching)
- Tool calling (time query, web search via Tavily)
- SSE streaming response
- Multi-user session isolation
- Long-term memory (LangGraph Store + PGVector)
- WeChat integration (WebSocket message push)
- Docker one-click deployment

## Next Steps

### Immediate Priorities (In Development)

1. **ReAct SubAgent** — Add reasoning and acting capabilities for complex multi-step tasks
2. **RAG SubAgent** — Implement retrieval-augmented generation for knowledge base queries
3. **Multi-Agent Collaboration** — Enable multiple agents to work together on complex problems

### Future Considerations

- Enhanced tool ecosystem (more built-in tools)
- Agent orchestration DSL for custom workflows
- Admin dashboard for monitoring and analytics
- API rate limiting and usage quotas

## Active Decisions & Considerations

### Architecture Decisions

1. **Supervisor Pattern**: Chosen for simplicity and clear routing. May evolve to more sophisticated patterns as SubAgents are added.

2. **PostgreSQL + pgvector**: Single database for both relational data and vector embeddings. Simplifies deployment and operations.

3. **LiteLLM Router**: Provides unified interface to multiple LLM providers with built-in fallback/retry logic.

4. **Middleware Chain**: LangChain v1 official middleware pattern for request processing (prompt → model selection → content filter → summarization).

### Known Constraints

- LangSmith tracing only allowed in `dev` mode (disabled in `prod`)
- JWT authentication required for all user-facing APIs (HTTP-only cookies)
- No client-side user ID storage — always extracted server-side from JWT
- API keys stored encrypted in database (AES-256)
- PostgreSQL is the only supported database (no SQLite/MySQL support)
- Frontend must include `credentials: "include"` for cookie transmission

## Important Patterns & Preferences

### Code Style
- Python backend: FastAPI async patterns, Pydantic v2 for validation
- TypeScript frontend: React 19 with hooks, Tailwind CSS for styling
- All configuration via environment variables (`.env` files)
- Comprehensive logging with JSON format option for production

### Development Workflow
- Docker Compose for local development and production
- `backend/` and `frontend/` directories are independently deployable
- Database migrations via SQL scripts in `backend/scripts/`

## Project Insights

### What Works Well
- Four-layer architecture provides clear separation of concerns
- Middleware pattern allows easy extension of agent behavior
- SSE streaming gives responsive user experience
- Docker one-click deployment lowers barrier to entry

### Areas for Improvement
- Test coverage needs to be established
- API documentation could be enhanced
- Error messages could be more user-friendly
- Performance benchmarking needed for production readiness