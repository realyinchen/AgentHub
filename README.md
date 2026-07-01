# 🚀 AgentHub — Production-Grade Multi-Agent Runtime Platform

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

<p align="center">
  <strong>Production-Grade Agent Runtime Platform Built on FastAPI + LangGraph</strong><br>
  High Concurrency · Low Latency · Multi-User Isolation · Long-Term Memory · Dynamic Model Switching
</p>

<p align="center">
  <a href="https://github.com/realyinchen/AgentHub/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License">
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi" alt="FastAPI">
  </a>
  <a href="https://www.langchain.com/langgraph">
    <img src="https://img.shields.io/badge/LangGraph_v1-FF5E0E?logo=langchain" alt="LangChain">
  </a>
  <a href="https://react.dev/">
    <img src="https://img.shields.io/badge/React_19-61dafb?logo=react" alt="React">
  </a>
</p>

<p align="center">
  关注公众号 <strong>AgenticHub</strong> 获得<br>
  AI智能体工程实战 | Agentic思维实现 | AgentHub开源项目作者 | 每周新增实战Agent + 完整代码 + 踩坑记录<br>
  <img src="https://github.com/realyinchen/AgentHub/blob/dev/imgs/qrcode_for_agentichub.jpg" alt="AgenticHub">
</p>

<p align="center">
  WebUI<br>
  <img src="https://github.com/realyinchen/AgentHub/blob/dev/imgs/webui.gif" alt="webui"><br>
  WeChat Channel<br>
  <img src="https://github.com/realyinchen/AgentHub/blob/dev/imgs/wechat.gif" alt="wechat channel"><br>
</p>

---

## Introduction

**AgentHub** is a production-focused Multi-Agent runtime platform that provides a high-performance, stable, and reliable Agent execution environment for AI applications.

It is **not** another Agent orchestration framework, but a true **Agent Runtime Platform** — solving the last-mile problem from prototype to production deployment.

### Core Architecture

AgentHub adopts the **Supervisor Pattern**: A super Agent (Supervisor) serves as the unified entry point, automatically identifying user intent and dispatching to the corresponding SubAgent to complete tasks.

<p align="center">
  <img src="https://github.com/realyinchen/AgentHub/blob/dev/imgs/architecture.png" alt="architecture"><br>
</p>

### Directory Structure

```
AgentHub/
├── backend/                    # Backend Service
│   ├── app/
│   │   ├── api/               # API Layer: HTTP Endpoints
│   │   ├── agents/            # Agent Layer: Supervisor + Middleware + Tools
│   │   ├── infra/             # Infrastructure Layer: Database, LLM, Config
│   │   ├── crud/              # Database CRUD Operations
│   │   ├── models/            # SQLAlchemy ORM Models
│   │   └── schemas/           # Pydantic Request/Response Models
│   └── requirements.txt
├── frontend/                   # Frontend Service
│   └── src/
│       ├── components/        # Common Components
│       ├── features/          # Feature Modules (chat, settings, etc.)
│       └── lib/               # Utility Libraries
└── docker-compose.yml         # Docker Orchestration Configuration
```

### Core Features

| Feature | Description |
|---------|-------------|
| ⚡ **High Concurrency & Low Latency** | FastAPI async + SSE token-level streaming + LiteLLM Router automatic fallback/retry |
| 👥 **Multi-User Isolation** | Independent session spaces + LangGraph Checkpointer state persistence, complete data isolation |
| 🔄 **Dynamic Model Switching** | Runtime LLM switching (OpenAI, Anthropic, Groq, Ollama, etc.) without session restart |
| 💾 **Long-Term Memory** | LangGraph Store + PGVector semantic retrieval, cross-session user preference persistence |
| 🐳 **One-Click Deployment** | Docker Compose three-container orchestration, complete service startup in 5 minutes |

### Use Cases

- **Individual Developers / Learners**: Quickly practice LangGraph production-level development
- **Startup Teams**: Rapidly validate Multi-Agent product ideas
- **Enterprise Users**: Build internal AI assistants, knowledge bases, intelligent workflows

---

## Quick Start

### Docker One-Click Deployment (Recommended)

#### Prerequisites

- Docker 20.10+
- Docker Compose v2+

#### Deployment Steps

```bash
# 1. Clone the repository
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# 2. Create environment variable files
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 3. Edit backend configuration (fill in required fields)
vim backend/.env
```

#### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SYSTEM_DEFAULT_LLM_MODEL` | Default model | `gpt-4o` or `openai/gpt-4o` |
| `SYSTEM_DEFAULT_LLM_API_KEY` | Model API Key | `sk-xxx` |
| `API_KEY_ENCRYPTION_KEY` | AES-256 encryption key (32 characters) | `python -c "import secrets; print(secrets.token_urlsafe(24)[:32])"` |
| `JWT_SECRET_KEY` | JWT signing key | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

```bash
# 4. Build and start
docker compose build && docker compose up -d

# 5. View logs
docker compose logs -f
```

#### Access URLs

- Local: http://localhost
- Server: http://your-server-ip

> ✅ Defaults to **PostgreSQL + pgvector**, data persisted to Docker named volumes

---

## Changelog

### v0.0.1 (2026-06-05) — Initial Release 🎉

**Core Features**

- ✅ Supervisor Agent basic conversation capabilities
- ✅ Dynamic model switching (runtime LLM switching)
- ✅ Tool calling (time query, web search)
- ✅ SSE streaming response
- ✅ Multi-user session isolation
- ✅ Long-term memory (LangGraph Store + PGVector)
- ✅ WeChat integration (WebSocket message push)
- ✅ Docker one-click deployment


---

## License

This project is licensed under the [Apache 2.0 License](LICENSE).

---

<p align="center">
  <strong>Made with ❤️ for the Agentic Future</strong>
</p>