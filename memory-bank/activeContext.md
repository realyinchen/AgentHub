# Active Context

## Current Work Focus

**Next Phase: Building a Powerful RAG Agent (3/11/2026)**

The thinking mode feature is complete and stable. The next major goal is to build a powerful RAG (Retrieval-Augmented Generation) agent.

### Planned RAG Agent Enhancements
- [ ] Improve document retrieval quality
- [ ] Add hybrid search (vector + keyword)
- [ ] Implement re-ranking for better relevance
- [ ] Add source citation in responses
- [ ] Support multiple document formats
- [ ] Add document upload UI

## Recent Changes

### Thinking Mode Feature Complete (3/10/2026 - 3/11/2026)

**Frontend Components:**
1. `frontend/src/features/chat/components/thinking-mode-toggle.tsx` - Brain icon toggle button
2. `frontend/src/hooks/use-thinking-mode.ts` - Custom hook for per-conversation thinking mode state

**Backend Changes:**
1. `backend/app/agents/chatbot.py` - Pure LangGraph implementation with dynamic model selection
2. `backend/app/api/v1/chat.py` - Added thinking_mode persistence endpoints
3. `backend/app/utils/message_utils.py` - Streaming support for thinking content

**Bug Fix - Message Content Filtering:**
- Fixed critical bug where `thinking` type content blocks caused API errors
- Root cause: `thinking` is an OUTPUT format, not an INPUT format
- Added `_filter_message_content_for_model()` to filter historical messages

**UI Improvements:**
- Right-aligned top buttons with consistent width
- Sidebar toggle button scaled 1.5x
- Logo area height reduced
- All Chinese comments converted to English

## Current State of the Project

The project has a complete core implementation:
- ✅ FastAPI backend with `/api/v1/chat` and `/api/v1/agent` endpoints
- ✅ Modern React frontend with i18n, theme toggle, thinking mode toggle
- ✅ 2 agents registered: `chatbot` (pure LangGraph with thinking mode), `rag-agent`
- ✅ PostgreSQL integration (async + sync managers, LangGraph checkpointer)
- ✅ Qdrant vector store integration
- ✅ LangSmith tracing integration
- ✅ Thinking mode with separate UI for thinking process and tool calls
- ✅ Message content filtering for LLM compatibility

## Next Steps

**RAG Agent Development:**
- [ ] Analyze current RAG agent implementation
- [ ] Design enhanced RAG architecture
- [ ] Implement improved retrieval strategies
- [ ] Add document management features

**Other Backend Development Priorities:**
- [ ] Add more agents to the hub (e.g., SQL agent, code agent, multi-agent workflows)
- [ ] Document upload UI for Qdrant population
- [ ] Unit/integration tests for backend

## Active Decisions and Considerations

- **Message Content Filtering**: Always filter `thinking` type blocks from historical messages before sending to any LLM
- **Pure LangGraph over create_agent**: Chose StateGraph for better control and async support
- **Lazy tool initialization**: Tools are created at runtime to avoid import-time API key errors
- **LLM Provider**: Using Alibaba DashScope (Qwen models) via OpenAI-compatible API
- **Thinking vs Tool UI**: Separate display - Brain icon for thinking, Wrench icon for tool calls

## Important Patterns and Preferences

- All database operations use singleton managers (`adb_manager`, `db_manager`, `qdrant_manager`)
- FastAPI lifespan manages all resource initialization and cleanup
- Agents are `CompiledStateGraph` instances from LangGraph
- API uses `agent_id` + `thread_id` for routing and conversation persistence
- Streaming uses Server-Sent Events (SSE) via `StreamingResponse`
- **PowerShell Commands**: Use PowerShell-compatible syntax (`;` instead of `&&`)
- **Lazy Initialization**: Create tools/resources at runtime, not at module import time

## Learnings and Project Insights

- **Thinking Type is OUTPUT only**: `thinking` type content blocks are output formats, not input formats - must be filtered from historical messages
- **LangGraph StateGraph**: Provides fine-grained control for agent orchestration
- **MessagesState**: Use as base class for custom state to get `add_messages` reducer
- **Dynamic Model Selection**: Can be done directly in node functions with state access
- Frontend modernization completed successfully with React + TypeScript + Tailwind + shadcn/ui