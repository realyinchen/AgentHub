# Development Guide

## Overview

This document is for developers who want to participate in AgentHub development or customize functionality.

---

## Technology Stack Overview

| Layer | Technology | Version Requirements |
|-------|------------|----------------------|
| Frontend | React + TypeScript + Vite | Node.js 20+ |
| Styling | TailwindCSS + shadcn/ui | - |
| Backend | FastAPI + Python | Python 3.11+ |
| AI Layer | LangChain + LangGraph | - |
| Database | SQLite / PostgreSQL + Qdrant | - |

---

## Local Development Environment Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- pnpm (recommended) or npm
- Docker (optional, for PostgreSQL + Qdrant mode)

### Backend Development Environment

```bash
# 1. Clone the project
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub/backend

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Configure environment variables
cp .env.example .env
# Edit .env, fill in necessary API Keys

# 6. Start development server (hot reload)
MODE=dev python run_backend.py
```

**Development Mode Features**:
- Uvicorn auto reload (code changes auto restart)
- Detailed log output
- Database connection pool auto maintenance

### Frontend Development Environment

```bash
# 1. Enter frontend directory
cd ../frontend

# 2. Install dependencies
pnpm install
# or npm install

# 3. Configure environment variables
cp .env.example .env
# Edit .env, ensure VITE_API_BASE_URL points to correct backend address

# 4. Start development server
pnpm dev
# or npm run dev
```

**Access URLs**:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8080
- API Documentation: http://localhost:8080/docs

---

## Project Structure

### Backend Structure

```
backend/
├── app/
│   ├── agents/              # Agent implementations
│   │   ├── chatbot.py      # Chatbot Master Agent
│   │   ├── navigator.py    # Navigation planning Agent
│   │   └── __init__.py
│   ├── api/                 # API routes
│   │   ├── agents.py
│   │   ├── chat.py
│   │   ├── models.py
│   │   ├── providers.py
│   │   ├── sessions.py
│   │   └── __init__.py
│   ├── database/            # Database abstraction layer
│   │   ├── backends/
│   │   │   ├── postgres/
│   │   │   └── sqlite/
│   │   ├── factory.py      # Factory pattern
│   │   └── interfaces/     # Interface definitions
│   ├── models/              # Pydantic models
│   ├── prompt/              # System Prompts
│   ├── services/            # Business logic layer
│   ├── tools/               # Tool functions
│   └── utils/               # Utility functions
├── data/                    # Data files (SQLite database, etc.)
├── scripts/                 # Scripts (database initialization, etc.)
├── requirements.txt
├── run_backend.py
└── .env
```

### Frontend Structure

```
frontend/
├── src/
│   ├── components/          # React components
│   │   ├── ui/             # shadcn/ui components
│   │   ├── chat/           # Chat related
│   │   ├── settings/       # Settings related
│   │   └── ...
│   ├── hooks/               # Custom Hooks
│   ├── lib/                 # Utility library
│   ├── services/            # API services
│   ├── store/               # State management (Zustand)
│   ├── types/               # TypeScript types
│   ├── App.tsx
│   └── main.tsx
├── public/
├── package.json
├── vite.config.ts
└── .env
```

---

## Core Development Concepts

### 1. Agent Development

All Agents are built based on **LangGraph**, supporting:
- State management (State)
- Tool calling (Tool Calling)
- Conditional branching (Conditional Routing)
- Memory persistence (Checkpointer)

**Developing new Agents reference document**: [Add New Agent](./add-new-agent.md)

**Key Points**:
- Always use `streaming_completion()` to automatically get Token statistics
- Pass message context through `AgentState`
- Use `Checkpointer` to persist conversation state

### 2. Database Abstraction Layer Development

Adding a new database backend requires implementing three interfaces:

```python
# 1. Implement DatabaseInterface
class MyDatabase(DatabaseInterface):
    async def get_session(self): ...
    async def create_tables(self): ...

# 2. Implement VectorstoreInterface
class MyVectorstore(VectorstoreInterface):
    async def search_with_embedding(self, ...): ...

# 3. Implement CheckpointInterface
class MyCheckpointer(Saver, CheckpointInterface):
    ...
```

Then register in `factory.py`:

```python
_DB_BACKENDS["my_db"] = MyDatabase
_VS_BACKENDS["my_vec"] = MyVectorstore
_CP_BACKENDS["my_cp"] = MyCheckpointer
```

### 3. API Development

Add new API endpoint:

```python
# app/api/my_endpoint.py
from fastapi import APIRouter

router = APIRouter(prefix="/my-endpoint", tags=["MyEndpoint"])

@router.get("/")
async def my_endpoint():
    return {"message": "Hello World"}
```

Register in `app/main.py`:

```python
from app.api.my_endpoint import router as my_router
app.include_router(my_router, prefix="/api/v1")
```

### 4. Frontend Component Development

Develop components using shadcn/ui + TailwindCSS:

```bash
# Add new shadcn component
pnpm dlx shadcn-ui@latest add component-name
```

Component development principles:
- Use TypeScript type definitions
- Follow existing component code style
- Support responsive layout
- Add appropriate loading states and error handling

---

## Development Workflow

### Code Style

**Backend (Python)**
- Follow PEP 8
- Use type annotations (Type Hints)
- Docstring style: Google style or NumPy style

**Frontend (TypeScript)**
- Use ESLint + Prettier (already configured)
- Run `pnpm lint` to check code

```bash
# Frontend code check
cd frontend
pnpm lint
pnpm lint:fix  # Auto fix
```

### Git Commit Specification

```
feat: Add new feature
fix: Fix bug
docs: Documentation update
style: Code format adjustment
refactor: Refactoring
test: Test related
chore: Build/tool/dependency related
```

### Pre-commit Check

```bash
# Backend
cd backend
python -m pytest  # If tests exist

# Frontend
cd frontend
pnpm build  # Ensure build works
```

---

## Debugging Techniques

### Backend Debugging

#### 1. LangSmith Tracing

Enable LangSmith configuration in `.env`:

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-key
```

View detailed call chains at https://smith.langchain.com/.

#### 2. Log Debugging

```python
import logging
logger = logging.getLogger(__name__)

logger.info("Information")
logger.debug("Debug information")
logger.error("Error information")
```

#### 3. Directly Test Agent

```python
# Test directly in Python REPL
from app.agents.chatbot import create_chatbot_agent
from app.utils.llm import get_llm

llm = get_llm("gpt-4o")
agent = await create_chatbot_agent(llm, checkpointer)

# Call Agent
result = await agent.ainvoke({"messages": [("user", "Hello")]})
print(result)
```

### Frontend Debugging

#### 1. React DevTools

Install browser extension for component tree inspection and state debugging.

#### 2. Network Request Debugging

Browser DevTools → Network panel to view API requests.

#### 3. State Management Debugging

Zustand store has Redux DevTools support configured, can view state changes in browser.

---

## Testing

### Backend Testing

```bash
cd backend
python -m pytest tests/ -v
```

**Test Directory Structure**:
```
tests/
├── unit/           # Unit tests
├── integration/    # Integration tests
└── conftest.py     # pytest configuration
```

### Frontend Testing

```bash
cd frontend
pnpm test           # Run tests
pnpm test:watch     # Watch mode
pnpm test:coverage  # Coverage report
```

---

## Common Development Issues

### Q: How to add new LLM Provider?

A:
1. Add Provider support in `app/utils/llm.py`
2. Add type in frontend `src/types/models.ts`
3. Add API call in frontend `src/services/models.ts`

### Q: Frontend hot reload not working?

A:
1. Check Vite configuration `server.hmr`
2. Ensure `VITE_API_BASE_URL` is correct
3. Clear browser cache and node_modules then reinstall

### Q: Agent responds slowly?

A:
1. Check LLM API network connection
2. Check if streaming output is enabled
3. Use LangSmith to analyze bottlenecks
4. Consider using faster models (like GPT-4o mini)

### Q: How to handle database migrations?

A:
1. SQLite mode: Directly delete `.db` file for auto-rebuild (development environment)
2. PostgreSQL mode: Use `alembic` or manually write migration scripts
3. Refer to initialization scripts under `scripts/` directory

---

## Performance Optimization Recommendations

### Backend Optimization

1. **Caching**: Use `TTLCache` to cache frequently accessed data (model list, Provider status, etc.)
2. **Async**: All database and network operations use async/await
3. **Connection Pool**: PostgreSQL uses connection pool to reuse connections
4. **Batch Operations**: Minimize database query count as much as possible

### Frontend Optimization

1. **React.memo**: Avoid unnecessary re-renders
2. **React Query/SWR**: Cache API responses
3. **Lazy Loading**: Use `React.lazy()` to split code
4. **Virtual List**: Long conversation lists use virtual scrolling

---

## Contribution Guide

Welcome to submit Pull Requests!

1. Fork this repository
2. Create feature branch: `git checkout -b feature/my-new-feature`
3. Commit changes: `git commit -am 'feat: add some feature'`
4. Push to branch: `git push origin feature/my-new-feature`
5. Submit Pull Request

**PR Requirements**:
- Clear feature description
- Pass all tests
- Update related documentation
- Follow code style specifications