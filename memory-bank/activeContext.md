# Active Context

## Current Focus

RoutingDecision, explicit execution-graph-v2, and evidence-gated Deep Research
publication are the current accepted runtime baseline. The route-model port is
present but intentionally disabled.

The canonical authority boundary is:

```text
RoutingDecision -> ActionPlan -> SystemRuntime -> PlanReceipt
```

The current Deep Research response path is:

```text
admitted evidence -> ResearchBrief -> deterministic Markdown publisher
```

Provider text and technical dependency IDs must never be copied directly into
the user-facing answer.

## Recent Changes

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
- JWT authentication required for all user-facing APIs
- API keys stored encrypted in database (AES-256)
- PostgreSQL is the only supported database (no SQLite/MySQL support)

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
