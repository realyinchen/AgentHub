# Progress

## Current Status

**Version**: v0.0.1 (Initial Release)
**Release Date**: 2026-06-05
**Status**: Production-ready core features, SubAgents in development

## What Works

### Core Platform ✅

## 2026-07-24 Architecture Baseline

- Routing uses Layer 0 rules and Layer 1 keyword/vector recall; Layer 2 remains
  disabled behind a candidate-only port.
- `execution-graph-v2` is authoritative for trace/DAG rendering.
- Deep Research uses seven explicit actions ending in constrained synthesis and
  deterministic publication.
- Evidence quality separates provenance, readability, relevance,
  corroboration, and publishability.
- Research answers are bounded localized Markdown; raw search dumps and
  internal dependency IDs are excluded.
- Backend architecture verifiers, live HTTP verification, frontend graph
  verification, and production build pass.

| Feature | Status | Notes |
|---------|--------|-------|
| Supervisor Agent | ✅ Complete | Basic conversation with tool calling |
| Dynamic Model Switching | ✅ Complete | Runtime LLM switching via middleware |
| SSE Streaming | ✅ Complete | Token-level streaming via `astream_events` v3 |
| Multi-User Isolation | ✅ Complete | Per-user sessions with Checkpointer |
| Long-Term Memory | ✅ Complete | LangGraph Store + PGVector |
| JWT Authentication | ✅ Complete | HTTP-only cookies, 7-day expiry |
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
