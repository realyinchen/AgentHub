# 🧠 AgentHub - AI Agent Platform

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

A modular AI Agent collection framework that provides a modern web interface for experimenting with LangChain and LangGraph agents. Built with FastAPI (backend) and React (frontend), featuring a clean separation of concerns and modern development practices.

This is the GUI version of the [AgentLab](https://github.com/realyinchen/AgentLab) project.

Inspired by: [agent-service-toolkit](https://github.com/JoshuaC215/agent-service-toolkit)

Follow my WeChat official account for the latest updates:

![wechat_qrcode](https://github.com/realyinchen/RAG/blob/main/imgs/wechat_qrcode.jpg)

## 🚀 Project Features

✅ **FastAPI Backend** — Robust RESTful API layer for agent orchestration and async task management.  
✅ **Modern React Frontend** — Interactive web interface built with Vite + React + TypeScript + Tailwind CSS + shadcn/ui for superior user experience.  
✅ **LangChain/LangGraph Integration** — Easy to build, design, and connect multi-agent reasoning workflows with visualization.  
✅ **Streaming & Event-Driven** — Real-time token streaming and agent execution event visualization.  
✅ **Thinking Mode** — Toggle between standard and thinking modes for deeper reasoning with separate UI for thought process and tool calls.  
✅ **Quote Messages** — Quote any historical message to continue the conversation with context. Quotes persist across page refreshes.  
✅ **Multi-language Support** — Built-in internationalization with English and Chinese translations.  
✅ **Dark/Light Theme** — Customizable theme support for comfortable viewing.  
✅ **Image Zoom & Drag** — Click any image in markdown to zoom in/out and drag to pan. Universal feature for all agents.  
✅ **Chat Minimap** — VSCode-style minimap showing miniature conversation text with hover preview, click-to-jump, and drag-to-scroll navigation. Fixed viewport click navigation, preview tooltip close behavior, and bottom position preview display.  

## 🧩 Perfect For:

Students and developers who want to efficiently showcase their LangChain and LangGraph learning achievements in an interactive, visual format.

## 🏗️ Architecture

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
│   │   ├── agents/         # Agent implementations (chatbot, rag-agent)
│   │   ├── api/            # API routes
│   │   ├── core/           # Core configurations
│   │   ├── database/       # Database managers and checkpointer
│   │   ├── tools/          # LangChain tools collection
│   │   ├── prompt/         # Centralized prompt templates
│   │   └── ...             # Other modules
│   ├── scripts/            # Database initialization scripts
│   │   └── init_database.py # Initialize PostgreSQL and Qdrant
│   ├── .env                # Environment variables
│   ├── .env.example        # Environment variables example
│   ├── requirements.txt    # Python dependencies
│   └── run_backend.py      # Backend startup script
└── README.md               # This file
```

## 🛠️ Tech Stack

### Backend
- **Python 3.12** - Runtime environment
- **FastAPI** - High-performance web framework with automatic API documentation
- **LangChain** - LLM orchestration framework
- **LangGraph** - Agent workflow graphs for complex reasoning
- **PostgreSQL** - Primary database with async/sync support
- **Qdrant** - Vector store for RAG functionality
- **Uvicorn** - ASGI server for production deployment

### Frontend
- **Vite** - Next-generation build tool with instant server start
- **React 19** - Component-based UI library
- **TypeScript** - Static typing for code safety
- **Tailwind CSS** - Utility-first CSS framework
- **shadcn/ui** - Accessible, customizable UI components
- **TanStack Query** - Data fetching and state management
- **Lucide React** - Beautiful icon library

## 📦 Branches

This project has two branches:

- **main** (default): Stable release branch with tested, production-ready features. Clone this branch if you want a stable experience.
- **dev**: Development branch with the latest features and improvements. Clone this branch if you want to try the newest capabilities.

```bash
# Clone main branch (stable)
git clone -b main https://github.com/realyinchen/AgentHub.git

# Clone dev branch (latest)
git clone -b dev https://github.com/realyinchen/AgentHub.git
```

## 🚀 Quick Start

### Prerequisites
1. Install [VS Code](https://code.visualstudio.com/Download) and [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/)
2. Install [Node.js 18+](https://nodejs.org/) for frontend development
3. **Start PostgreSQL and Qdrant** (required for both local development and Docker deployment):
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

### Setup Instructions

1. **Create virtual environment**
   ```bash
   conda create -n agenthub python=3.12
   ```

2. **Activate virtual environment**
   ```bash
   conda activate agenthub
   ```

3. **Clone and enter project directory**
   ```bash
   git clone https://github.com/realyinchen/AgentHub.git
   cd AgentHub
   ```

4. **Configure environment variables**
   ```bash
   cd backend
   cp .env.example .env
   ```
   Edit `.env` with your API keys and configuration settings.

5. **Install backend dependencies**
   ```bash
   pip install -r requirements.txt
   ```

6. **Initialize database**
   ```bash
   python scripts/init_database.py
   ```

7. **Start backend server**
   ```bash
   python run_backend.py
   ```

8. **In a new terminal, navigate to frontend and start development server**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

9. **Access the application**
   - Frontend: Open `http://localhost:5173` in your browser
   - Backend API: Visit `http://localhost:8080/docs` for Swagger UI

## 🤖 Available Agents

- **chatbot** — Conversational agent with tools:
  - `get_current_time` — Get current time in any timezone
  - `web_search` — Search the web for real-time information (via Tavily)
  - Supports real-time queries (weather, news, current time, etc.)
- **rag-agent** — Advanced RAG agent with:
  - Question routing (vector store / web search / direct answer)
  - Qdrant vector store retrieval
  - Document relevance grading
  - Hallucination grading
  - Answer quality grading
  - Tavily web search fallback
  - Reporter node for final answer formatting
- **navigator** — Navigation agent with Amap (高德地图) integration:
  - `get_current_time` — Get current time in any timezone
  - `amap_geocode` — Convert address to coordinates (geocoding)
  - `amap_place_search` — Search POI by keywords (restaurants, hotels, etc.)
  - `amap_place_around` — Search POI around a location
  - `amap_driving_route` — Plan driving route with distance, time, and navigation URL
  - `amap_route_preview` — Generate complete route preview URL with waypoints
  - `amap_weather` — Query weather information for a city
  - Features: Time conflict detection, itinerary planning, weather-aware suggestions
  - **Parallel tool execution** — Multiple tools execute simultaneously for faster planning
  - Supports location queries, route planning, and nearby place searches

## 📋 Environment Variables

### Backend (backend/.env)
```env
# Application mode. If the value is "dev", it will enable uvicorn reload
MODE=dev

# Web server configuration
HOST=0.0.0.0
PORT=8080

# =============================================================================
# LLM Configuration - Multi-model via LLM_MODELS (Recommended)
# =============================================================================
# Model Naming Convention:
#   - Regular models: any name without "thinking" suffix (e.g., "default", "gpt-4", "glm-4")
#   - Thinking models: name MUST end with "thinking" (e.g., "deepseek-thinking", "qwen-thinking")
#   - The "thinking" suffix determines if the model appears in thinking mode selector in UI
#
# Supported providers: dashscope (阿里云), zai (智谱) etc.
# See LiteLLM documentation for full provider list: https://docs.litellm.ai/docs/providers

LLM_MODELS=[{"model_name":"qwen3.5-27b","litellm_params":{"model":"dashscope/qwen3.5-27b","api_key":"sk-xxx","extra_body":{"enable_thinking":false}}},{"model_name":"qwen3.5-flash-thinking","litellm_params":{"model":"dashscope/qwen3.5-flash-2026-02-23","api_key":"sk-xxx","extra_body":{"enable_thinking":true}}},{"model_name":"glm5","litellm_params":{"model":"zai/glm-5","api_key":"xxx.xxx","extra_body":{"thinking":{"type":"disabled"}}}},{"model_name":"glm5-thinking","litellm_params":{"model":"zai/glm-5","api_key":"xxx.xxx","extra_body":{"thinking":{"type":"enabled"}}}}]

# Default model for regular chat (must match a model_name in LLM_MODELS)
LLM_DEFAULT_MODEL=qwen3.5-27b
# Default thinking model (must match a model_name ending with "thinking")
LLM_THINKING_MODEL=qwen3.5-flash-thinking

# Embedding model
EMBEDDING_MODEL_NAME=text-embedding-v4

# =============================================================================
# LangSmith Configuration
# =============================================================================
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT="AgentHub"
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=lsv2_pt_xxx...

# =============================================================================
# PostgreSQL Configuration
# =============================================================================
POSTGRES_USER=langchain
POSTGRES_PASSWORD=langgraph
# POSTGRES_HOST is automatically detected:
# - Local development: localhost
# - Docker container: host.docker.internal
# You can override by uncommenting and setting a value below:
# POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agentdb

# =============================================================================
# Qdrant Configuration
# =============================================================================
# QDRANT_HOST is automatically detected:
# - Local development: localhost
# - Docker container: host.docker.internal
# You can override by uncommenting and setting a value below:
# QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=agentic_rag_survey

# =============================================================================
# Tavily Search API
# =============================================================================
TAVILY_API_KEY=tvly-dev-xxx...

# =============================================================================
# Amap (高德地图) Configuration
# =============================================================================
# Get your API key from: https://lbs.amap.com/api/webservice/guide/create-project/get-key
AMAP_KEY=your_amap_api_key_here
```

### Frontend (frontend/.env)
```env
VITE_API_URL=http://localhost:8080
```

## 🔄 Development Notes

- **Backend**: Located in `backend/` directory, uses FastAPI with async lifespan management
- **Frontend**: Located in `frontend/` directory, built with Vite + React + TypeScript + Tailwind CSS
- **Database Scripts**: Located in `backend/scripts/` for initialization and maintenance
- **Agent Registration**: Agents are registered in `backend/app/agents/__init__.py` and controlled via PostgreSQL
- **Streaming**: Uses Server-Sent Events (SSE) for real-time agent responses

**Before development, start PostgreSQL and Qdrant using Docker:**

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

# Initialize database (first time only)
cd backend
python scripts/init_database.py
```

## 🐳 Docker Deployment

AgentHub provides separate Docker deployment for backend and frontend.

### Deploy Backend

Only starts the backend service. You provide your own PostgreSQL and Qdrant instances.

> **⚠️ Important: Network Configuration**
>
> When running backend in Docker but connecting to PostgreSQL/Qdrant on the host machine, you **must** use `host.docker.internal` instead of `localhost`:
> - `POSTGRES_HOST=host.docker.internal` (not `localhost`)
> - `QDRANT_HOST=host.docker.internal` (not `localhost`)
>
> This is because `localhost` inside a Docker container refers to the container itself, not the host machine. `host.docker.internal` is a special DNS name that resolves to the host machine's IP address.

```bash
# 1. Copy environment file
cp backend/.env.example backend/.env

# 2. Edit backend/.env with your configuration
# Required:
#   - LLM_MODELS (your LLM API keys)
#   - POSTGRES_HOST=host.docker.internal (for local PostgreSQL)
#   - POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#   - QDRANT_HOST=host.docker.internal (for local Qdrant)
#   - QDRANT_PORT
# Optional: TAVILY_API_KEY, AMAP_KEY, LANGCHAIN_API_KEY

# 3. Start backend service
docker-compose -f docker-compose.backend.yml up -d

# 4. View logs
docker-compose -f docker-compose.backend.yml logs -f

# 5. Stop service
docker-compose -f docker-compose.backend.yml down
```

Access the application:
- Backend API: `http://localhost:8080/docs`

### Deploy Frontend

Only starts the frontend service. Requires a running backend.

> **How it works:**
> - Browser accesses frontend at `http://localhost:5173`
> - Browser makes API requests to `/api/v1` (relative path, same origin)
> - Nginx proxies `/api/` requests to the backend
> - This avoids CORS issues since browser sees same-origin requests

```bash
# 1. Start frontend service (with default settings)
docker-compose -f docker-compose.frontend.yml up -d

# Or with custom backend:
# NGINX_BACKEND_HOST=your-backend \
# NGINX_BACKEND_PORT=8080 \
# docker-compose -f docker-compose.frontend.yml up -d

# 2. View logs
docker-compose -f docker-compose.frontend.yml logs -f

# 3. Stop service
docker-compose -f docker-compose.frontend.yml down
```

**Environment Variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `NGINX_BACKEND_HOST` | Hostname for nginx to proxy to | `host.docker.internal` |
| `NGINX_BACKEND_PORT` | Backend port | `8080` |
| `FRONTEND_PORT` | Frontend exposed port | `5173` |

Access the application:
- Frontend: `http://localhost:5173`

### Docker Files Structure

```
AgentHub/
├── docker-compose.backend.yml   # Backend deployment (external databases required)
├── docker-compose.frontend.yml  # Frontend deployment (external backend required)
├── backend/
│   ├── Dockerfile               # Backend container
│   └── .env.example             # Environment template
└── frontend/
    ├── Dockerfile               # Frontend container (multi-stage build)
    ├── nginx.conf               # Nginx configuration with API proxy
    └── .env.example             # Environment template
```

### Docker Commands Reference

```bash
# Build images
docker-compose -f docker-compose.backend.yml build
docker-compose -f docker-compose.frontend.yml build

# Start services in background
docker-compose -f docker-compose.backend.yml up -d
docker-compose -f docker-compose.frontend.yml up -d

# View service logs
docker-compose -f docker-compose.backend.yml logs -f
docker-compose -f docker-compose.frontend.yml logs -f

# Stop and remove containers
docker-compose -f docker-compose.backend.yml down
docker-compose -f docker-compose.frontend.yml down
```

## 🚧 Known Limitations

1. **RAG Collection**: The `rag-agent` requires pre-populated Qdrant collections; no built-in document upload UI yet
2. **Testing**: No unit/integration tests currently implemented

## 🚀 Future Enhancements

- Additional agent types (SQL agent, code agent, multi-agent workflows)
- Comprehensive test suite for backend and frontend
- Agent graph visualization in React UI
- Conversation search and filtering
- Document upload UI for Qdrant population
- Agent performance metrics dashboard