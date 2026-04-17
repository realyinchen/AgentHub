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
✅ **Flexible Model Configuration** — Configure models directly in the web UI. Switch between different agents and models within the same thread without losing conversation history.  

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

4. **Configure LLM and VLM models (IMPORTANT!)**
   
   Before initializing the database, you need to configure your LLM and VLM models:
   
   ```bash
   # Edit the SQL file to add your API keys
   # Open backend/scripts/sql/init_database.sql and:
   # - Replace empty api_key values with your actual API keys
   # - Adjust model_id, model_name as needed
   # - Set is_default=true for your preferred default LLM and VLM
   ```

5. **Configure environment variables**
   ```bash
   cd backend
   cp .env.example .env
   ```
   Edit `.env` with your configuration:
   - **Embedding model**: Configure `EMBEDDING_MODEL_NAME` and `EMBEDDING_API_KEY`
   - **Other API keys**: Tavily, Amap, LangSmith, etc.
   
   > **Note**: LLM and VLM models are configured in `init_database.sql`, not in `.env`. Embedding models are configured in `.env`.

6. **Install backend dependencies**
   ```bash
   pip install -r requirements.txt
   ```

7. **Initialize database**
   ```bash
   python scripts/init_database.py
   ```

8. **Start backend server**
   ```bash
   python run_backend.py
   ```

9. **In a new terminal, navigate to frontend and start development server**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

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

AgentHub provides separate Docker deployment for backend and frontend. Each module has its own `docker-compose.yml` file.

### Deploy Backend

Only starts the backend service. You provide your own PostgreSQL and Qdrant instances.

```bash
# 1. Navigate to backend directory
cd backend

# 2. Copy environment file
cp .env.example .env

# 3. Edit .env with your configuration
# Configure POSTGRES_HOST, QDRANT_HOST and other settings

# 4. Start backend service
docker-compose up -d

# 5. View logs
docker-compose logs -f

# 6. Stop service
docker-compose down
```

Access the application:
- Backend API: `http://localhost:8080/docs`

### Deploy Frontend

Only starts the frontend service. Requires a running backend.

```bash
# 1. Navigate to frontend directory
cd frontend

# 2. Copy environment file
cp .env.example .env

# 3. Edit .env with your configuration
# Required: NGINX_BACKEND_HOST (your backend server address)
# NGINX_BACKEND_HOST=your-backend-host
# NGINX_BACKEND_PORT=8080

# 4. Build and start frontend service
docker-compose up -d --build

# 5. View logs
docker-compose logs -f

# 6. Stop service
docker-compose down
```

**Environment Variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `NGINX_BACKEND_HOST` | Backend hostname for nginx to proxy to | `localhost` |
| `NGINX_BACKEND_PORT` | Backend port | `8080` |
| `FRONTEND_PORT` | Frontend exposed port | `5173` |

Access the application:
- Frontend: `http://localhost:5173`

### Docker Files Structure

```
AgentHub/
├── backend/
│   ├── docker-compose.yml   # Backend deployment
│   ├── Dockerfile           # Backend container
│   └── .env.example         # Environment template
└── frontend/
    ├── docker-compose.yml   # Frontend deployment
    ├── Dockerfile           # Frontend container (multi-stage build)
    ├── nginx.conf           # Nginx configuration with API proxy
    └── .env.example         # Environment template
```

## 🚧 Known Limitations

1. **Testing**: No unit/integration tests currently implemented

## 🚀 Future Enhancements

- Additional agent types (SQL agent, code agent, multi-agent workflows)
- Comprehensive test suite for backend and frontend
- Agent graph visualization in React UI
- Conversation search and filtering
- Document upload UI for Qdrant population
- Agent performance metrics dashboard