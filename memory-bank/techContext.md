# Tech Context

## Technologies Used

### Backend
| Technology              | Version   | Purpose                              |
|-------------------------|-----------|--------------------------------------|
| Python                  | 3.12      | Runtime                              |
| FastAPI                 | 0.121.2   | REST API framework                   |
| Uvicorn                 | 0.38.0    | ASGI server                          |
| Pydantic / pydantic-settings | (via FastAPI) | Data validation + config management |

### AI / LLM
| Technology              | Version   | Purpose                              |
|-------------------------|-----------|--------------------------------------|
| LangChain               | 1.2.10    | LLM orchestration framework          |
| LangChain-Community     | 0.4.1     | Community integrations               |
| LangChain-LiteLLM       | 0.6.1     | Multi-provider LLM client (replaces langchain-openai) |
| LangGraph               | 1.0.9     | Agent workflow graphs                |
| LangSmith               | 0.4.59    | Tracing and observability            |
| DashScope               | 1.25.1    | Alibaba Cloud AI SDK                 |
| LangChain-Tavily        | 0.2.17    | Tavily web search integration        |
| LangChain-Qdrant        | 1.1.0     | Qdrant vector store integration      |
| LiteLLM                 | (via langchain-litellm) | Unified LLM API with multi-provider support |

### Database
| Technology              | Version   | Purpose                              |
|-------------------------|-----------|--------------------------------------|
| PostgreSQL              | (external)| Primary database                     |
| SQLAlchemy              | (via deps)| ORM + connection pooling             |
| asyncpg                 | 0.31.0    | Async PostgreSQL driver              |
| psycopg-binary          | 3.3.2     | Sync PostgreSQL driver               |
| langgraph-checkpoint-postgres | 3.0.4 | LangGraph state persistence          |
| Qdrant                  | (external)| Vector store for RAG                 |

### Frontend
| Technology              | Version   | Purpose                              |
|-------------------------|-----------|--------------------------------------|
| Vite                    | 7.3.1     | Fast build tool & dev server         |
| React                   | 19.2.0    | UI component library                 |
| TypeScript              | ~5.9.3    | Static typing for safety             |
| Tailwind CSS            | 4.2.1     | Utility-first CSS framework          |
| shadcn/ui               | 3.8.5     | Accessible, customizable components  |
| Lucide React            | 0.575.0   | Icon library                         |
| Tiptap                  | 3.20.0    | Rich text editor                     |
| React Markdown          | 10.1.0    | Markdown rendering                   |
| Shiki                   | 3.22.0    | Syntax highlighting                  |
| Marked                  | 17.0.3    | Markdown parsing                     |
| Radix UI                | 1.4.3     | Low-level accessible components      |
| Class Variance Authority| 0.7.1     | Component variants                   |
| Tailwind Merge          | 3.5.0     | Class name merging                   |
| ai                      | 6.0.101   | Vercel AI SDK for chat UI patterns   |
| cmdk                    | 1.1.1     | Command menu component               |
| nanoid                  | 5.1.6     | Unique ID generator                  |
| streamdown              | 2.3.0     | Markdown streaming renderer          |

### Utilities
| Technology              | Version   | Purpose                              |
|-------------------------|-----------|--------------------------------------|
| python-dotenv           | 1.2.1     | .env file loading (backend)          |

## Development Setup

### Development Environment
- **Operating System**: Windows 11
- **Shell**: PowerShell (default)
- **IDE**: Visual Studio Code
- **Package Manager**: pnpm (frontend), pip (backend)

### Prerequisites
- VS Code (recommended)
- Miniconda / Python 3.12
- Node.js 18+ & npm/pnpm/yarn (for frontend)
- PostgreSQL instance (local/remote)
- Qdrant instance (local/remote)
- LLM API keys (DashScope, OpenAI, or other LiteLLM-supported providers)
- Tavily Search API key
- LangSmith API key (optional, for tracing)

### Setup Steps

#### Backend
```bash
# 1. Create & activate conda env
conda create -n agenthub python=3.12
conda activate agenthub

# 2. Copy & configure .env
cp .env.example .env
# Edit .env with your credentials

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize database
python scripts/init_database.py

# 5. Start backend
python run_backend.py
```

#### Frontend
```bash
# Navigate to frontend directory
cd frontend

# Install dependencies (first time only)
npm install

# Start dev server
npm run dev
```

### Access Points
- Frontend: `http://localhost:5173`
- Backend API: `http://0.0.0.0:8080`
- Swagger UI: `http://0.0.0.0:8080/docs`

## Configuration

Configuration is split:
- Backend: .env file loaded via pydantic-settings
- Frontend: .env file in frontend/ (Vite uses VITE_ prefix)

### Key Environment Variables

#### Backend (backend/.env)
```env
# Application
MODE=dev                          # "dev" enables uvicorn auto-reload

# Server
HOST=0.0.0.0
PORT=8080

# LLM Multi-model Configuration (Recommended)
# JSON array of model configurations for LiteLLM Router
LLM_MODELS=[{"model_name":"default","litellm_params":{"model":"dashscope/qwen3-max","api_key":"sk-...","api_base":"https://dashscope.aliyuncs.com/compatible-mode/v1"}},{"model_name":"thinking","litellm_params":{"model":"dashscope/qwen3.5-27b","api_key":"sk-...","api_base":"https://dashscope.aliyuncs.com/compatible-mode/v1","extra_body":{"enable_thinking":true}}}]

LLM_DEFAULT_MODEL=default         # Default model name
LLM_THINKING_MODEL=thinking       # Thinking model name (optional)

# Embedding model
EMBEDDING_MODEL_NAME=text-embedding-v4

# Legacy single model configuration (fallback)
LLM_API_KEY=sk-...
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_NAME=qwen3-max

# LangSmith Tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT="AgentHub"
LANGCHAIN_API_KEY=lsv2_...

# PostgreSQL
POSTGRES_USER=langchain
POSTGRES_PASSWORD=langgraph
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agentdb

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=agentic_rag_survey

# Tavily Search
TAVILY_API_KEY=tvly-...

# Amap (高德地图)
AMAP_KEY=your_amap_key_here
```

#### Frontend (frontend/.env)
```env
VITE_API_BASE_URL=http://localhost:8080/api/v1
```

## Technical Constraints

1. **LLM Provider**: Now uses LiteLLM for unified multi-provider support. Supports DashScope (Qwen models), OpenAI, Azure, Anthropic, and 100+ other providers. Configure via `LLM_MODELS` JSON for multi-model setup.

2. **PostgreSQL Required**: The application requires a running PostgreSQL instance for:
   - LangGraph conversation checkpointing
   - Conversation metadata storage
   - Agent registry

3. **Qdrant Required for RAG**: The `rag-agent` requires a running Qdrant instance with a pre-populated collection (`QDRANT_COLLECTION`).

4. **Python 3.12**: The project targets Python 3.12 specifically.

5. **Async-first**: The FastAPI backend is async-first. The sync `DatabaseManager` is provided for non-async contexts (scripts, tests) only.

6. **Thinking Mode**: Requires `LLM_THINKING_MODEL` to be configured in `LLM_MODELS`. Supported by models like DeepSeek-R1, Qwen3 with `enable_thinking: true` parameter.

## Tool Usage Patterns

### LLM Initialization (`backend/app/core/models.py`)
- Uses `ChatLiteLLMRouter` for multi-model management via `litellm.router.Router`
- Supports both router mode (multi-model) and legacy single model mode
- Thinking mode available via separate model configuration with `enable_thinking` parameter
- LLM selection via `get_llm(thinking_mode=True/False)`

### Agent Creation
- Simple agents: LangGraph `StateGraph` with custom nodes and edges
- Tool binding: `llm.bind_tools(tools)`
- Streaming: `llm.astream(messages)` for token-level streaming

### Database Sessions
```python
# Async (in FastAPI routes / LangGraph nodes)
async with adb_manager.session() as session:
    result = await session.execute(...)

# Sync (in scripts / non-async contexts)
with db_manager.session() as session:
    result = session.execute(...)
```

### Frontend Patterns
- API calls via native `fetch` with async/await
- SSE streaming via `ReadableStream` reader
- State management: React hooks (useState, useCallback, useMemo)