# System Patterns

## Architecture Overview

AgentHub implements a **Four-Layer Architecture** with strict unidirectional dependencies: `API → Agent → Service → Infra`

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Layer 4: API Layer (HTTP Interface)                   │
│                                                                              │
│   auth.py · chat/ · models.py · traces.py · weixin.py                       │
│                                                                              │
│   Responsibilities: HTTP endpoints, parameter validation, SSE streaming,     │
│                     global exception handling                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Layer 3: Agent Layer (Business Logic)                    │
│                                                                              │
│   supervisor.py · middleware/ · prompts/ · tools/                           │
│                                                                              │
│   Responsibilities: Agent compilation, middleware chain, tool execution,     │
│                     state management                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Layer 2: Service Layer (Business Services)              │
│                                                                              │
│   streaming.py · chat.py · weixin_listener.py                               │
│                                                                              │
│   Responsibilities: Session management, message persistence, SSE streaming,  │
│                     WeChat message listening                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Layer 1: Infrastructure Layer (Foundation)                │
│                                                                              │
│   config.py · database/ · llm/ · security/ · auth.py                        │
│                                                                              │
│   Responsibilities: Database connection pool, LLM gateway, vector store,     │
│                     JWT authentication, configuration management             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Design Patterns

### 1. Supervisor Pattern (Agent Layer)

The Supervisor serves as the single entry point for all user requests, routing to appropriate handlers:

```
User Request → Supervisor (Intent Recognition + Task Routing)
                    │
                    ├── Chat SubAgent (Current)
                    ├── ReAct SubAgent (Planned)
                    ├── RAG SubAgent (Planned)
                    └── Multi-Agent Collaboration (Planned)
```

**Implementation**: `backend/app/agents/supervisor.py`
- Agent instance is a module-level singleton (`_agent_instance`)
- Built once at startup via `init_agent()` during FastAPI lifespan
- Multi-turn state maintained by LangGraph Checkpointer

### 2. Middleware Chain Pattern

LangChain v1 official middleware pattern for request processing:

```python
middleware: list = [
    supervisor_prompt,      # @dynamic_prompt: loads MD template + time context
    dynamic_model,          # DynamicModelMiddleware: runtime model switching
    content_filter,         # ContentFilterMiddleware: removes non-standard content
    SummarizationMiddleware(
        model=model,
        trigger=("tokens", 4000),
        keep=("messages", 20),
    ),
]
```

**Order matters**: Pre-processing → Model Selection → Content Filter → Post-processing

### 3. Repository Pattern (CRUD Layer)

Database operations are encapsulated in CRUD modules:

- `backend/app/crud/chat.py` — Chat session and message operations
- `backend/app/crud/user.py` — User management
- `backend/app/crud/model.py` — Model configuration
- `backend/app/crud/provider.py` — LLM provider management

### 4. Dependency Injection

FastAPI's dependency injection for:
- Database sessions (`get_async_session`)
- Current user (`get_current_user`)
- Agent instance (`get_agent`)

### 5. SSE Streaming Pattern

Server-Sent Events for token-level streaming:

```
Client Request → Service Layer → Agent.astream_events() → SSE Event Stream
```

**Implementation**: `backend/app/services/streaming.py` + `backend/app/utils/sse.py`

## Component Relationships

### Agent Initialization Flow

```
FastAPI Lifespan (startup)
    │
    ├── init_system_llm()         # System default LLM
    ├── init_embedding_model()    # For vector store
    ├── init_database()           # PostgreSQL + PGVector
    │       ├── vectorstore
    │       ├── checkpointer      # LangGraph state persistence
    │       └── store             # Long-term memory
    ├── get_model_manager().refresh()  # Load model configs from DB
    ├── preload_templates()       # Prompt templates
    └── init_agent()              # Build and cache agent graph
```

### Request Processing Flow

```
HTTP Request
    │
    ├── API Layer (Validation + Auth)
    │       │
    │       └── Service Layer (Context Building)
    │               │
    │               └── Agent Layer (Execution)
    │                       │
    │                       ├── Middleware Chain
    │                       │       ├── supervisor_prompt (load prompt)
    │                       │       ├── dynamic_model (select model)
    │                       │       ├── content_filter (clean content)
    │                       │       └── summarization (if needed)
    │                       │
    │                       ├── Tool Execution (if needed)
    │                       │       ├── get_current_time
    │                       │       └── web_search (Tavily)
    │                       │
    │                       ├── LLM Call (via LiteLLM Router)
    │                       │
    │                       ├── Checkpointer (persist state)
    │                       │
    │                       └── Store (long-term memory)
    │
    └── SSE Streaming Response
```

## Critical Implementation Paths

### Dynamic Model Switching

1. User selects model in UI
2. Request includes `model_id` in context
3. `dynamic_model` middleware intercepts request
4. Model manager provides configured LLM instance
5. Agent uses switched model for this request only

### Long-Term Memory

1. User preference extracted during conversation
2. Stored in LangGraph Store with embedding
3. PGVector enables semantic search
4. Retrieved in subsequent sessions for personalization

### Multi-User Isolation

1. Each user authenticated via JWT
2. Session ID included in every request
3. Checkpointer uses `thread_id` (user_id + session_id) for state isolation
4. Store uses `user_id` namespace for memory isolation

## Authentication Flow

AgentHub uses **JWT-based authentication with HTTP-only cookies**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Authentication Architecture                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Frontend                          Backend                                  │
│   ─────────                         ─────────                               │
│                                                                              │
│   1. Login Request ──────────────────► POST /api/v1/auth/mock-login         │
│                                                                              │
│   2. Set-Cookie: jwt_token ──────────► HTTP-only, Secure, SameSite=Lax     │
│                                                                              │
│   3. API Request ───────────────────► GET /api/v1/chat/...                  │
│      + credentials: "include"               │                                │
│                                             ▼                                │
│                                      get_current_user()                      │
│                                             │                                │
│                                             ▼                                │
│                                      Verify JWT → Extract user_id            │
│                                             │                                │
│                                             ▼                                │
│                                      User object injected into endpoint      │
│                                                                              │
│   4. 401 Response ────────────────────► Redirect to /login                  │
│      (if cookie invalid/expired)                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- No client-side user ID storage (no localStorage/URL params)
- All API endpoints use `get_current_user` dependency to extract user from JWT
- Frontend includes `credentials: "include"` for cookie transmission
- 401 responses trigger automatic redirect to login page

## Directory Structure Mapping

```
backend/app/
├── api/                    # Layer 4: HTTP endpoints
│   ├── auth.py            # Authentication endpoints (login, logout, status)
│   ├── chat/              # Chat endpoints (sessions, messages, streaming)
│   ├── models.py          # Model management endpoints
│   ├── traces.py          # LangSmith trace endpoints
│   └── weixin.py          # WeChat integration endpoints
│
├── agents/                 # Layer 3: Agent logic
│   ├── supervisor.py      # Main agent definition
│   ├── context.py         # AgentRuntimeContext schema
│   ├── middleware/        # Middleware implementations
│   ├── prompts/           # Prompt templates (MD files)
│   └── tools/             # Tool implementations
│
├── services/               # Layer 2: Business services
│   ├── chat.py            # Chat service
│   ├── streaming.py       # SSE streaming service
│   └── weixin_listener.py # WeChat message listener
│
├── infra/                  # Layer 1: Infrastructure
│   ├── config.py          # Settings and configuration
│   ├── auth.py            # JWT authentication
│   ├── security.py        # Encryption utilities
│   ├── database/          # Database connections
│   └── llm/               # LLM gateway (LiteLLM)
│
├── crud/                   # Database CRUD operations
├── models/                 # SQLAlchemy ORM models
├── schemas/                # Pydantic schemas
└── utils/                  # Utility functions