# Technical Context

## Technology Stack

### Backend

| Technology | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.11+ | Primary language |
| **FastAPI** | 0.121.2 | Async web framework |
| **LangChain** | 1.3.1 | LLM application framework |
| **LangGraph** | 1.2.0 | Agent orchestration |
| **langchain-litellm** | 0.6.6 | LLM provider abstraction |
| **langgraph-checkpoint-postgres** | 3.1.0 | State persistence |
| **langchain-postgres** | 0.0.17 | Vector store |
| **langchain-tavily** | 0.2.18 | Web search tool |
| **asyncpg** | 0.31.0 | Async PostgreSQL driver |
| **psycopg-binary** | 3.3.2 | Sync PostgreSQL driver |
| **cryptography** | 46.0.7 | API key encryption |
| **python-jose** | 3.4.0 | JWT handling |
| **passlib** | 1.7.4 | Password hashing |
| **websockets** | 15.0.1 | WebSocket support |
| **uvicorn** | 0.38.0 | ASGI server |

### Frontend

| Technology | Version | Purpose |
|------------|---------|---------|
| **React** | 19.2.0 | UI framework |
| **TypeScript** | 5.9.3 | Type-safe JavaScript |
| **Vite** | 8.0.10 | Build tool |
| **Tailwind CSS** | 4.2.1 | Styling |
| **Radix UI** | 1.4.3 | Component primitives |
| **TipTap** | 3.20.0 | Rich text editor |
| **react-router-dom** | 7.14.2 | Client-side routing |
| **react-markdown** | 10.1.0 | Markdown rendering |
| **Shiki** | 3.22.0 | Code syntax highlighting |
| **Recharts** | 3.8.1 | Charts library |
| **Lucide React** | 0.575.0 | Icon library |

### Infrastructure

| Technology | Version | Purpose |
|------------|---------|---------|
| **PostgreSQL** | 18 | Primary database |
| **pgvector** | 0.8.2 | Vector extension |
| **Docker** | 20.10+ | Containerization |
| **Docker Compose** | v2+ | Multi-container orchestration |
| **Nginx** | - | Reverse proxy / static serving |

## Development Setup

### Prerequisites

- Docker 20.10+
- Docker Compose v2+
- Node.js 18+ (for local frontend development)
- Python 3.11+ (for local backend development)

### Required Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SYSTEM_DEFAULT_LLM_MODEL` | Default model (e.g., `openai/gpt-4o`) | ✅ |
| `SYSTEM_DEFAULT_LLM_API_KEY` | Model API Key | ✅ |
| `API_KEY_ENCRYPTION_KEY` | AES-256 encryption key (32 chars) | ✅ |
| `JWT_SECRET_KEY` | JWT signing key | ✅ |
| `POSTGRES_USER` | PostgreSQL username | ✅ |
| `POSTGRES_PASSWORD` | PostgreSQL password | ✅ |
| `POSTGRES_HOST` | PostgreSQL host | ✅ |
| `POSTGRES_PORT` | PostgreSQL port | ✅ |
| `POSTGRES_DB` | Database name | ✅ |
| `TAVILY_API_KEY` | Tavily search API key | ❌ |
| `LANGCHAIN_API_KEY` | LangSmith tracing | ❌ |

### Local Development

```bash
# Clone repository
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# Setup environment
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
# Edit backend/.env with your values

# Start with Docker
docker compose up -d

# Access
# Frontend: http://localhost
# Backend API: http://localhost:8080/docs
```

## Technical Constraints

### Database

- **PostgreSQL only** — No SQLite or MySQL support
- **pgvector required** — For vector embeddings and semantic search
- **Connection pooling** — Min 2, Max 10 connections per pool

### Authentication

- **JWT-based** — HTTP-only cookies for web, token for API
- **Token expiry** — 7 days default
- **HTTPS required** — JWT cookies are `Secure` by default (disable for dev)

### LLM Integration

- **LiteLLM Router** — All LLM calls go through LiteLLM
- **Model format** — `provider/model-id` (e.g., `openai/gpt-4o`)
- **Fallback/retry** — Handled by LiteLLM Router, not application code

### Agent Execution

- **Timeouts**:
  - Invoke: 120s default
  - Stream: 300s default
  - LLM call: 60s default
- **Summarization**: Triggered at 4000 tokens, keeps 20 messages

## Dependencies

### Backend Key Dependencies

```
fastapi==0.121.2
langchain==1.3.1
langchain-community==0.4.1
langchain-litellm==0.6.6
langchain-postgres==0.0.17
langchain-tavily==0.2.18
langgraph-checkpoint-postgres==3.1.0
langgraph==1.2.0
langsmith==0.8.5
asyncpg==0.31.0
psycopg-binary==3.3.2
uvicorn==0.38.0
cryptography==46.0.7
websockets==15.0.1
python-jose[cryptography]==3.4.0
passlib[bcrypt]==1.7.4
```

### Frontend Key Dependencies

```json
{
  "react": "^19.2.0",
  "react-dom": "^19.2.0",
  "react-router-dom": "^7.14.2",
  "@radix-ui/react-*": "various",
  "@tiptap/*": "^3.20.0",
  "tailwindcss": "^4.2.1",
  "vite": "^8.0.10",
  "typescript": "~5.9.3"
}
```

## Tool Usage Patterns

### LangSmith Tracing

- **Dev mode only** — Automatically disabled in production
- **Opt-in** — Set `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY`
- **Project-based** — Group traces by `LANGCHAIN_PROJECT`

### Docker Deployment

```yaml
# Three-container setup
services:
  db:        # PostgreSQL + pgvector
  backend:   # FastAPI application
  frontend:  # Nginx serving React + proxying API
```

### Logging

- **Format**: Console (dev) or JSON (prod)
- **Level**: INFO default, configurable via `LOG_LEVEL`
- **Request ID**: Injected via `RequestIdFilter` for tracing

## API Endpoints

### Authentication
- `POST /api/v1/auth/register` — User registration
- `POST /api/v1/auth/login` — User login
- `POST /api/v1/auth/logout` — User logout (clears JWT cookie)
- `POST /api/v1/auth/mock-login` — Mock user login (development)
- `GET /api/v1/auth/mock-users` — List mock users (development)
- `GET /api/v1/auth/status` — Check authentication status

### Chat
- `GET /api/v1/chat/conversations` — List conversations (user from JWT)
- `POST /api/v1/chat/conversations` — Create conversation
- `GET /api/v1/chat/conversations/{thread_id}` — Get conversation
- `DELETE /api/v1/chat/conversations/{thread_id}` — Delete conversation
- `GET /api/v1/chat/conversations/{thread_id}/info` — Get conversation info
- `PATCH /api/v1/chat/conversations/{thread_id}/title` — Update title
- `POST /api/v1/chat/conversations/{thread_id}/title/generate` — Generate title
- `GET /api/v1/chat/history/{thread_id}` — Get chat history
- `POST /api/v1/chat/run` — SSE streaming chat
- `GET /api/v1/chat/stats` — Get usage statistics

### Models
- `GET /api/v1/models` — List available models
- `GET /api/v1/models/{model_id}` — Get model config
- `PUT /api/v1/models/{model_id}` — Update model config

### Traces
- `GET /api/v1/traces/{thread_id}/steps` — Get conversation steps/traces

### WeChat
- `GET /api/v1/weixin/ws` — WebSocket endpoint for WeChat integration
