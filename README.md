# 🧠 AgentHub - AI Agent Platform

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

A modular AI Agent collection framework that provides a modern web interface for experimenting with LangChain and LangGraph agents. Built with FastAPI (backend) and React (frontend), featuring a clean separation of concerns and modern development practices.

This is the GUI version of the [AgentLab](https://github.com/realyinchen/AgentLab) project.

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
✅ **Token Stats Display** — Real-time token consumption visualization with vertical bar chart showing Input/Output/Reasoning tokens. Input tokens include system prompt (explained via tooltip). Dark mode compatible with internationalization support.  
✅ **Agent Execution Visualization** — Real-time display of agent intermediate steps including thinking/reasoning process and tool calls with arguments and results. Timeline sidebar shows execution history for each conversation turn.  
✅ **Flexible Model Configuration** — Configure LLM, VLM, and Embedding models directly in the web UI. Switch between different agents and models within the same thread without losing conversation history. Each model type (LLM/VLM/Embedding) can have its own default model.

![demo](https://github.com/realyinchen/AgentLab/blob/main/imgs/demo.gif)

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
   Edit `.env` file to configure the following:
   - **Third-party API keys**: Tavily, Amap, LangSmith, etc.

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

9. **Configure providers and models (Important!)**
   
   After the application starts, you need to configure model providers and models:
   
   1. Open the web UI at `http://localhost:5173`
   2. Click the settings icon in the top right corner
   3. Configure providers first (enter API keys)
   4. Then add models for each configured provider

10. **Access the application**
    - Frontend: Open `http://localhost:5173` in your browser
    - Backend API: Visit `http://localhost:8080/docs` for Swagger UI

## 🤖 Available Agents

- **chatbot** — Conversational agent with tools:
  - `get_current_time` — Get current time in any timezone
  - `web_search` — Search the web for real-time information (via Tavily)
  - Supports real-time queries (weather, news, current time, etc.)
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

## 🔄 Development Notes

- **Backend**: Located in `backend/` directory, uses FastAPI with async lifespan management
- **Frontend**: Located in `frontend/` directory, built with Vite + React + TypeScript + Tailwind CSS
- **Database Scripts**: Located in `backend/scripts/` for initialization and maintenance
- **Agent Registration**: Agents are registered in `backend/app/agents/__init__.py` and controlled via PostgreSQL
- **Streaming**: Uses Server-Sent Events (SSE) for real-time agent responses
- **API Design**: Only use GET, POST, DELETE endpoints (no PATCH/PUT). Model update/delete operations use POST with model_id in request body to avoid URL encoding issues with `/` character in model_id (e.g., `zai/glm-5`)
- **Token Tracking**: Automatic token usage tracking via `streaming_completion()` in `backend/app/utils/llm.py`. New agents automatically get token tracking by using this function and returning `result.raw_response`. No additional code needed. See `chatbot.py` or `navigator.py` for examples.

### LLM API Usage Guidelines

**Recommended (Async API):**
- Use `aget_llm()`, `aembedding_model()` in FastAPI async endpoints
- Use `streaming_completion()` for LLM calls with automatic token tracking

**Compatibility Only (Sync Wrappers):**
- `get_llm()`, `embedding_model()` - for legacy code or non-async contexts only
- These add overhead when called from async context (triggers warning log)

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

**⚡ Same Docker image supports both SQLite and PostgreSQL backends!** All configuration is managed in `.env` files.

### Quick Start (Recommended - SQLite Mode)

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

Open `http://localhost:5173` → Go to **Settings** → Configure your LLM API keys, and start chatting!

> 💡 **How it works**: Uses embedded SQLite databases (file-based) stored in a Docker volume. No PostgreSQL or Qdrant required.

### Production Deployment (PostgreSQL Mode)

For production use with PostgreSQL + Qdrant:

1. Edit `backend/.env`:
   - Set `DATABASE_TYPE=postgres` and `VECTORSTORE_TYPE=qdrant`
   - Set `POSTGRES_HOST=postgres` (Docker service name, NOT localhost)
   - Set `QDRANT_HOST=qdrant` (Docker service name, NOT localhost)
   - Adjust other PostgreSQL settings if needed

2. Start with the postgres profile:

```bash
docker-compose --profile postgres up -d
```

**Access the application:**
- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8080/docs`

**Data Persistence:**
- SQLite databases: `agenthub-backend-data` Docker volume
- PostgreSQL data: `agenthub-postgres-data` Docker volume
- Qdrant data: `agenthub-qdrant-data` Docker volume

**Useful Commands:**
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

Each module can also be deployed separately if you need more control:

#### Backend Only

See `backend/docker-compose.yml` for standalone backend deployment.

#### Frontend Only

See `frontend/docker-compose.yml` for standalone frontend deployment.

### Docker Files Structure

```
AgentHub/
├── docker-compose.yml       # Full-stack deployment (with profiles) ← USE THIS
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

## 🚧 Known Limitations

1. **Testing**: No unit/integration tests currently implemented
2. **Vector Database**: The vector store functionality (both Qdrant and sqlite-vec backends) has not been tested yet. The `vectorstore_search` tool and document ingestion features require further validation

## 🚀 Future Enhancements
- Additional agent types (SQL agent, code agent, multi-agent workflows)
- Comprehensive test suite for backend and frontend
- Agent graph visualization in React UI
- Conversation search and filtering
- Document upload UI for Qdrant population
- Agent performance metrics dashboard

## 📈 Performance Optimizations (2026-04-23)

### Database Optimizations
- **Connection Pool**: Increased from 5 to 20 connections (supports 100+ concurrent users)
- **Index Optimizations**: Added composite indexes, partial indexes, and covering indexes
- **Query Performance**: 5-10x faster conversation list queries

### API Optimizations
- **Rate Limiting**: 100 requests/minute default per IP (prevents abuse)
- **Caching**: In-memory TTL cache for models, providers, conversations (80%+ hit rate)
- **Sensitive Data**: API keys masked in logs for security

### Frontend Optimizations
- **Error Boundary**: Prevents white screen crashes
- **React Performance**: useMemo optimization and debounced state updates

### Vector Store Optimizations
- **Qdrant**: HNSW index configuration (m=16, ef=200) for 20-50ms search
- **Batch Search**: Support for multiple vector queries in one request

See [memory-bank/progress.md](memory-bank/progress.md) for detailed optimization notes.

## 🚀 Future Enhancements

- Additional agent types (SQL agent, code agent, multi-agent workflows)
- Comprehensive test suite for backend and frontend
- Agent graph visualization in React UI
- Conversation search and filtering
- Document upload UI for Qdrant population
- Agent performance metrics dashboard
