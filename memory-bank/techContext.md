# Tech Context: AgentHub

## Technologies Used

### Backend
- **Python 3.12** — Runtime environment
- **FastAPI** — High-performance web framework with automatic API documentation
- **LangChain** — LLM orchestration framework
- **LangGraph** — Agent workflow graphs for complex reasoning
- **PostgreSQL** — Primary database with async/sync support
- **Qdrant** — Vector store for RAG functionality
- **Uvicorn** — ASGI server for production deployment

### Frontend
- **Vite** — Next-generation build tool with instant server start
- **React 19** — Component-based UI library
- **TypeScript** — Static typing for code safety
- **Tailwind CSS** — Utility-first CSS framework
- **shadcn/ui** — Accessible, customizable UI components
- **TanStack Query** — Data fetching and state management
- **Lucide React** — Beautiful icon library

## Development Setup

### Prerequisites
1. VS Code
2. Miniconda
3. Node.js 18+
4. Docker (for PostgreSQL and Qdrant)

### Environment Setup
```bash
# Create and activate virtual environment
conda create -n agenthub python=3.12
conda activate agenthub

# Clone repository
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# Install backend dependencies
cd backend
pip install -r requirements.txt

# Install frontend dependencies
cd ../frontend
npm install
```

### Docker Services
```bash
# Start PostgreSQL
docker run -d --name agenthub-postgres \
  -e POSTGRES_USER=langchain \
  -e POSTGRES_PASSWORD=langgraph \
  -e POSTGRES_DB=agentdb \
  -p 5432:5432 \
  postgres:latest

# Start Qdrant
docker run -d --name agenthub-qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  qdrant/qdrant:latest
```

## Technical Constraints

### API Design
- Only use GET, POST, DELETE endpoints (no PATCH/PUT)
- Model update/delete operations use POST with model_id in request body
- Avoids URL encoding issues with `/` character in model_id (e.g., `zai/glm-5`)

### LLM API Usage
- **Recommended (Async API):**
  - Use `aget_llm()`, `aembedding_model()` in FastAPI async endpoints
  - Use `streaming_completion()` for LLM calls with automatic token tracking
- **Compatibility Only (Sync Wrappers):**
  - `get_llm()`, `embedding_model()` — for legacy code or non-async contexts only
  - These add overhead when called from async context (triggers warning log)

## Dependencies

### Backend Key Dependencies
- FastAPI ecosystem (fastapi, uvicorn, pydantic)
- LangChain ecosystem (langchain, langchain-core, langgraph)
- Database drivers (asyncpg, psycopg2, qdrant-client)
- Utilities (python-dotenv, httpx, tavily-python)

### Frontend Key Dependencies
- React ecosystem (react, react-dom, react-router-dom)
- UI libraries (@radix-ui/*, tailwindcss, class-variance-authority)
- State management (@tanstack/react-query)
- Icons (lucide-react)

## Tool Usage Patterns

### LLM Configuration
- LLM/VLM models configured in `backend/scripts/sql/init_database.sql`
- Embedding models configured in `backend/.env`
- Model manager provides centralized access to model configurations

### Streaming Pattern
```python
# Use streaming_completion for automatic token tracking
async for event in streaming_completion(llm, messages, ...):
    yield event
# Return result.raw_response for token stats
```

### Agent Pattern
```python
# Register agent in __init__.py
from app.agents.chatbot import chatbot
from app.agents.navigator import navigator

__all__ = ["chatbot", "navigator"]
```

## Performance Configuration

### Database Connection Pool
```python
# backend/app/database/db_manager.py
pool_size=20,              # Base connections
max_overflow=30,           # Overflow connections
pool_recycle=300,          # Connection recycle time (seconds)
pool_use_lifo=True,        # LIFO mode for better performance
```

### Rate Limiting
```python
# backend/app/core/rate_limiter.py
default_limits=["100/minute"]  # Global default per IP
RateLimits.LIST_AGENTS = "30/minute"
RateLimits.STREAM_CHAT = "10/minute"
```

### Caching
```python
# backend/app/core/cache.py
_models_cache = TTLCache(maxsize=100, ttl=300)      # 5 min
_providers_cache = TTLCache(maxsize=50, ttl=300)    # 5 min
_conversations_cache = TTLCache(maxsize=200, ttl=60) # 1 min
_vector_search_cache = TTLCache(maxsize=500, ttl=600) # 10 min
```

### Qdrant HNSW Index
```python
# backend/app/database/qdrant_manager.py
hnsw_config={
    "m": 16,              # Connections per node
    "ef_construct": 200,  # Construction search factor
}
ef_search=200              # Query-time search factor
```

## Configuration Files

| File | Purpose |
|------|---------|
| `backend/.env` | Backend environment variables (embedding model, API keys) |
| `backend/scripts/sql/init_database.sql` | LLM/VLM model configurations + DB indexes |
| `frontend/.env` | Frontend environment variables |
| `backend/docker-compose.yml` | Backend Docker deployment |
| `frontend/docker-compose.yml` | Frontend Docker deployment |
| `backend/app/core/rate_limiter.py` | Rate limiting configuration |
| `backend/app/core/cache.py` | Caching configuration |
