# System Patterns

## System Architecture

```mermaid
flowchart TD
    A[React Frontend<br>(Vite + React + TS + Tailwind CSS + shadcn/ui)<br>localhost:5173] -->|HTTP / SSE| B[FastAPI Backend<br>backend/app/main.py<br>0.0.0.0:8080]

    B --> C[/api/v1/chat/*<br>Chat API (stream, invoke, history)]
    B --> D[/api/v1/agent/*<br>Agent API (list agents)]

    C --> E[chatbot<br>(LangGraph graph)]
    C --> F[rag-agent<br>(LangGraph graph)]
    C --> N[navigator<br>(LangGraph graph)]

    subgraph External Services
        G[Qdrant<br>(vector store)]
        H[Tavily<br>(search tool)]
        I[LangSmith<br>(tracing)]
    end

    E --> G
    E --> H
    E --> I
    F --> G
    F --> H
    F --> I

    K[Amap API<br>(Gaode Map)] <--> N[navigator<br>(Navigation Agent)]
    H[Tavily<br>(search tool)] --> N

    J[PostgreSQL<br>- LangGraph checkpointer<br>- Conversation metadata<br>- Agent registry] <--> B
    J <--> E
    J <--> F

    style A fill:#f9f,stroke:#333,stroke-width:2px
    style B fill:#bbf,stroke:#333,stroke-width:2px
```
**Notes on Diagram:**
- Frontend now a modern SPA with layout: top-left logo + agent selector, left sidebar (conversation history), right main chat area.
- Streaming responses via SSE rendered progressively with distinct message types (user, assistant, tool call, tool result).
- Thinking mode supported for models like DeepSeek-R1, Qwen3 with separate UI for thought process.

## Key Technical Decisions

### 1. Agent Registry Pattern
- Agents are defined as module-level singletons in `backend/app/agents/__init__.py`
- Registered in a `Dict[str, CompiledStateGraph]` keyed by agent ID string
- Active agents are controlled via the PostgreSQL `agents` table (`is_active` flag)
- At startup, active agent IDs are fetched from DB and matched to the registry dict

### 2. Dual Database Manager Pattern
- `AsyncDatabaseManager` (`adb_manager`) — for FastAPI async routes and LangGraph async nodes
  - Uses `asyncpg` driver via SQLAlchemy async extensions
- `DatabaseManager` (`db_manager`) — for CLI scripts, background tasks, non-async contexts
  - Uses `psycopg` driver via SQLAlchemy sync extensions
- Both are module-level singletons initialized lazily at startup

### 3. FastAPI Lifespan Management
- All resources (DB engines, Qdrant, checkpointer) initialized in `@asynccontextmanager lifespan`
- Checkpointer is created as an async context manager and shared across all agents
- Graceful cleanup on shutdown via `dispose()` methods

### 4. LangGraph Checkpointer (Short-term Memory)
- PostgreSQL-based checkpointer (`langgraph-checkpoint-postgres`)
- Shared across all active agents
- Scoped by `thread_id` — each conversation thread has its own state
- Enables multi-turn conversation persistence

### 5. Streaming via SSE
- `/api/v1/chat/stream` returns `StreamingResponse` with `media_type="text/event-stream"`
- Uses `streaming_message_generator()` utility to yield SSE events
- Supports both token-level streaming and intermediate message events

### 6. LiteLLM Multi-Model Router (NEW)
- Uses `langchain-litellm` with `ChatLiteLLMRouter` for unified multi-provider LLM support
- Configuration via `LLM_MODELS` JSON environment variable
- Supports 100+ providers: OpenAI, Azure, Anthropic, DashScope, etc.
- Router manages model selection, load balancing, and failover

### 7. Thinking Mode Support (NEW)
- Separate model configuration with `enable_thinking: true` parameter
- Models like DeepSeek-R1, Qwen3 output structured thinking blocks
- Frontend displays thinking process in collapsible section
- `get_llm(thinking_mode=True)` returns thinking-capable model
- API endpoint `/chat/thinking-mode` checks availability

## Design Patterns in Use

### Singleton Pattern
- `adb_manager`, `db_manager`, `qdrant_manager` — module-level singletons
- `settings` — pydantic-settings singleton
- `llm`, `thinking_llm`, `embedding_model` — module-level singletons in `models.py`

### Repository Pattern (CRUD)
- `backend/app/crud/chat.py` — database operations for conversations
- Separates data access logic from API route handlers

### Factory/Registry Pattern
- `backend/app/agents/__init__.py` — agent registry dict
- `get_agent(agent_id)` factory function in `backend/app/utils/agent_utils.py`
- `get_llm(thinking_mode)` factory function in `backend/app/core/models.py`

### Event-Driven / Streaming
- SSE for real-time agent feedback

### Component-Based UI
- React components for chat, sidebar, selector
- ThinkingModeToggle component for mode switching

## Component Relationships
```
backend/
├── .env                       # Environment variables
├── .env.example               # Environment variables example
├── requirements.txt           # Python dependencies
├── run_backend.py             # Backend startup script
├── scripts/                   # Database and utility scripts
│   └── init_database.py       # Database initialization script
└── app/                      # FastAPI application
    ├── main.py                # FastAPI app + lifespan
    ├── core/
    │   ├── config.py          # pydantic-settings (Settings singleton)
    │   └── models.py          # LLM + embedding model instances (ChatLiteLLMRouter)
    ├── agents/
    │   ├── __init__.py        # Agent registry dict
    │   ├── chatbot.py         # Chatbot agent (StateGraph with tools)
    │   ├── navigator.py       # Navigator agent (StateGraph with Amap tools)
    │   └── agentic_rag/       # Agentic RAG agent (multi-node LangGraph)
    │       ├── graph.py       # StateGraph definition + compilation
    │       ├── state.py       # GraphState TypedDict
    │       ├── chains/        # LLM chains (router, graders)
    │       └── nodes/         # Graph node functions
    ├── api/v1/
    │   ├── router.py          # Combines chat + agent routers
    │   ├── chat.py            # Chat endpoints (stream, invoke, history, thinking-mode)
    │   └── agent.py           # Agent listing endpoint
    ├── database/
    │   ├── db_manager.py      # Async + sync DB managers
    │   ├── checkpointer.py    # LangGraph PostgreSQL checkpointer
    │   ├── qdrant_manager.py  # Qdrant vector store manager
    │   └── base.py            # SQLAlchemy Base
    ├── models/                # SQLAlchemy ORM models
    ├── schemas/               # Pydantic schemas (request/response)
    ├── crud/                  # Database CRUD operations
    ├── tools/                 # LangChain tools collection
    │   ├── __init__.py        # Tool exports
    │   ├── time.py            # get_current_time - timezone-aware time tool
    │   ├── web.py             # create_web_search - Tavily search factory
    │   ├── amap.py            # Amap (高德地图) tools - geocode, place_search, place_around, driving_route
    │   ├── execute_sql_query.py  # SQL query execution
    │   └── vectorstore_retriever.py  # Vector store retrieval
    ├── prompt/                # Centralized prompt templates
    │   ├── __init__.py
    │   ├── chatbot.py         # Chatbot system prompt with tool usage guidelines
    │   └── navigator.py       # Navigator agent system prompt
    └── utils/
        ├── agent_utils.py     # Agent lookup + availability helpers
        └── message_utils.py   # Message conversion + streaming helpers

frontend/                      # React frontend (Vite + React + TypeScript + Tailwind CSS project)
├── .env                       # Frontend environment variables
├── public/                    # Static assets (favicon, logo, etc.)
│   └── agenthub.png           # Project logo
├── src/
│   ├── assets/                # Images, icons, fonts, etc.
│   ├── components/            # Reusable UI components
│   │   ├── ui/                # shadcn/ui components
│   │   └── ai/                # AI-specific components (prompt-input, loader, message)
│   ├── features/              # Feature-based organization
│   │   └── chat/              # Chat feature
│   │       └── components/    # Chat components (main-panel, message-item, sidebar, etc.)
│   ├── hooks/                 # Custom React hooks
│   │   ├── use-mobile.ts      # Mobile detection hook
│   │   ├── use-theme.tsx      # Theme toggle hook
│   │   └── use-thinking-mode.ts  # Thinking mode hook
│   ├── i18n/                  # Internationalization
│   ├── lib/                   # Utility functions, API client
│   │   └── api.ts             # API client (fetch wrapper)
│   ├── types.ts               # TypeScript type definitions
│   ├── App.tsx                # Root component
│   ├── main.tsx               # Entry file
│   └── index.css              # Global styles (Tailwind directives)
├── vite.config.ts             # Vite configuration
├── tailwind.config.js         # Tailwind CSS configuration
├── tsconfig.json              # TypeScript configuration
└── package.json               # Frontend dependencies
```

## Critical Implementation Paths

### Adding a New Agent
1. Create agent file in `backend/app/agents/` (or subdirectory)
2. Define a `CompiledStateGraph` (via LangGraph `StateGraph.compile()`)
3. Register in `backend/app/agents/__init__.py` dict with a unique string key
4. Add a record to the PostgreSQL `agents` table with `is_active=True`

### Chat Request Flow (Streaming)
1. `POST /api/v1/chat/stream` with `{agent_id, thread_id, message, thinking_mode}`
2. `get_agent(agent_id)` looks up agent from registry
3. `get_llm(thinking_mode)` selects appropriate LLM model
4. `streaming_message_generator()` calls `agent.astream_events()`
5. SSE events yielded back to client as they arrive
6. LangGraph checkpointer saves state to PostgreSQL by `thread_id`

### LLM Model Selection
1. Check `LLM_MODELS` environment variable for router mode
2. If router mode: use `ChatLiteLLMRouter` with configured models
3. `get_llm(thinking_mode=False)` returns default model
4. `get_llm(thinking_mode=True)` returns thinking model (if configured)
5. Fallback to legacy single model mode if `LLM_MODELS` not set

### Thinking Mode Flow
1. Frontend checks `/chat/thinking-mode` endpoint for availability
2. User toggles thinking mode via `ThinkingModeToggle` component
3. Request includes `thinking_mode: true` in payload
4. Backend selects thinking-capable model via `get_llm(thinking_mode=True)`
5. Model outputs structured content with thinking blocks
6. Frontend renders thinking content in collapsible section