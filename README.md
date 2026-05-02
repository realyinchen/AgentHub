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

```mermaid
flowchart TD
    subgraph Frontend["React 19 Frontend"]
        A[Chat Interface]
        B[Agent Marketplace]
        C[Model Settings]
        D[Token Visualization]
        KB[Kanban Dashboard]
    end
    
    subgraph Backend["FastAPI Backend"]
        E[API Router Layer]
        F[Agent Manager]
        G[Model Provider Manager]
        T[Trace API]
    end
    
    subgraph AgentLayer["LangGraph Agents"]
        H[Master Agent (Chatbot)]
        I[Sub Agent Pool]
        J[Navigator Agent]
        K[Custom Agents...]
    end
    
    subgraph Tools["Tools & Memory"]
        L[Web Search]
        M[Geocoding & Routing]
        N[RAG Vector Store]
        O[Checkpointer Memory]
    end
    
    subgraph Storage["Storage Layer"]
        P[PostgreSQL / SQLite]
        Q[Qdrant / sqlite-vec]
    end
    
    subgraph Observability["Observability"]
        R[LangSmith Tracing]
        S[Token Statistics]
    end
    
    A --> E
    B --> E
    C --> E
    D --> E
    KB --> T
    
    E --> F
    E --> G
    
    F --> H
    F --> I
    
    H --> J
    H --> K
    I --> J
    I --> K
    
    J --> L
    J --> M
    K --> N
    K --> O
    
    N --> Q
    O --> P
    
    H --> R
    J --> R
    J --> S
```

### Technology Stack

| Layer | Technologies |
|-------|-------------|
| **Frontend** | React 19 + TypeScript + Tailwind CSS + shadcn/ui + TanStack Query |
| **Backend** | FastAPI + Uvicorn + SQLAlchemy 2.0 (async) |
| **AI Orchestration** | LangChain + LangGraph |
| **Storage (Dev)** | SQLite + sqlite-vec (zero-dependency, embedded) |
| **Storage (Production)** | PostgreSQL + asyncpg + Qdrant |
| **Observability** | LangSmith + built-in token tracking |

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