# Product Context

## Why AgentHub Exists

AgentHub addresses a critical gap in the AI application landscape: the **last-mile problem from prototype to production deployment**.

Most Agent frameworks excel at helping developers build prototypes quickly, but fall short when it comes to production concerns:
- Multi-user isolation and data privacy
- High-concurrency request handling
- Long-term memory across sessions
- Dynamic model switching without downtime
- Reliable streaming responses at scale

AgentHub is built to solve these problems, providing a true **Agent Runtime Platform** — not just an orchestration framework.

## Problems It Solves

### 1. Production Readiness
- **Problem**: Prototypes built with LangChain/LangGraph don't translate easily to production
- **Solution**: Pre-built four-layer architecture with production best practices (async, connection pooling, error handling, logging)

### 2. Multi-Tenancy
- **Problem**: Agent frameworks typically assume single-user development mode
- **Solution**: Built-in multi-user isolation with LangGraph Checkpointer for per-user state persistence

### 3. Model Flexibility
- **Problem**: Switching LLM providers requires code changes or service restarts
- **Solution**: Runtime dynamic model switching via LiteLLM Router with automatic fallback/retry

### 4. Memory Persistence
- **Problem**: Agents forget user preferences across sessions
- **Solution**: LangGraph Store + PGVector for semantic long-term memory

### 5. Deployment Complexity
- **Problem**: AI applications have complex dependencies (vector DB, LLM APIs, etc.)
- **Solution**: Docker Compose one-click deployment with all components pre-configured

## How It Works

### Request Flow

```
User Request → API Validation → Service Context Building → Agent Middleware Chain → LLM Call → SSE Streaming Response
                                                    ↓
                                            Tool Execution (Time/Search)
                                                    ↓
                                        Checkpointer State Persistence
                                                    ↓
                                        Store Long-Term Memory Semantic Retrieval
```

### Key User Flows

1. **Chat Flow**: User sends message → SSE streaming response with token-level output
2. **Model Switching**: User selects different model in UI → subsequent requests use new model
3. **Session Management**: Each user has isolated sessions with persistent conversation history
4. **WeChat Integration**: WeChat messages received via WebSocket → processed by agent → response pushed back

## User Experience Goals

### For Developers
- **Quick Start**: Clone, configure env, `docker compose up` — running in 5 minutes
- **LangGraph Best Practices**: Production patterns like `create_agent` + Middleware Chain + `astream_events` v3
- **Observable**: LangSmith tracing (dev mode) for debugging agent behavior

### For End Users
- **Responsive**: SSE token-level streaming for real-time response
- **Consistent**: Long-term memory remembers preferences across sessions
- **Flexible**: Switch models mid-conversation without losing context

## Success Metrics

- Time from clone to first chat: < 5 minutes
- Support for concurrent users: 100+ (with proper scaling)
- Response latency: < 2s to first token
- Session isolation: Zero data leakage between users