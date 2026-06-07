# Project Brief

## Project Overview

**AgentHub** is a production-grade Multi-Agent runtime platform that provides a high-performance, stable, and reliable Agent execution environment for AI applications.

It is **not** another Agent orchestration framework, but a true **Agent Runtime Platform** — solving the last-mile problem from prototype to production deployment.

## Core Requirements

### Primary Goals

1. **High Concurrency & Low Latency** — FastAPI async + SSE token-level streaming + LiteLLM Router automatic fallback/retry
2. **Multi-User Isolation** — Independent session spaces with LangGraph Checkpointer state persistence, complete data isolation
3. **Dynamic Model Switching** — Runtime LLM switching (OpenAI, Anthropic, Groq, Ollama, etc.) without session restart
4. **Long-Term Memory** — LangGraph Store + PGVector semantic retrieval, cross-session user preference persistence
5. **Production-Ready Deployment** — Docker Compose three-container orchestration, complete service startup in 5 minutes

### Architecture Pattern

AgentHub adopts the **Supervisor Pattern**:

```
User Request → Supervisor (Intent Recognition + Task Routing)
                    │
                    ├── Chat SubAgent (Available Now)
                    │
                    ├── ReAct SubAgent (In Development)
                    │
                    ├── RAG SubAgent (In Development)
                    │
                    └── Multi-Agent Collaboration (In Development)
```

### Four-Layer Architecture

Strict unidirectional dependencies: `API → Agent → Service → Infra`

- **Layer 4: API Layer** — HTTP endpoints, parameter validation, SSE streaming, global exception handling
- **Layer 3: Agent Layer** — Agent compilation, middleware chain, tool execution, state management
- **Layer 2: Service Layer** — Session management, message persistence, SSE streaming, WeChat message listening
- **Layer 1: Infrastructure Layer** — Database connection pool, LLM gateway, vector store, JWT authentication, configuration management

## Target Users

- **Individual Developers / Learners** — Quickly practice LangGraph production-level development
- **Startup Teams** — Rapidly validate Multi-Agent product ideas
- **Enterprise Users** — Build internal AI assistants, knowledge bases, intelligent workflows

## Scope

### In Scope

- Supervisor Agent with basic conversation capabilities
- Dynamic model switching at runtime
- Tool calling (time query, web search)
- SSE streaming response
- Multi-user session isolation
- Long-term memory with semantic retrieval
- WeChat integration (WebSocket message push)
- Docker one-click deployment

### Out of Scope (Future)

- ReAct SubAgent
- RAG SubAgent  
- Multi-Agent Collaboration
- Agent orchestration DSL