# 🚀 AgentHub - AI Agent Orchestration Platform

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

<p align="center">
  <strong>The ultimate platform to orchestrate, switch, and collaborate with AI Agents. One session, infinite possibilities.</strong>
</p>

<p align="center">
  <a href="https://github.com/realyinchen/AgentHub/stargazers">
    <img src="https://img.shields.io/github/stars/realyinchen/agenthub?style=social" alt="GitHub stars">
  </a>
  <a href="https://github.com/realyinchen/AgentHub/network/members">
    <img src="https://img.shields.io/github/forks/realyinchen/agenthub?style=social" alt="GitHub forks">
  </a>
  <a href="https://github.com/realyinchen/AgentHub/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License">
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi" alt="FastAPI">
  </a>
  <a href="https://react.dev/">
    <img src="https://img.shields.io/badge/React_19-61dafb?logo=react" alt="React">
  </a>
  <a href="https://www.langchain.com/langgraph">
    <img src="https://img.shields.io/badge/LangGraph-FF5E0E?logo=langchain" alt="LangChain">
  </a>
</p>

<p align="center">
  <img src="https://github.com/realyinchen/AgentLab/blob/main/imgs/demo.gif?raw=true" alt="AgentHub Demo">
</p>

---

## ✨ Core Features

| Feature | Description |
|---------|-------------|
| 🎛️ **Dynamic Agent & LLM Switching** | Switch between any Agent and underlying LLM (OpenAI, Anthropic, Groq, Ollama, local models) **within the same session** — no history loss |
| 🧠 **Chatbot Master Agent** | Intelligent routing & task planning. Automatically understands user intent, decomposes tasks, and selects the optimal sub-agent for execution |
| ⚡ **Multi-Agent Collaboration** | Support for parallel, sequential, and conditional routing workflows. Human-in-the-loop for complex decision-making |
| 🔌 **Pluggable Agent Ecosystem** | Easily register new Agents with full LangChain component support: Tools, Memory, RAG, Graphs |
| 💬 **Modern Conversation UI** | React frontend with Markdown rendering, syntax highlighting, real-time streaming, session management, and Agent card switching |
| 📊 **Token Visualization** | Real-time token consumption charts (Input/Output/Reasoning) with dark mode and i18n support |
| 🔍 **Agent Execution Timeline** | Real-time display of intermediate steps: reasoning process, tool calls with arguments and results |
| 📋 **Kanban Dashboard** | Comprehensive trace visualization: session & turn tracking, daily token stats (conversations/tokens/input/output/reasoning), execution DAG graphs, parallel tool detection, subagent run monitoring |
| 🗄️ **Zero-Dependency Storage** | SQLite + sqlite-vec embedded database. Start in 30 seconds with zero external services |
| 🏭 **Production-Ready Architecture** | Full PostgreSQL + Qdrant support for high-concurrency deployments. One config switch, **zero code changes** |

---

## 🎯 Why AgentHub?

| Traditional Chatbot | AgentHub |
|---------------------|----------|
| ❌ **Single, Fixed Agent** | ✅ **Agent Supermarket + Intelligent Brain** |
| ❌ One model per session | ✅ Switch any model mid-conversation |
| ❌ Hardcoded tool integration | ✅ Dynamic tool binding per Agent |
| ❌ No task decomposition | ✅ Master Agent automatically plans & routes |
| ❌ Production requires full rewrite | ✅ One codebase — dev & production use cases |

**AgentHub is built for developers who want to**:
- Ship AI applications faster with a complete developer toolkit
- Experiment with multi-agent orchestration without infrastructure overhead
- Build production-ready systems that scale from SQLite to PostgreSQL

---

## 🖼️ Screenshots

| Agent Switching | Master Agent Planning |
|-----------------|----------------------|
| ![Agent Switching](https://via.placeholder.com/600x350?text=Agent+Market+UI) | ![Planning](https://via.placeholder.com/600x350?text=Master+Agent+Planning) |

| Multi-Agent Execution | LLM Provider Configuration |
|----------------------|---------------------------|
| ![Execution](https://via.placeholder.com/600x350?text=Multi+Agent+Execution) | ![Config](https://via.placeholder.com/600x350?text=LLM+Configuration) |

| Kanban Dashboard | Execution DAG Graph |
|------------------|---------------------|
| ![Kanban](https://via.placeholder.com/600x350?text=Kanban+Dashboard) | ![DAG](https://via.placeholder.com/600x350?text=Execution+DAG) |

---

## 🚀 Quick Start

### ⚠️ Important Notice (READ FIRST!)

`docker-compose.yml` uses **absolute paths** to map host directories and `.env` files. You must create these directories manually before starting, otherwise Docker will fail to start.

---

### Option 1: Docker Compose One-Click Start (Recommended)

#### Prerequisites
- Docker + Docker Compose

```bash
# 1. Clone the repository
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# 2. Create host directories (⭐ most important step)
mkdir -p /app/agenthub/backend/data
mkdir -p /app/agenthub/frontend

# 3. Copy environment variable files
cp backend/.env.example /app/agenthub/backend/.env
cp frontend/.env.example /app/agenthub/frontend/.env

# 4. Edit backend configuration (add your API Keys)
vim /app/agenthub/backend/.env
# TAVILY_API_KEY=your-key
# AMAP_API_KEY=your-key

# 5. Build and start
docker compose build
docker compose up -d

# 6. Check status
docker compose ps
docker compose logs -f
```

**Access URLs**:
- Local: http://localhost
- Server: http://your-server-ip

> ✅ Defaults to **SQLite + sqlite-vec** mode (zero external dependencies)

---

### Option 2: Manual Development Setup

#### Prerequisites
- Python 3.11+
- Node.js 20+

#### Backend

```bash
cd backend
cp .env.example .env
# Edit .env with your API keys

pip install -r requirements.txt
python scripts/init_database.py
python run_backend.py
```

#### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

**Access URL**: http://localhost:5173

---

### For more deployment options (PostgreSQL + Qdrant, separate frontend/backend), see the [Deployment Guide](docs/deployment.md).

---

## 📚 Documentation

- [🏗️ Database Abstraction Architecture](docs/database-abstraction.md) - Two-layer architecture, zero-dependency to production
- [➕ Add New Agent Guide](docs/add-new-agent.md) - Build and register custom Agents
- [📡 API Reference](docs/api-reference.md) - Complete API documentation
- [🐳 Deployment Guide](docs/deployment.md) - Docker, Kubernetes, and production deployment
- [⚙️ Configuration Reference](docs/configuration.md) - All environment variables explained
- [💻 Development Guidelines](docs/development.md) - Contributor guide and best practices

---

## 🏗️ Architecture

### Layered Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           REQUEST LAYER                                  │
│                                                                          │
│   uvicorn + FastAPI — lifespan initializes all services                  │
│                                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                             API LAYER                                    │
│                                                                          │
│   HTTP/SSE endpoints, parameter validation, global error handling        │
│                                                                          │
│   chat      — streaming/non-streaming chat, history, session management  │
│   agent     — Agent discovery and configuration                          │
│   model     — model CRUD and dynamic selection                          │
│   provider  — API key configuration management                          │
│   trace     — execution tracing, DAG visualization, step replay          │
│                                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                       AGENT RUNTIME LAYER                                │
│                                                                          │
│   Agent compilation, caching, and runtime scheduling                     │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │  Registry — central registry (DB-driven + atomic snapshot,       │   │
│   │             zero-lock reads, auto-discovery)                      │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │  Middleware — shared middleware (reused by all Agents)            │   │
│   │  · dynamic model selection  · dynamic prompt injection            │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │  Agents — independent sub-packages, auto-discovered               │   │
│   │  · Chatbot  · RAG Agent  · Multi-Agent Supervisor  · ...         │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
├───────────────┬─────────────────────────────────────────────────────────┤
│               │                                                          │
│  INFRA LAYER  │  OBSERVABILITY LAYER                                    │
│               │                                                          │
│  Foundation   │  Read-only analysis, not in runtime path                 │
│  capabilities │                                                          │
│               │  · TraceBuilder                                          │
│  · Config     │    Reconstruct execution steps from checkpoint           │
│    Global     │                                                          │
│    config     │  · Parsers                                               │
│               │    Message content / thinking extraction                 │
│  · LLM        │                                                          │
│    Litellm    │                                                          │
│    multi-pro- │                                                          │
│    vider with │                                                          │
│    fallback   │                                                          │
│               │                                                          │
│  · Database   │                                                          │
│    PG/SQLite  │                                                          │
│    + Vector   │                                                          │
│    + Checkp.  │                                                          │
│               │                                                          │
│  · Tools      │                                                          │
│    time · web │                                                          │
│    sql · vec  │                                                          │
│               │                                                          │
├───────────────┴─────────────────────────────────────────────────────────┤
│                         DATA & UTILS LAYER                               │
│                                                                          │
│   Models (SQLAlchemy ORM)  — database table definitions                  │
│   Schemas (Pydantic v2)    — request/response validation                 │
│   CRUD                     — async database operations                   │
│   Utils                    — message conversion, crypto, async writer    │
│   Prompts                  — system prompt MD templates                  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Dependency flow (strictly unidirectional, no cycles):**

```
REQUEST → API → AGENT RUNTIME → INFRA
                   │
                   └──→ OBSERVABILITY (read-only)
                              │
                              ▼
                    DATA · UTILS · PROMPTS
```

**Layer responsibilities:**

| Layer | Responsibility |
|-------|---------------|
| **REQUEST** | Process entry point, starts FastAPI, initializes all services |
| **API** | HTTP interface exposure, parameter validation, SSE streaming |
| **AGENT RUNTIME** | Agent compilation/caching/scheduling, middleware injection, runtime context |
| **INFRA** | LLM gateway, database, vector store, tool execution — pure capability provider |
| **OBSERVABILITY** | Reconstruct execution traces from checkpoint, consumed by Trace UI — read-only |
| **DATA & UTILS** | Data modeling, validation, persistence, shared utility functions |

### Technology Stack

| Layer | Technologies |
|-------|-------------|
| **Frontend** | React 19 + TypeScript + Tailwind CSS + shadcn/ui + TanStack Query |
| **Backend** | FastAPI + Uvicorn + SQLAlchemy 2.0 (async) |
| **AI Orchestration** | LangChain v1 + LangGraph (create_agent, middleware, astream_events v3) |
| **Storage (Dev)** | SQLite + sqlite-vec (zero-dependency, embedded) |
| **Storage (Production)** | PostgreSQL + pgvector + asyncpg |
| **Observability** | Built-in TraceBuilder + LangSmith |

### Directory Structure

```
backend/app/
├── main.py                    # FastAPI entrypoint + lifespan
├── api/                       # HTTP API layer
│   ├── errors.py              # Global exception handlers
│   └── v1/
│       ├── router.py          # Route aggregation
│       ├── dependencies.py    # Dependency injection (get_db)
│       ├── chat.py            # Streaming, invoke, history
│       ├── chat_title.py      # Title CRUD + auto-generation
│       ├── chat_session.py    # Conversations, stats, thinking-mode
│       ├── agent.py           # Agent discovery & config
│       ├── model.py           # Model CRUD & selection
│       ├── provider.py        # API key configuration
│       ├── stream.py          # SSE streaming engine
│       └── trace.py           # Trace kanban routes
├── agents/                    # Agent runtime layer
│   ├── __init__.py            # Auto-discovery (pkgutil)
│   ├── registry.py            # Central registry (DB + atomic snapshot)
│   ├── middleware/             # Shared middleware (all Agents reuse)
│   │   ├── model/dynamic.py   # @wrap_model_call — dynamic model selection
│   │   └── prompt/
│   │       ├── dynamic.py     # make_dynamic_prompt(agent_id)
│   │       └── service.py     # PromptService (configurable path)
│   ├── chatbot/               # Agent: general-purpose chatbot
│   │   ├── agent.py           # create_agent + register_factory
│   │   └── types.py           # ChatbotContext
│   ├── rag_agent/             # (future) RAG retrieval agent
│   ├── research/              # (future) deep research agent
│   └── multi_agent/           # (future) multi-agent supervisor
├── infra/                     # Infrastructure layer
│   ├── config.py              # pydantic-settings (single config source)
│   ├── database/              # Factory pattern, PG/SQLite dual backends
│   ├── llm/                   # Litellm gateway, model manager, extra_body
│   └── tools/                 # Infra tools (time, web, sql, vectorstore)
├── models/                    # SQLAlchemy ORM models
├── schemas/                   # Pydantic v2 request/response schemas
├── crud/                      # Async database operations
├── observability/             # Read-only trace reconstruction
│   ├── trace.py               # TraceBuilder
│   └── parsers.py             # Message content parsers
├── utils/                     # Shared utilities
│   ├── message_converters.py  # Unified message conversion (single source)
│   ├── request_handler.py     # Request-to-agent-kwargs handler
│   ├── crypto.py              # AES-GCM encryption
│   └── async_writer.py        # Async write queue
└── prompts/                   # System prompt MD templates
    ├── chatbot.md
    ├── rag_agent.md
    └── research.md
```

### Adding a New Agent

```python
# 1. Create app/agents/my_agent/agent.py
from langchain.agents import create_agent
from app.agents.registry import register_factory
from app.agents.middleware.prompt.dynamic import make_dynamic_prompt
from app.agents.middleware.model.dynamic import dynamic_model

def _create_my_agent(checkpointer=None, store=None):
    prompt = make_dynamic_prompt("my_agent")  # auto-loads prompts/my_agent.md
    return create_agent(
        model=default_llm,
        tools=[...],
        middleware=[prompt, dynamic_model],  # reuse shared middleware!
        checkpointer=checkpointer,
    )

register_factory("my_agent", _create_my_agent)

# 2. Create app/prompts/my_agent.md — system prompt
# 3. Done! Auto-discovery picks it up — zero other code changes.
```

---

## 🔌 How to Extend

### Add a New Agent

```python
# 1. Implement your LangGraph Agent in backend/app/agents/
from langgraph.graph import StateGraph, END

def create_my_agent(llm, checkpointer):
    workflow = StateGraph(AgentState)
    # ... build your graph
    return workflow.compile(checkpointer=checkpointer)

# 2. Register in backend/app/agents/__init__.py
# 3. Add prompt templates to backend/app/prompt/
# 4. Add tools to backend/app/tools/ if needed
```

**Full Guide** → [Add New Agent](docs/add-new-agent.md)

### Add a New Database Backend

Implement three interfaces and register in the factory:
- `DatabaseInterface`
- `CheckpointInterface`
- `VectorstoreInterface`

**No business code changes required.**

---

## 📊 Roadmap

- [ ] **Multi-modal Support** - Image, voice, and file attachments
- [ ] **Agent Marketplace** - Discover, install, and share community agents
- [ ] **Team Collaboration** - Multi-user support with permissions
- [ ] **Advanced Evaluation** - Agent benchmarking and performance metrics
- [ ] **Self-Hosted Model Integration** - Deep integration with Ollama, Llama.cpp
- [ ] **Agent Graph Visualization** - Visual debugging of LangGraph workflows
- [ ] **Full Test Suite** - Unit, integration, and E2E tests

---

## 🤝 Contributing

We welcome contributions!

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please read our [Development Guidelines](docs/development.md) before contributing.

---

## 📄 License

This project is licensed under the [Apache 2.0 License](LICENSE).

---

<p align="center">
  <strong>Made with ❤️ for the Agentic Future</strong>
</p>

<p align="center">
  <a href="https://github.com/realyinchen">GitHub</a> •
  <a href="https://github.com/realyinchen/AgentLab">AgentLab</a> •
  <a href="https://github.com/realyinchen/RAG">RAG Tutorial</a>
</p>

<p align="center">
  <img src="https://github.com/realyinchen/RAG/blob/main/imgs/wechat_qrcode.jpg?raw=true" alt="WeChat QR Code" width="150">
  <br>
  <em>Follow my WeChat official account for the latest updates</em>
</p>