# Active Context

## Current Focus

Authentication refactoring completed. System now uses server-side JWT cookie authentication instead of client-side user ID management.

## Recent Changes

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