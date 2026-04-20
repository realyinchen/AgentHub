# System Patterns: AgentHub

## System Architecture

```
AgentHub/
├── frontend/               # Vite + React + TypeScript + Tailwind CSS + shadcn/ui
│   ├── .env                # Frontend environment variables
│   ├── src/                # React components and logic
│   ├── public/             # Static assets
│   ├── package.json        # Frontend dependencies
│   └── vite.config.ts      # Vite build configuration
├── backend/                # FastAPI + LangGraph backend
│   ├── app/                # Main application code
│   │   ├── main.py         # FastAPI application entry point
│   │   ├── agents/         # Agent implementations (chatbot, navigator)
│   │   ├── api/            # API routes
│   │   ├── core/           # Core configurations
│   │   ├── database/       # Database managers and checkpointer
│   │   ├── tools/          # LangChain tools collection
│   │   ├── prompt/         # Centralized prompt templates
│   │   └── ...             # Other modules
│   ├── scripts/            # Database initialization scripts
│   │   └── init_database.py # Initialize PostgreSQL and Qdrant
│   ├── .env                # Environment variables
│   ├── requirements.txt    # Python dependencies
│   └── run_backend.py      # Backend startup script
└── README.md               # This file
```

## Key Technical Decisions

### Backend Architecture
- **FastAPI Lifespan Management** — Uses async context manager for database initialization and cleanup
- **Async-First Design** — Primary use of async APIs (`aget_llm()`, `aembedding_model()`)
- **Checkpointer Pattern** — LangGraph checkpointer for thread-scoped conversation memory
- **Model Manager** — Centralized model configuration management with database-backed settings

### Agent Registration
- Agents are registered in `backend/app/agents/__init__.py`
- Agent availability is controlled via PostgreSQL database
- Each agent has its own checkpointer for conversation history

### Streaming Architecture
- **Server-Sent Events (SSE)** — Real-time streaming of agent responses
- **True Streaming (astream)** — LLM uses `astream()` for real token-by-token streaming (NOT `ainvoke`)
- **Token Usage Capture** — `usage_metadata` captured from stream chunks with `stream_options.include_usage`
- **Event Visualization** — Real-time display of thinking process and tool calls

### Message Sequence Pattern (2026-04-15)
- **Dual Output** — History API returns both `messages` (main chat) and `message_sequence` (sidebar)
- **Step-by-Step Display** — Each LangChain message is an independent step in sidebar
- **No Type Merging** — Multiple messages of same type remain as separate steps
- **LangSmith-style UI** — Similar to LangSmith's node input/output visualization

## Design Patterns in Use

### Repository Pattern
- `adb_manager` — Async database manager
- `db_manager` — Sync database manager
- `qdrant_manager` — Vector store manager

### Factory Pattern
- `get_llm()` / `aget_llm()` — Factory functions for LLM instances
- `embedding_model()` / `aembedding_model()` — Factory functions for embedding models

### Strategy Pattern
- Different agents implement different tool strategies
- Tool selection based on agent type and user query

## Component Relationships

```
Frontend (React) ←→ Backend API (FastAPI) ←→ Agents (LangGraph)
                                            ↓
                                      Tools (LangChain)
                                            ↓
                                    External APIs (Tavily, Amap)
```

### Database Relationships
- PostgreSQL: User data, conversations, model configurations
- Qdrant: Vector embeddings for RAG functionality

## Critical Implementation Paths

### 1. Adding a New Agent
1. Create agent file in `backend/app/agents/`
2. Define tools in `backend/app/tools/`
3. Register agent in `backend/app/agents/__init__.py`
4. Add agent configuration to database via `init_database.sql`

### 2. Streaming Response Flow
1. User sends message via frontend
2. Backend creates/retrieves thread from checkpointer
3. Agent processes message with LangGraph
4. `streaming_completion()` yields tokens via SSE
5. Frontend renders tokens in real-time

### 3. Token Tracking
- Automatic via `streaming_completion()` in `backend/app/utils/llm.py`
- New agents get token tracking by using this function
- Return `result.raw_response` for token stats

### 4. Implementing True Streaming in Agent LLM Call (2026-04-16)

**IMPORTANT: All agents must use `astream()` for true streaming, NOT `ainvoke()`.**

#### Why astream() instead of ainvoke()?
- `ainvoke()` is a one-shot call that returns the complete response at once
- `astream()` yields chunks as they arrive, enabling real token-by-token streaming
- Token usage (`usage_metadata`) is more stable and reliable with `astream()`
- LangGraph's `astream_events` can capture real streaming chunks

#### Step-by-Step Implementation

**Step 1: Configure ChatLiteLLM with stream_options**

In `get_chat_litellm()` (backend/app/utils/llm.py), add `model_kwargs`:

```python
llm_kwargs: dict[str, Any] = {
    "model": litellm_model,
    "temperature": temperature,
    "streaming": True,
    "drop_params": True,
    # KEY: Enable usage metadata in stream
    "model_kwargs": {
        "stream_options": {"include_usage": True}
    },
}

# When binding tools, also pass model_kwargs
if tools:
    llm = llm.bind_tools(
        tools,
        extra_body=extra_body,
        **{"model_kwargs": {"stream_options": {"include_usage": True}}}
    )
```

**Step 2: Implement llm_call node with astream**

```python
async def llm_call(state: State, config: RunnableConfig) -> dict:
    # ... get model_name, thinking_mode, tools, messages ...
    
    llm = get_chat_litellm(
        model=model_name,
        thinking_mode=thinking_mode,
        tools=tools,
    )
    
    # TRUE STREAMING - collect from chunks
    full_content = ""
    usage_metadata = None
    tool_calls_list: list[dict] = []
    reasoning_content = ""
    
    async for chunk in llm.astream(full_messages, config=config):
        # 1. Collect content
        if chunk.content:
            if isinstance(chunk.content, str):
                full_content += chunk.content
            elif isinstance(chunk.content, list):
                # Handle structured content (thinking models)
                for block in chunk.content:
                    if isinstance(block, dict):
                        block_type = block.get("type")
                        if block_type == "text":
                            full_content += block.get("text", "")
                        elif block_type == "thinking":
                            reasoning_content += block.get("thinking", "")
        
        # 2. Collect tool_calls
        if hasattr(chunk, "tool_calls") and chunk.tool_calls:
            for tc in chunk.tool_calls:
                tool_calls_list.append({
                    "id": getattr(tc, "id", ""),
                    "name": getattr(tc, "name", ""),
                    "args": getattr(tc, "args", {}),
                    "type": "tool_call",
                })
        
        # 3. Capture usage_metadata (usually in last chunk)
        if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
            usage_metadata = chunk.usage_metadata
    
    # Build final AIMessage
    ai_message = AIMessage(
        content=full_content,
        tool_calls=tool_calls_list,
        usage_metadata=usage_metadata,
    )
    
    if reasoning_content:
        ai_message.additional_kwargs["reasoning_content"] = reasoning_content
    
    return {"messages": [ai_message]}
```

**Step 3: Token Usage Events**

The `streaming_message_generator()` in chat.py captures usage from `on_chat_model_end` events and sends SSE events:

```
event: usage
data: {"node": "llm_call", "usage": {"input_tokens": X, "output_tokens": Y, "total_tokens": Z}}
```

Frontend handles this in `App.tsx`:
```typescript
if (event.type === "usage") {
  console.log(`[${event.content.node}] Token usage: ...`)
}
```

#### Reference Implementation
- See `backend/app/agents/chatbot.py` for complete example
- See `backend/app/agents/navigator.py` for another example

## API Design Patterns

- **Only GET, POST, DELETE** — No PATCH/PUT to avoid URL encoding issues
- **Model ID in Request Body** — POST requests use model_id in body (not URL params)
- **OpenAPI Documentation** — Auto-generated via FastAPI with custom operation IDs