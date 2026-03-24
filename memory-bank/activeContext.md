# Active Context

## Current Work Focus

**Navigator Agent Optimization (3/24/2026)**

### Changes Made

#### 1. Removed web_search Tool
- Removed `create_web_search` import and usage from `backend/app/agents/navigator.py`
- Navigator now uses only Amap tools + time tool

#### 2. Rewrote Navigator Prompt (Authentic English)
- Complete rewrite of `backend/app/prompt/navigator.py` in authentic English
- Simplified output format: Itinerary Table + Weather + Navigation Links
- Added time conflict detection logic:
  - Detect conflicts before providing navigation links
  - Ask user if they want to adjust plans
  - Provide practical suggestions based on priority
- Priority reference for suggestions:
  - Picking up/dropping off children > Personal errands
  - Flights/High-speed rail > Regular appointments
  - Time-sensitive reservations > Flexible arrangements

#### 3. Weather Query via amap_weather
- Uses `amap_weather` tool instead of web_search for weather information
- Cleaner, more reliable weather data from Amap API

#### 4. Frontend Link Styling
- All hyperlinks in markdown now display as green buttons
- Added `ExternalLinkIcon` to indicate external links
- Click opens link in new window/tab

### Files Modified
- `backend/app/agents/navigator.py` - Removed web_search
- `backend/app/prompt/navigator.py` - Complete rewrite in English
- `frontend/src/components/ui/markdown-content.tsx` - Green button style for links

### Current Navigator Tools
| Tool | Purpose |
|------|---------|
| `get_current_time` | Get current accurate time (MUST call first) |
| `amap_geocode` | Convert address to coordinates |
| `amap_place_search` | Search POI by keywords |
| `amap_place_around` | Search POI around location |
| `amap_driving_route` | Plan driving route + generate navigation URL |
| `amap_route_preview` | Generate complete route URL with waypoints |
| `amap_weather` | Query weather information |

---

**Previous: Quote Feature Persistence Fix (3/24/2026)**

### Problem
After page refresh, quoted messages lost their special styling (clickable quote block with truncated preview). The `quoted_message_id` and `user_content` were stored in frontend state but not persisted to the backend.

### Solution
Implemented full persistence of `custom_data` through the LangGraph checkpointer:

1. **Backend UserInput Schema** - Added `custom_data` field
2. **Backend handle_input** - Store `custom_data` in `HumanMessage.additional_kwargs`
3. **Backend langchain_to_chat_message** - Restore `custom_data` from `additional_kwargs`
4. **Frontend UserInput type** - Added `custom_data` field
5. **Frontend streamChat** - Pass `custom_data` to backend

---

**Previous: Grok-Style Branching Chat Implementation (3/23/2026)**

### Completed Work
- Database schema with `message_nodes` table for tree structure
- SQLAlchemy model and Pydantic schemas
- CRUD operations for tree management
- API endpoints for tree operations
- Frontend tree manager and React context
- Branch selector UI component
- Retry/quote/edit buttons on messages
- i18n translations

---

## Current State of the Project

The project has a complete core implementation:
- ✅ FastAPI backend with `/api/v1/chat` and `/api/v1/agent` endpoints
- ✅ Modern React frontend with i18n, theme toggle, thinking mode toggle
- ✅ 3 agents registered: `chatbot`, `rag-agent`, `navigator`
- ✅ PostgreSQL integration (async + sync managers, LangGraph checkpointer)
- ✅ Qdrant vector store integration
- ✅ LangSmith tracing integration
- ✅ Thinking mode with separate UI for thinking process and tool calls
- ✅ Message content filtering for LLM compatibility
- ✅ Navigator agent with Amap integration and time conflict detection
- ✅ Green button styling for all hyperlinks in markdown

## Next Steps

- [ ] Add more agents to the hub (e.g., SQL agent, code agent, multi-agent workflows)
- [ ] Document upload UI for Qdrant population
- [ ] Unit/integration tests for backend

## Active Decisions and Considerations

- **Navigator Tool Order**: `get_current_time` first, then weather check, then other tools
- **No web_search for Navigator**: Uses `amap_weather` for weather, no traffic news search
- **Time Conflict Detection**: Check for conflicts before providing navigation links
- **Link Styling**: Green button style for all external links in markdown
- **Message Content Filtering**: Always filter `thinking` type blocks from historical messages
- **Pure LangGraph over create_agent**: Chose StateGraph for better control and async support
- **LLM Provider**: Using Alibaba DashScope (Qwen models) via OpenAI-compatible API

## Important Patterns and Preferences

- All database operations use singleton managers (`adb_manager`, `db_manager`, `qdrant_manager`)
- FastAPI lifespan manages all resource initialization and cleanup
- Agents are `CompiledStateGraph` instances from LangGraph
- API uses `agent_id` + `thread_id` for routing and conversation persistence
- Streaming uses Server-Sent Events (SSE) via `StreamingResponse`
- **PowerShell Commands**: Use PowerShell-compatible syntax (`;` instead of `&&`)
- **Lazy Initialization**: Create tools/resources at runtime, not at module import time

## Learnings and Project Insights

- **Thinking Type is OUTPUT only**: `thinking` type content blocks are output formats, not input formats
- **LangGraph StateGraph**: Provides fine-grained control for agent orchestration
- **Navigator Agent**: Time conflict detection improves user experience significantly
- **Link Styling**: Green buttons provide better visual distinction for clickable links