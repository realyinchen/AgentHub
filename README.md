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
  - `get_current_time` — Get current time in any timezone (MUST call first)
  - `amap_geocode` — Convert address to coordinates (geocoding)
  - `amap_place_search` — Search POI by keywords (restaurants, hotels, etc.)
  - `amap_place_around` — Search POI around a location
  - `amap_driving_route` — Plan driving route with distance, time, and navigation URL
  - `amap_route_preview` — Generate complete route preview URL with waypoints
  - `amap_weather` — Query weather information for a city
  - Features: Time conflict detection, itinerary planning, weather-aware suggestions
  - Supports location queries, route planning, and nearby place searches

## 📋 Environment Variables

### Backend (backend/.env)
```env
# Application
MODE=dev                          # "dev" enables uvicorn auto-reload

# Server
HOST=0.0.0.0
PORT=8080

# LLM (OpenAI-compatible API)
COMPATIBLE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
COMPATIBLE_API_KEY=sk-...
LLM_NAME=qwen3-max
EMBEDDING_MODEL_NAME=text-embedding-v4

# LangSmith Tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT="AgentHub"
LANGCHAIN_API_KEY=lsv2_...

# PostgreSQL
POSTGRES_USER=langchain
POSTGRES_PASSWORD=langgraph
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agentdb

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=agentic_rag_survey

# Tavily Search
TAVILY_API_KEY=tvly-...
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

## 🚧 Known Limitations

1. **RAG Collection**: The `rag-agent` requires pre-populated Qdrant collections; no built-in document upload UI yet
2. **Testing**: No unit/integration tests currently implemented
3. **Deployment**: No Docker Compose configuration for easy local deployment

## 🚀 Future Enhancements

- Additional agent types (SQL agent, code agent, multi-agent workflows)
- Comprehensive test suite for backend and frontend
- Docker Compose for simplified local development
- Agent graph visualization in React UI
- Conversation search and filtering
- Document upload UI for Qdrant population
- Agent performance metrics dashboard