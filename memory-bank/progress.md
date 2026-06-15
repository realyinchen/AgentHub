# Progress

## Current Status

**Version**: v0.0.2 (Authentication Refactoring)
**Release Date**: 2026-06-08
**Status**: Production-ready core features with improved authentication, standardized logging, SubAgents in development

## What Works

### Core Platform ✅

| Feature | Status | Notes |
|---------|--------|-------|
| Supervisor Agent | ✅ Complete | Basic conversation with tool calling |
| Dynamic Model Switching | ✅ Complete | Runtime LLM switching via middleware |
| Local / Self-Hosted LLM | ✅ Complete | 2026-06-15: Provider `local` with configurable base_url, `is_openai_compatible` routing |
| SSE Streaming | ✅ Complete | Token-level streaming via `astream_events` v3 |
| Multi-User Isolation | ✅ Complete | Per-user sessions with Checkpointer |
| Long-Term Memory | ✅ Complete | LangGraph Store + PGVector |
| JWT Authentication | ✅ Complete | HTTP-only cookies, 7-day expiry, server-side user extraction |
| Auth Refactoring | ✅ Complete | v0.0.2: Removed client-side user ID, cookie-based auth |
| Logging Standardization | ✅ Complete | 2026-06-12: Structured format with auto-injected context fields |
| API Key Encryption | ✅ Complete | AES-256 encryption for stored keys |
| Docker Deployment | ✅ Complete | One-click three-container setup |

### Tools ✅

| Tool | Status | Notes |
|------|--------|-------|
| `get_current_time` | ✅ Complete | Timezone-aware time query |
| `web_search` | ✅ Complete | Tavily-powered web search |

### Integrations ✅

| Integration | Status | Notes |
|-------------|--------|-------|
| WeChat iLink | ✅ Complete | WebSocket message push |
| LangSmith | ✅ Complete | Tracing (dev mode only) |
| LiteLLM Router | ✅ Complete | Multi-provider with fallback/retry |
| Local / Self-Hosted Provider | ✅ Complete | 2026-06-15: Any OpenAI-compatible endpoint (vLLM, Ollama, etc.) via `local` provider |

### Frontend ✅

| Feature | Status | Notes |
|---------|--------|-------|
| Chat UI | ✅ Complete | SSE streaming, markdown rendering |
| Session Management | ✅ Complete | Create, list, delete sessions |
| Model Selection | ✅ Complete | Dynamic model switching UI |
| User Authentication | ✅ Complete | Login, register, logout |
| Responsive Design | ✅ Complete | Mobile-friendly |

## What's Left to Build

### Phase 1: SubAgents (In Development)

| Feature | Status | Priority |
|---------|--------|----------|
| ReAct SubAgent | 🔄 In Progress | High |
| RAG SubAgent | 📋 Planned | High |
| Multi-Agent Collaboration | 📋 Planned | Medium |

### Phase 2: Enhanced Tooling

| Feature | Status | Priority |
|---------|--------|----------|
| Code Interpreter | 📋 Planned | Medium |
| File Processing | 📋 Planned | Medium |
| Custom Tool Framework | 📋 Planned | Medium |

### Phase 3: Platform Features

| Feature | Status | Priority |
|---------|--------|----------|
| Admin Dashboard | 📋 Planned | Medium |
| Usage Analytics | 📋 Planned | Low |
| Rate Limiting | 📋 Planned | Medium |
| API Quotas | 📋 Planned | Low |

### Phase 4: Developer Experience

| Feature | Status | Priority |
|---------|--------|----------|
| Agent Orchestration DSL | 📋 Planned | Low |
| Custom Agent Templates | 📋 Planned | Low |
| CLI Tool | 📋 Planned | Low |

## Known Issues

1. **Test Coverage**: No automated tests yet — needs unit and integration tests
2. **API Documentation**: OpenAPI docs exist but could be enhanced with more examples
3. **Error Messages**: Some error messages are technical; could be more user-friendly
4. **Performance Benchmarking**: No load testing done yet for production readiness

## Evolution of Project Decisions

### Architecture Decisions

| Decision | Rationale | Status |
|----------|-----------|--------|
| Four-layer architecture | Clean separation, testability | ✅ Final |
| Supervisor Pattern | Simple routing, extensible | ✅ Final |
| PostgreSQL + pgvector | Single DB for all data types | ✅ Final |
| LiteLLM Router | Multi-provider support, fallback | ✅ Final |
| Middleware Chain | LangChain v1 best practice | ✅ Final |

### Technology Choices

| Choice | Rationale | Status |
|--------|-----------|--------|
| FastAPI over Flask/Django | Async-native, OpenAPI | ✅ Final |
| React 19 over Vue/Svelte | Ecosystem, TypeScript support | ✅ Final |
| Tailwind CSS | Rapid UI development | ✅ Final |
| Docker Compose over K8s | Simplicity for target users | ✅ Final |

## Milestone History

### 2026-06-15 — Local / Self-Hosted LLM Provider

**Multi-Provider Support:**
- New `local` provider in database seed (idempotent INSERT, `is_openai_compatible=true`)
- `factory.py` added `is_openai_compatible` routing: when true, hardcodes `openai/` protocol prefix for LiteLLM
- Provider name `local` avoids confusion with official OpenAI, leaves room for future providers
- `is_openai_compatible` field now drives factory behavior — any future OpenAI-compatible provider only needs this flag in DB
- `base_url` configurable per-provider via Web UI
- Test script validates sync/async × streaming/non-streaming × thinking on/off (6 combinations)
- README.zh.md updated with "接入本地 / 自托管 LLM" configuration guide

**Files Changed (4 files):**
- `backend/scripts/sql/000_init_database.sql` — Added `local` provider INSERT
- `backend/app/infra/llm/factory.py` — Added `is_openai_compatible` special-casing
- `backend/scripts/test_openai_compatible_llm.py` — New test script
- `memory-bank/activeContext.md` + `progress.md` — Documentation

### v0.0.2 (2026-06-08) — Authentication Refactoring

**Security & Architecture Improvements:**
- Server-side JWT cookie authentication (no client-side user ID storage)
- All API endpoints use `get_current_user` dependency for user extraction
- Frontend sends `credentials: "include"` for cookie transmission
- Automatic 401 handling with redirect to `/login`
- Consistent JSONResponse format for auth endpoints
- Deprecated client-side `setCurrentUserId` / `getCurrentUserId` functions

**Files Changed (16 files):**
- Backend: auth.py, conversations.py, history.py, run.py, stats.py, models.py, traces.py, weixin.py, infra/auth.py
- Frontend: App.tsx, chat-main-panel.tsx, turn-dag-sidebar.tsx, useTurnSteps.ts, use-user.ts, api.ts, types.ts

### v0.0.1 (2026-06-05) — Initial Release

- Core Supervisor Agent with conversation capabilities
- Dynamic model switching
- Tool calling (time, web search)
- SSE streaming response
- Multi-user session isolation
- Long-term memory
- WeChat integration
- Docker one-click deployment

## Next Milestone: v0.1.0

**Target**: SubAgent Architecture

- [ ] ReAct SubAgent for multi-step reasoning
- [ ] RAG SubAgent for knowledge retrieval
- [ ] Supervisor routing to SubAgents based on intent
- [ ] Tool sharing across SubAgents