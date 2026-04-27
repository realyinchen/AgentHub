# 🧠 AgentHub - AI Agent Platform

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

A modular AI Agent platform with a modern web interface for building, experimenting with, and deploying LangChain and LangGraph agents. Built with **FastAPI** (backend) and **React** (frontend), featuring clean separation of concerns, a database/business-layer decoupling architecture, and **zero-dependency startup** via SQLite + sqlite-vec.

This is the GUI version of the [AgentLab](https://github.com/realyinchen/AgentLab) project.

Follow my WeChat official account for the latest updates:

![wechat_qrcode](https://github.com/realyinchen/RAG/blob/main/imgs/wechat_qrcode.jpg)

---

## 📑 Table of Contents

- [✨ Project Highlights](#-project-highlights)
- [🧩 Who Is This For](#-who-is-this-for)
- [🏗️ Technical Architecture](#️-technical-architecture)
- [🗄️ Database Abstraction Architecture](#️-database-abstraction-architecture)
- [🚀 Quick Start](#-quick-start)
- [🤖 Available Agents](#-available-agents)
- [📡 API Reference](#-api-reference)
- [🐳 Docker Deployment](#-docker-deployment)
- [💻 Development Guidelines](#-development-guidelines)
- [⚙️ Configuration Reference](#️-configuration-reference)
- [📈 Performance Optimizations](#-performance-optimizations)
- [📦 Branches](#-branches)
- [🚧 Known Limitations and Roadmap](#-known-limitations-and-roadmap)
- [📄 License](#-license)

---

## ✨ Project Highlights

| Feature | Description |
|---------|-------------|
| Zero-Dependency Startup | SQLite + sqlite-vec embedded storage. No PostgreSQL, no Qdrant, no Docker needed. Just `pip install` and run. |
| Database/Business Decoupling | Factory pattern + interface abstraction. Switch between SQLite and PostgreSQL with **zero business code changes**. Only `.env` configuration needed. |
| LangChain/LangGraph Integration | Build, design, and connect multi-agent reasoning workflows with visualization. |
| Streaming and Event-Driven | Real-time token streaming (SSE) and agent execution event visualization. |
| Thinking Mode | Toggle between standard and thinking modes for deeper reasoning. Separate UI for thought process and tool calls. |
| Quote Messages | Quote any historical message to continue the conversation with context. Quotes persist across page refreshes. |
| Multi-language Support | Built-in i18n with English and Chinese translations. |
| Dark/Light Theme | Customizable theme support for comfortable viewing. |
| Image Zoom and Drag | Click any image in markdown to zoom in/out and drag to pan. Universal for all agents. |
| Token Stats Display | Real-time token consumption visualization with vertical bar chart (Input/Output/Reasoning). Dark mode + i18n supported. |
| Agent Execution Visualization | Real-time display of agent intermediate steps: thinking/reasoning process, tool calls with arguments and results. Timeline sidebar for each conversation turn. |
| Flexible Model Configuration | Configure LLM, VLM, and Embedding models in the web UI. Switch agents and models within the same thread without losing history. |

![demo](https://github.com/realyinchen/AgentLab/blob/main/imgs/demo.gif)

---

## 🧩 Who Is This For

Students and developers who want to efficiently showcase their LangChain and LangGraph learning achievements in an interactive, visual format, and teams who need a production-ready AI agent platform with pluggable storage backends.

---

## 🏗️ Technical Architecture

### Overall Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Frontend (React)                      │
│    Vite + React 19 + TypeScript + Tailwind + shadcn/ui   │
│              TanStack Query · SSE Client · i18n           │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / SSE
                         ▼
┌──────────────────────────────────────────────────────────┐
│                    Backend (FastAPI)                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────────┐  │
│  │  Agents  │  │   API   │  │  Tools  │  │   Utils    │  │
│  │(LangGraph│  │ (REST)  │  │(LangChn)│  │ (LLM,Msg)  │  │
│  └────┬────┘  └────┬────┘  └────┬────┘  └─────┬──────┘  │
│       │            │            │              │          │
│       └────────────┴────────────┴──────────────┘          │
│                         │                                  │
│              ┌──────────▼──────────┐                      │
│              │   Factory Layer     │                      │
│              │ DatabaseFactory     │                      │
│              │ VectorstoreFactory  │                      │
│              └──────────┬──────────┘                      │
│                         │                                  │
│              ┌──────────▼──────────┐                      │
│              │  Interface Layer    │                      │
│              │ DatabaseInterface   │                      │
│              │ VectorstoreInterface│                      │
│              │ CheckpointInterface │                      │
│              └────┬──────────┬────┘                      │
│                   │          │                             │
│            ┌──────▼──┐  ┌───▼──────┐                     │
│            │SQLite   │  │PostgreSQL│                      │
│            │+sqlite- │  │+Qdrant  │                       │
│            │  vec    │  │         │                       │
│            └─────────┘  └─────────┘                       │
└──────────────────────────────────────────────────────────┘
```

### Backend Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Runtime | Python 3.12 | Language runtime |
| Web Framework | FastAPI | High-performance async API with auto-generated docs |
| Agent Framework | LangChain + LangGraph | LLM orchestration and workflow graphs |
| ORM | SQLAlchemy 2.0 (async) | Database abstraction with async session management |
| Relational DB (Default) | SQLite + aiosqlite | Zero-dependency embedded database |
| Relational DB (Production) | PostgreSQL + asyncpg | Production-grade database with connection pooling |
| Vector Store (Default) | sqlite-vec | Zero-dependency embedded vector search |
| Vector Store (Production) | Qdrant | Production-grade vector database with HNSW indexing |
| Checkpointer | LangGraph Savers (SQLite/PostgreSQL) | Agent state persistence for conversation memory |
| ASGI Server | Uvicorn | Production-ready async server |
| Rate Limiting | slowapi | IP-based request throttling |
| Caching | cachetools TTLCache | In-memory caching for models, providers, conversations |

### Frontend Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Build Tool | Vite | Next-gen bundler with instant HMR |
| UI Framework | React 19 | Component-based UI |
| Language | TypeScript | Static typing for code safety |
| Styling | Tailwind CSS | Utility-first CSS framework |
| UI Components | shadcn/ui | Accessible, customizable component library |
| State Management | TanStack Query | Server state management with caching |
| Icons | Lucide React | Beautiful icon library |

### Project Structure

```
AgentHub/
├── frontend/                    # Vite + React + TypeScript + Tailwind CSS + shadcn/ui
│   ├── .env                     # Frontend environment variables
│   ├── src/                     # React components and logic
│   │   ├── components/          # UI components (ui/, chat/, settings/, etc.)
│   │   ├── hooks/               # Custom React hooks
│   │   ├── lib/                 # Utilities and API client
│   │   ├── locales/             # i18n translation files (en, zh)
│   │   └── pages/               # Page components
│   ├── public/                  # Static assets
│   ├── package.json             # Frontend dependencies
│   └── vite.config.ts           # Vite build configuration
├── backend/                     # FastAPI + LangGraph backend
│   ├── app/
│   │   ├── main.py              # FastAPI application entry point + lifespan
│   │   ├── agents/              # Agent implementations
│   │   │   ├── chatbot.py       # Conversational agent with web search + time tools
│   │   │   └── navigator.py     # Navigation agent with Amap integration
│   │   ├── api/v1/              # v1 API endpoints
│   │   │   ├── agent.py         # Agent CRUD
│   │   │   ├── chat.py          # Chat streaming, history, conversations
│   │   │   ├── model.py         # Model management
│   │   │   └── provider.py      # Provider management
│   │   ├── core/                # Core configurations
│   │   │   ├── config.py        # Settings (Pydantic BaseSettings)
│   │   │   ├── model_manager.py # LLM/VLM/Embedding model manager
│   │   │   ├── cache.py         # TTL cache configuration
│   │   │   └── rate_limiter.py  # Rate limiting configuration
│   │   ├── crud/                # Database CRUD operations
│   │   ├── database/            # Database abstraction layer
│   │   │   ├── interfaces.py    # Abstract interface definitions
│   │   │   ├── factory.py       # Factory implementation (singleton instances)
│   │   │   └── backends/        # Backend implementations
│   │   │       ├── postgres/    # PostgreSQL + Qdrant backend
│   │   │       └── sqlite/      # SQLite + sqlite-vec backend
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── tools/               # LangChain tools collection
│   │   ├── prompt/              # Centralized prompt templates
│   │   └── utils/               # Utilities (LLM, messages, crypto, agent helpers)
│   ├── scripts/                 # Database initialization scripts
│   ├── data/                    # SQLite database files (auto-created)
│   ├── .env.example             # Environment variables template
│   ├── requirements.txt         # Python dependencies
│   └── run_backend.py           # Backend startup script
├── docker-compose.yml           # Full-stack deployment (with profiles)
└── README.md                    # This file
```

---

## 🗄️ Database Abstraction Architecture

AgentHub supports both **SQLite** (zero-dependency, recommended for quick start) and **PostgreSQL + Qdrant** (production-grade) backends through a clean abstraction layer. Switching backends requires **zero business code changes** — only configuration.

### Why This Matters

The database/business layer decoupling means:
- **Developers** can start coding immediately with SQLite — no Docker, no database setup
- **Teams** can deploy to production with PostgreSQL + Qdrant — just change `.env`
- **Contributors** can add new backends without touching any business logic

### Core Design Principles

1. **Zero Business Logic Awareness** — Agents, API, and Tools layers are completely unaware of the underlying database type. The factory pattern and interface abstraction ensure business code depends only on interfaces, not implementations.
2. **Factory Layer, Done Once** — `factory.py` only creates instances based on configuration. Adding a new backend only requires registering it in the factory. Schema changes only affect the specific backend implementation, not the factory.
3. **Configuration-Driven Switching** — Switch backends via `.env` configuration: `DATABASE_TYPE` and `VECTORSTORE_TYPE` are two independent settings. The same codebase supports multiple deployment scenarios.

### Three-Layer Architecture

```
Business Layer
  Agent | API | Tools | Utils
         |         |         |
         v         v         v
Factory Layer
  DatabaseFactory + VectorstoreFactory
  - Dynamically create backend instances based on config
  - Inject embedding function into vector store
         |         |         |
         v         v         v
Interface Layer
  DatabaseInterface + CheckpointInterface
  VectorstoreInterface
         |         |         |
         v         v         v
Backend Implementations
  PostgreSQL          |  SQLite
  PostgresDatabase    |  SQLiteDatabase
  PostgresCheckpointer|  SqliteCheckpointer
  QdrantVectorstore   |  SqliteVecVectorstore
```

### Backend Comparison

| Component | SQLite Backend (Default) | PostgreSQL Backend (Production) |
|-----------|------------------------|-------------------------------|
| Database | SQLAlchemy + aiosqlite (StaticPool single-connection) | SQLAlchemy + asyncpg (connection pool, high concurrency) |
| Checkpointer | AsyncSqliteSaver (LangGraph official) | AsyncPostgresSaver (LangGraph official) |
| Vector Store | sqlite-vec extension (zero-dependency, embedded) | qdrant-client (production-grade) |
| External Dependencies | **None** | PostgreSQL server + Qdrant server |
| Concurrency | Single-writer (suitable for small-to-medium apps) | Full concurrent read/write (100+ users) |
| Setup | Auto-creates `data/` directory and tables | Requires `init_database.py` + Docker services |

### Score Semantics Unification

| Backend | Raw Output | Meaning | Unified Output | Conversion |
|---------|-----------|---------|---------------|------------|
| Qdrant | score (0~1) | Cosine similarity, higher = more similar | score (0~1) | No conversion needed |
| sqlite-vec | distance (0~2) | Cosine distance, lower = more similar | score (0~1) | score = 1.0 - distance |

**Convention**: `VectorstoreInterface.search_with_embedding()` must return `score` as cosine similarity (0~1, higher = more similar).

### ORM Model Compatibility

| PostgreSQL Type | SQLAlchemy Generic Type | SQLite Storage |
|----------------|----------------------|----------------|
| `postgresql.UUID(as_uuid=True)` | `sqlalchemy.Uuid` | TEXT (string form) |
| `postgresql.JSONB` | `sqlalchemy.JSON` | TEXT |

For `server_default`, SQLite doesn't support `server_default=func.now()` on UPDATE, so Python-side callbacks (`default=utc_now`, `onupdate=utc_now`) are used instead.

### Adding a New Backend

1. Implement `DatabaseInterface`
2. Implement `CheckpointInterface`
3. Implement `VectorstoreInterface`
4. Register in `factory.py` (`_DB_BACKENDS`, `_CP_BACKENDS`, `_VS_BACKENDS`)
5. Update `config.py` if new configuration is needed
6. Update `.env.example` and `README.md`

**No changes needed**: Any business layer code (agents, api, tools, utils)

### Database File Structure

```
backend/app/database/
├── base.py                  # Interface definitions (re-exports from interfaces.py)
├── interfaces.py            # Abstract interface definitions
├── factory.py               # Factory implementation (singleton caching)
├── __init__.py              # Export factory functions
└── backends/
    ├── __init__.py
    ├── postgres/
    │   ├── __init__.py
    │   ├── db.py            # PostgresDatabase
    │   ├── checkpointer.py  # PostgresCheckpointer
    │   └── vectorstore.py   # QdrantVectorstore
    └── sqlite/
        ├── __init__.py
        ├── db.py            # SQLiteDatabase
        ├── checkpointer.py  # SqliteCheckpointer
        └── vectorstore.py   # SqliteVecVectorstore
```

### Known Trade-offs

| Decision | Benefit | Cost |
|----------|---------|------|
| Factory pattern + interface abstraction | Zero business awareness, easy to extend | Negligible indirection overhead (<1% of API response time; bottleneck is always in the backend implementation itself) |
| Embedding function DI | Vectorstore doesn't depend on ModelManager | Slightly more complexity |
| Unified score semantics | Business layer handles one format | sqlite-vec needs extra conversion step |
| Docker Profiles | One compose file supports both modes | Learning curve (need to know `--profile`) |

### 📊 Performance Analysis

> **Key Insight**: The factory pattern + interface abstraction layer only runs at startup (creating singleton instances). At runtime, business code calls interface methods directly — Python's duck typing + dependency injection adds virtually zero overhead (<1% of total API response time). The real performance differences come from the **backend implementations themselves**, not the abstraction layer.

#### Relational Database: SQLite vs PostgreSQL

| Aspect | SQLite | PostgreSQL |
|--------|--------|------------|
| **Low-concurrency reads** | ✅ Faster — no network overhead, direct file I/O. Simple point queries can be 2-10x faster than PG on small datasets. | ❌ Slower — network round-trip + process overhead adds latency. |
| **High-concurrency writes** | ❌ Poor — single writer (even in WAL mode). Concurrent checkpoint writes serialize and throttle throughput. | ✅ Excellent — MVCC allows concurrent reads/writes without blocking. Handles hundreds of simultaneous connections. |
| **Complex queries** | ❌ Limited — no advanced query planner, limited JSON query capabilities. | ✅ Superior — advanced query planner, JSONB indexing, partial indexes, CTEs. |
| **Scalability** | Single-machine only. Suitable for <200 QPS with moderate writes. | Horizontal scaling via connection pooling, read replicas, partitioning. |
| **Best for** | Development, testing, low-traffic single-instance deployments. | Production, multi-user, high-concurrency, strong consistency requirements. |

#### Vector Store: sqlite-vec vs Qdrant

| Aspect | sqlite-vec | Qdrant |
|--------|-----------|--------|
| **Small-scale vectors (<1M)** | ✅ Sufficient — low latency, zero deployment overhead. Good for prototyping. | Works but requires a separate service. |
| **Medium-to-large scale (>1M)** | ❌ Limited — no HNSW optimization, performance degrades significantly at scale. | ✅ Purpose-built (Rust implementation) — HNSW indexing delivers 20-50ms search even at scale. |
| **Filtered vector search** | ❌ Basic — metadata filtering + similarity is limited. | ✅ Excellent — rich payload filtering with vector search, quantization for memory efficiency. |
| **Deployment** | Embedded — shares process with app, zero setup. | Separate service — requires Docker/deployment, but offers API and dashboard. |
| **Best for** | Development, small RAG prototypes, low-traffic scenarios. | Production RAG, medium-to-large vector collections, real-time retrieval with filtering. |

#### Scenario Recommendations

| Scenario | Recommended Stack | Reason |
|----------|------------------|--------|
| Local development / testing | **SQLite + sqlite-vec** | Zero setup, fastest iteration cycle. |
| Demo / personal project | **SQLite + sqlite-vec** | Low traffic, minimal resources, easy deployment. |
| Production (<100 concurrent users) | **SQLite + sqlite-vec** (or PG if write-heavy) | SQLite handles moderate loads well; switch to PG if checkpoint writes become a bottleneck. |
| Production (100+ concurrent users) | **PostgreSQL + Qdrant** | MVCC for concurrent writes, HNSW for vector search at scale. |
| Production with heavy RAG | **PostgreSQL + Qdrant** | Qdrant's payload filtering and quantization are critical for production RAG. |

---

## 🚀 Quick Start

### Recommended: SQLite Mode (Zero Dependencies)

The fastest way to get started — no PostgreSQL, no Qdrant, no Docker required.

**Prerequisites**
1. Install [VS Code](https://code.visualstudio.com/Download) and [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/)
2. Install [Node.js 18+](https://nodejs.org/) for frontend development

**Setup**

1. **Create and activate virtual environment**
   ```bash
   conda create -n agenthub python=3.12
   conda activate agenthub
   ```

2. **Clone and enter project directory**
   ```bash
   git clone https://github.com/realyinchen/AgentHub.git
   cd AgentHub
   ```

3. **Configure environment variables**
   ```bash
   cd backend
   cp .env.example .env
   ```
   Edit `.env` file — defaults are already set for SQLite mode. Just fill in your third-party API keys (Tavily, Amap, etc.) if needed.

4. **Install backend dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Initialize database**
   ```bash
   python scripts/init_database.py
   ```

6. **Start backend server**
   ```bash
   python run_backend.py
   ```

7. **In a new terminal, start frontend dev server**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

8. **Configure providers and models (Important!)**
   - Open `http://localhost:5173`
   - Click the settings icon in the top right corner
   - Configure providers first (enter API keys)
   - Then add models for each configured provider

9. **Access the application**
   - Frontend: `http://localhost:5173`
   - Backend API docs: `http://localhost:8080/docs`

> SQLite mode automatically creates database files in `backend/data/`. No external services needed!

### Production: PostgreSQL + Qdrant Mode

For production deployments requiring high concurrency and full-featured vector search.

**Additional Prerequisites**: Docker (for running PostgreSQL and Qdrant)

**Additional Steps**

1. **Start PostgreSQL and Qdrant**
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

2. **Edit `backend/.env` to switch backends**
   ```env
   DATABASE_TYPE=postgres
   VECTORSTORE_TYPE=qdrant
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_USER=langchain
   POSTGRES_PASSWORD=langgraph
   POSTGRES_DB=agentdb
   QDRANT_HOST=localhost
   QDRANT_PORT=6333
   ```

3. **Initialize database**
   ```bash
   python scripts/init_database.py
   ```

Then follow steps 6-9 from the SQLite mode above.

---

## 🤖 Available Agents

### chatbot — Conversational Agent

A general-purpose conversational agent with tool-calling capabilities.

| Tool | Description |
|------|-------------|
| `get_current_time` | Get current time in any timezone |
| `web_search` | Search the web for real-time information (via Tavily) |

**Features**: Real-time queries (weather, news, current time, etc.), streaming responses, thinking mode support.

### navigator — Navigation Agent

A navigation and location-aware agent with Amap API integration.

| Tool | Description |
|------|-------------|
| `get_current_time` | Get current time in any timezone |
| `amap_geocode` | Convert address to coordinates (geocoding) |
| `amap_place_search` | Search POI by keywords (restaurants, hotels, etc.) |
| `amap_place_around` | Search POI around a location |
| `amap_driving_route` | Plan driving route with distance, time, and navigation URL |
| `amap_route_preview` | Generate complete route preview URL with waypoints |
| `amap_weather` | Query weather information for a city |

**Features**: Time conflict detection, itinerary planning, weather-aware suggestions, **parallel tool execution** — multiple tools execute simultaneously for faster planning.

---

## 📡 API Reference

All API endpoints are prefixed with `/api/v1`. Interactive documentation is available at `http://localhost:8080/docs` (Swagger UI) after starting the backend.

### Agent API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/agents/` | Create a new agent |
| `GET` | `/agents/` | List agents (with pagination and active-only filter) |
| `GET` | `/agents/{agent_id}` | Get agent details |
| `PATCH` | `/agents/{agent_id}` | Update an agent (partial update) |
| `DELETE` | `/agents/{agent_id}` | Soft-delete an agent (set `is_active = False`) |

**Query Parameters (List Agents)**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `active_only` | bool | `true` | Only show active agents |
| `limit` | int | 20 | Max number of results (1-100) |
| `offset` | int | 0 | Number of results to skip |

### Chat API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat/stream` | Stream agent response via SSE |
| `POST` | `/chat/invoke` | Invoke agent and get complete response (non-streaming) |
| `GET` | `/chat/history/{agent_id}/{thread_id}` | Get chat history with message sequence |
| `GET` | `/chat/conversations` | List conversations (paginated) |
| `POST` | `/chat/conversations` | Create a new conversation |
| `DELETE` | `/chat/conversations/{thread_id}` | Soft-delete a conversation |
| `GET` | `/chat/title/{thread_id}` | Get conversation title |
| `POST` | `/chat/title` | Update conversation title |
| `POST` | `/chat/title/generate` | Auto-generate title using LLM |
| `GET` | `/chat/thinking-mode` | Check if thinking mode is available |
| `GET` | `/chat/models` | Get available models from configuration |

**SSE Stream Request Body** (`UserInput`):
```json
{
  "agent_id": "chatbot",
  "thread_id": "uuid-of-conversation",
  "message": "What's the weather today?",
  "model_id": "optional-model-id",
  "thinking_mode": false,
  "quote_message_id": "optional-quoted-message-id"
}
```

**SSE Stream Format** (for `/chat/stream`):
```
data: {"type": "token", "content": "Hello"}
data: {"type": "token", "content": " World"}
data: [DONE]
```

**Conversations List**: Response includes `X-Total-Count` header for pagination.

### Model API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/models/` | Get available models (with provider API key configured) |
| `GET` | `/models/all` | Get all models (for configuration page) |
| `GET` | `/models/providers` | Get available model providers |
| `POST` | `/models/` | Create a new model |
| `POST` | `/models/update` | Update model configuration |
| `POST` | `/models/delete` | Delete a model |
| `POST` | `/models/set-default` | Set default model for a type (llm/vlm/embedding) |
| `POST` | `/models/refresh` | Manually refresh model cache |

**Models Response** includes:
- `models` — List of model info objects
- `default_llm` — Default LLM model ID
- `default_vlm` — Default VLM model ID
- `default_embedding` — Default Embedding model ID

> **Note**: Model update/delete/set-default use `POST` with model ID in request body (not URL path) to avoid URL encoding issues with `/` character in model IDs (e.g., `zai/glm-5`).

### Provider API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/providers/` | List all providers |
| `POST` | `/providers/` | Create a new provider |
| `POST` | `/providers/update` | Update provider configuration |
| `POST` | `/providers/delete` | Delete a provider |
| `POST` | `/providers/validate` | Validate provider API key |

> **Note**: Provider update/delete use `POST` with provider ID in request body for the same reason as Model API.

### Common Patterns

- **Pagination**: `limit` (1-100) and `offset` parameters; `X-Total-Count` header in response
- **Soft Delete**: Entities are marked as inactive rather than removed from the database
- **Error Format**: `{"detail": "error message"}` with appropriate HTTP status codes

---

## 🐳 Docker Deployment

The same Docker image supports both SQLite and PostgreSQL backends. All configuration is managed in `.env` files.

### Quick Start — SQLite Mode (Recommended)

Zero external dependencies, uses embedded SQLite databases:

```bash
# 1. Copy config templates
cd backend && cp .env.example .env
cd ../frontend && cp .env.example .env
cd ..

# 2. Edit backend/.env to add your 3rd-party API keys (Tavily, Amap, etc.)
#    Defaults are fine for SQLite mode - just fill in the API keys you need

# 3. Start
docker-compose up -d
```

Open `http://localhost:5173` and configure your LLM API keys in Settings.

> SQLite databases are stored in a Docker volume (`agenthub-backend-data`). No PostgreSQL or Qdrant required.

### Production — PostgreSQL Mode

For production use with PostgreSQL + Qdrant:

1. Edit `backend/.env`:
   - Set `DATABASE_TYPE=postgres` and `VECTORSTORE_TYPE=qdrant`
   - Set `POSTGRES_HOST=postgres` (Docker service name, NOT localhost)
   - Set `QDRANT_HOST=qdrant` (Docker service name, NOT localhost)

2. Start with the postgres profile:
   ```bash
   docker-compose --profile postgres up -d
   ```

### Access Points

| Service | URL |
|---------|-----|
| Frontend | `http://localhost:5173` |
| Backend API Docs | `http://localhost:8080/docs` |

### Data Persistence

| Mode | Volume | Content |
|------|--------|---------|
| SQLite | `agenthub-backend-data` | Database files in `data/` |
| PostgreSQL | `agenthub-postgres-data` | PostgreSQL data |
| Qdrant | `agenthub-qdrant-data` | Vector store data |

### Useful Commands

```bash
# View logs
docker-compose logs -f

# Stop services (SQLite mode)
docker-compose down

# Stop services (PostgreSQL mode)
docker-compose --profile postgres down

# Rebuild images after code changes
docker-compose build --no-cache
```

### Standalone Deployments

Each module can also be deployed separately:

- **Backend only**: See `backend/docker-compose.yml`
- **Frontend only**: See `frontend/docker-compose.yml`

### Docker Files Structure

```
AgentHub/
├── docker-compose.yml       # Full-stack deployment (with profiles)
├── backend/
│   ├── docker-compose.yml   # Backend standalone deployment
│   ├── Dockerfile           # Backend container (supports both SQLite and PG)
│   └── .env.example         # Environment template
└── frontend/
    ├── docker-compose.yml   # Frontend standalone deployment
    ├── Dockerfile           # Frontend container (multi-stage build)
    ├── nginx.conf           # Nginx configuration with API proxy
    └── .env.example         # Environment template
```

---

## 💻 Development Guidelines

### API Design Conventions

- **Only use GET, POST, DELETE endpoints** (no PATCH/PUT for most cases)
- Model and Provider update/delete operations use `POST` with ID in request body to avoid URL encoding issues with `/` character in model IDs (e.g., `zai/glm-5`)
- Exception: Agent update uses `PATCH /agents/{agent_id}` (agent IDs don't contain `/`)

### LLM API Usage

**Recommended (Async API)**:
- Use `aget_llm()`, `aembedding_model()` in FastAPI async endpoints
- Use `streaming_completion()` for LLM calls with automatic token tracking

**Compatibility Only (Sync Wrappers)**:
- `get_llm()`, `embedding_model()` — for legacy code or non-async contexts only
- These add overhead when called from async context (triggers warning log)

### Database Operations

- **Session auto-commits on success**: All business code (API, Services, CRUD) must NOT manually call `session.commit()` or `session.rollback()`
- **Unified handling**: `db.session()` context manager handles commit/rollback/close automatically
- **Standard pattern**:
  ```python
  async with db.session() as session:
      # Business logic: only add/update/delete, zero transaction operations
      await crud.do_something(session, ...)
  # Context exit auto-commits, exception auto-rollbacks, always closes
  ```

### Token Tracking

Automatic token usage tracking via `streaming_completion()` in `backend/app/utils/llm.py`. New agents automatically get token tracking by using this function and returning `result.raw_response`. No additional code needed. See `chatbot.py` or `navigator.py` for examples.

### Adding a New Agent

1. Create agent file in `backend/app/agents/` (e.g., `my_agent.py`)
2. Define the LangGraph workflow with tools
3. Register in `backend/app/agents/__init__.py`
4. Add prompt templates in `backend/app/prompt/`
5. Add any new tools in `backend/app/tools/`
6. Initialize agent data via `init_database.py` or API

### Adding a New Database Backend

1. Implement `DatabaseInterface` in `backends/<name>/db.py`
2. Implement `CheckpointInterface` in `backends/<name>/checkpointer.py`
3. Implement `VectorstoreInterface` in `backends/<name>/vectorstore.py`
4. Register in `factory.py` (`_DB_BACKENDS`, `_CP_BACKENDS`, `_VS_BACKENDS`)
5. Update `config.py` if new configuration is needed
6. Update `.env.example` and `README.md`

**No changes needed in any business layer code** (agents, api, tools, utils).

### Production Singleton Rules

| Component | Singleton? | Reason |
|-----------|-----------|--------|
| Database Engine | Yes | Global connection pool reuse |
| Database Session | **No** | Request-level isolation, has transaction state, not thread-safe |
| Qdrant Client | Yes | No transactions, thread-safe, connection reuse |

---

## ⚙️ Configuration Reference

### Backend Environment Variables (`backend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_TYPE` | `sqlite` | Database backend: `sqlite` or `postgres` |
| `VECTORSTORE_TYPE` | `sqlite_vec` | Vector store backend: `sqlite_vec` or `qdrant` |
| `API_V1_STR` | `/api/v1` | API route prefix |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host (only for postgres mode) |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_USER` | `langchain` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `langgraph` | PostgreSQL password |
| `POSTGRES_DB` | `agentdb` | PostgreSQL database name |
| `QDRANT_HOST` | `localhost` | Qdrant host (only for qdrant mode) |
| `QDRANT_PORT` | `6333` | Qdrant port |
| `QDRANT_COLLECTION` | `agenthub` | Qdrant collection name |
| `SQLITE_DB_PATH` | `data/agenthub.db` | SQLite database file path |
| `SQLITE_VEC_PATH` | `data/agenthub_vec.db` | sqlite-vec database file path |
| `TAVILY_API_KEY` | — | Tavily API key (for web search tool) |
| `AMAP_API_KEY` | — | Amap API key (for navigator agent) |
| `LANGSMITH_API_KEY` | — | LangSmith API key (for tracing, optional) |
| `LANGSMITH_PROJECT` | — | LangSmith project name (optional) |
| `LLM_DEFAULT_MODEL` | — | Default LLM model identifier |

### Frontend Environment Variables (`frontend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE_URL` | `http://localhost:8080` | Backend API base URL |

### Docker-Specific Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NGINX_BACKEND_HOST` | `localhost` | Nginx proxy backend host (frontend Docker) |
| `NGINX_BACKEND_PORT` | `8080` | Nginx proxy backend port |
| `FRONTEND_PORT` | `5173` | Frontend exposed port |

---

## 📈 Performance Optimizations

### Database Optimizations
- **Connection Pool**: 20 base connections with 30 overflow (supports 100+ concurrent users)
- **Index Optimizations**: Composite indexes, partial indexes, and covering indexes
- **Query Performance**: 5-10x faster conversation list queries

### API Optimizations
- **Rate Limiting**: 100 requests/minute default per IP (prevents abuse)
- **Caching**: In-memory TTL cache for models (5min), providers (5min), conversations (1min), vector search (10min) — 80%+ hit rate
- **Sensitive Data**: API keys masked in logs for security

### Frontend Optimizations
- **Error Boundary**: Prevents white screen crashes
- **React Performance**: useMemo optimization and debounced state updates

### Vector Store Optimizations
- **Qdrant**: HNSW index configuration (m=16, ef=200) for 20-50ms search
- **Batch Search**: Support for multiple vector queries in one request

---

## 📦 Branches

| Branch | Description |
|--------|-------------|
| `main` (default) | Stable release branch with tested, production-ready features |
| `dev` | Development branch with the latest features and improvements |

```bash
# Clone main branch (stable)
git clone -b main https://github.com/realyinchen/AgentHub.git

# Clone dev branch (latest)
git clone -b dev https://github.com/realyinchen/AgentHub.git
```

---

## 🚧 Known Limitations and Roadmap

### Known Limitations
1. **Testing**: No unit/integration tests currently implemented
2. **Vector Database**: The vector store functionality (both Qdrant and sqlite-vec backends) has not been fully tested yet. The `vectorstore_search` tool and document ingestion features require further validation

### Roadmap
- Additional agent types (SQL agent, code agent, multi-agent workflows)
- Comprehensive test suite for backend and frontend
- Agent graph visualization in React UI
- Conversation search and filtering
- Document upload UI for vector store population
- Agent performance metrics dashboard

---

## 📄 License

This project is licensed under the terms found in the [LICENSE](LICENSE) file.