# Configuration Guide

## Overview

AgentHub configuration is primarily managed through environment variable files. This document details all configuration items.

---

## Quick Configuration

### Backend Configuration

```bash
cd backend
cp .env.example .env
# Edit .env file, fill in your API Keys
```

### Frontend Configuration

```bash
cd frontend
cp .env.example .env
# Edit .env file, set backend address
```

---

## Complete Backend Configuration Description

### Application Mode

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `MODE` | `prod` | Application mode: `prod` (production) or `dev` (development, enables hot reload) |
| `HOST` | `0.0.0.0` | Web server listening address |
| `PORT` | `8080` | Web server port |

### Database Configuration (First Layer Abstraction)

AgentHub adopts a two-layer database abstraction architecture. The first layer switches between SQLite and PostgreSQL through `DATABASE_TYPE`, with zero business code changes.

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `DATABASE_TYPE` | `sqlite` | Database type: `sqlite` (zero-dependency) or `postgres` (production-grade) |

#### SQLite Configuration (DATABASE_TYPE=sqlite)

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `SQLITE_DATABASE_PATH` | `./data/agenthub.db` | SQLite database file path |

**Note**: Under Docker environment, this is overridden to `/app/data/agenthub.db` (mounted via volume).

#### PostgreSQL Configuration (DATABASE_TYPE=postgres)

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `POSTGRES_USER` | `langchain` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `langgraph` | PostgreSQL password |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host address |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `agentdb` | PostgreSQL database name |

**Note**: Under Docker Compose environment, `POSTGRES_HOST` should be set to the service name `postgres`, not `localhost`.

### Vector Database Configuration (Second Layer Abstraction)

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `VECTORSTORE_TYPE` | `sqlite_vec` | Vector storage type: `sqlite_vec` (embedded) or `qdrant` (independent service) |

#### SQLite Vec Configuration (VECTORSTORE_TYPE=sqlite_vec)

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `SQLITE_VEC_DATABASE_PATH` | `./data/agenthub_vec.db` | SQLite vector database file path |

#### Qdrant Configuration (VECTORSTORE_TYPE=qdrant)

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `QDRANT_HOST` | `localhost` | Qdrant service host address |
| `QDRANT_PORT` | `6333` | Qdrant service port |
| `QDRANT_COLLECTION` | `agentic_rag_survey` | Qdrant collection name |

### Model Provider Configuration

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `MODEL_PROVIDERS` | `["dashscope", "zai"]` | Model providers displayed in frontend dropdown list |

**Supported Providers**:
- `openai`: OpenAI (GPT-4o, GPT-4 Turbo, etc.)
- `anthropic`: Anthropic (Claude 3, Claude 3.5 Sonnet, Opus)
- `groq`: Groq (fast inference LLM)
- `openrouter`: OpenRouter (supports 100+ models)
- `dashscope`: Alibaba Cloud Tongyi Qianwen
- `zhipuai`: Zhipu AI (GLM series)
- `zai`: ByteDance Doubao

**Note**: LLM Provider API Keys are configured in the frontend Web UI (Settings → Model Providers), no need to configure in this file.

### LangSmith Tracing Configuration (Optional)

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `LANGCHAIN_TRACING_V2` | `false` | Whether to enable LangSmith tracing |
| `LANGCHAIN_PROJECT` | `"AgentHub"` | LangSmith project name |
| `LANGCHAIN_ENDPOINT` | `https://api.smith.langchain.com` | LangSmith API endpoint |
| `LANGCHAIN_API_KEY` | Empty | LangSmith API Key |

When enabled, you can view all LLM calls, tool calls, and Agent execution chains on the LangSmith platform, facilitating debugging and performance analysis.

### Tool API Keys (Required)

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `TAVILY_API_KEY` | Empty | **Required** Tavily search API Key (web search functionality) |
| `AMAP_KEY` | Empty | **Required** Amap (Gaode Map) API Key (navigation planning Agent) |

**How to obtain**:
- Tavily API Key: https://tavily.com/
- Amap API Key: https://lbs.amap.com/api/webservice/guide/create-project/get-key

### API Key Encryption Configuration

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `API_KEY_ENCRYPTION_KEY` | `AgentHub2026SecureKey!@#$%` | API Keys encryption key stored in the database |

**Important**:
- Must be consistent with the frontend's `VITE_API_KEY_ENCRYPTION_KEY`
- Default key length is 32 characters (256-bit AES key)
- **Be sure to modify this key in production environments**!
- Changing the key will result in all previously stored API Keys being undecryptable

---

## Complete Frontend Configuration Description

| Configuration Item | Default Value | Description |
|-------------------|---------------|-------------|
| `VITE_API_BASE_URL` | `http://localhost:8080` | Backend API base address |
| `VITE_APP_TITLE` | `AgentHub` | Application display name |
| `VITE_API_KEY_ENCRYPTION_KEY` | `AgentHub2026SecureKey!@#$%` | Encryption key consistent with backend |

**Note**: Under Docker environment, `VITE_API_BASE_URL` can be overridden via environment variables:

```yaml
frontend:
  environment:
    - VITE_API_BASE_URL=http://backend:8080
```

---

## Configuration Mode Switching

### Switching from SQLite Mode to PostgreSQL Mode

1. Modify `backend/.env`:

```bash
# Database
DATABASE_TYPE=postgres
POSTGRES_HOST=postgres  # Use service name for Docker environment
POSTGRES_PORT=5432
POSTGRES_USER=langchain
POSTGRES_PASSWORD=your-password
POSTGRES_DB=agentdb

# Vector storage
VECTORSTORE_TYPE=qdrant
QDRANT_HOST=qdrant
QDRANT_PORT=6333
```

2. Restart containers:

```bash
docker compose up -d
```

### Data Migration Notes

When switching database types:
- SQLite → PostgreSQL: **Data will not be automatically migrated**, need to manually export and import
- PostgreSQL → SQLite: **Data will not be automatically migrated**, need to manually export and import

**Recommendation**: Export conversation history before switching, then recreate sessions after switching.

---

## Production Environment Configuration Checklist

Before deploying to production environment, ensure the following items are configured:

| Check Item | Requirement |
|-----------|-------------|
| `DATABASE_TYPE` | Set to `postgres` |
| `VECTORSTORE_TYPE` | Set to `qdrant` |
| `POSTGRES_PASSWORD` | Use strong password |
| `API_KEY_ENCRYPTION_KEY` | Modify to custom key (32 characters) |
| `LANGCHAIN_TRACING_V2` | Enable as needed |
| `TAVILY_API_KEY` | Configured |
| `AMAP_KEY` | Configured |
| Frontend `VITE_API_BASE_URL` | Points to correct backend address |

---

## Common Issues

### Q: How does configuration take effect after modification?

A: Docker environment requires restarting containers:

```bash
docker compose restart backend
```

Local development environment has automatic hot reload (`MODE=dev`).

### Q: Where does the SQLite database file exist?

A:
- Local development: `backend/data/agenthub.db`
- Docker: Inside container `/app/data/agenthub.db`, mounted to host `./backend/data/` via volume

### Q: How to backup configuration?

A: Include `.env` files in version control (but **do not commit files containing real API Keys**). It is recommended to maintain `.env.production` templates.

### Q: Backend cannot connect to database in Docker?

A: Check if `POSTGRES_HOST` is the Docker Compose service name `postgres`, not `localhost`. In Docker containers, `localhost` points to the container itself.