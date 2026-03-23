# Active Context

## Current Work Focus

**Navigator Agent Improvements (3/23/2026)**

### Recent Changes

#### 1. Added Weather Checking Requirement
- Added mandatory `amap_weather` call in the workflow (step 3)
- Must check weather for all user-mentioned locations and potential waypoints
- Ensures user safety and pleasant travel experience
- Weather check is especially important for outdoor activities

#### 2. Translated Prompt to English
- Complete translation of navigator prompt to authentic English
- Maintained consistent terminology (Leg, Itinerary, etc.)
- Preserved all formatting, tables, and code examples
- Added "Weather Conditions" section in example output

#### 3. Fixed Type Annotation Bug
- Fixed Pylance error in `backend/app/tools/amap.py`
- Added `Any` to typing imports
- Added explicit type annotation: `result: dict[str, Any]`

#### 4. Added Web Search Tool for Real-time Information
- Added `web_search` tool (Tavily) to navigator agent
- Used for checking real-time traffic conditions, road closures, construction, events
- **Mandatory step**: Must call `web_search` before route planning

#### 5. Removed Static Map Tool
- Removed `amap_static_map` from AMAP_TOOLS (not needed)
- Simplified output format from 3 steps to 2 steps

#### 6. Simplified Output Format
**New Two-Step Output:**
1. **Itinerary Table** - Markdown table with segments, times, locations
2. **Navigation Links** - Complete route link + segment navigation links

#### 7. Enforced Tool Usage Order
**Mandatory execution order:**
1. `get_current_time` - Must be called FIRST
2. `web_search` - Must be called BEFORE route planning
3. `amap_weather` - Must check weather for all locations
4. Then proceed with location search, route planning, etc.

### Files Modified
- `backend/app/agents/navigator.py`: Added web_search tool, updated docstrings
- `backend/app/tools/amap.py`: Fixed type annotation, removed amap_static_map from exports
- `backend/app/prompt/navigator.py`: Complete rewrite in authentic English with weather checking

### Current Navigator Tools
| Tool | Purpose |
|------|---------|
| `get_current_time` | Get current accurate time (MUST call first) |
| `web_search` | Search real-time traffic/road info (MUST call before planning) |
| `amap_geocode` | Convert address to coordinates |
| `amap_place_search` | Search POI by keywords |
| `amap_place_around` | Search POI around location |
| `amap_driving_route` | Plan driving route + generate navigation URL |
| `amap_route_preview` | Generate complete route URL with waypoints |
| `amap_weather` | Query weather information |

---

**Previous: Auto-Title Generation Improvement (3/20/2026)**

### Problem
The auto-generated conversation title was created immediately after the user sends the first message, using only the user's input. This resulted in less accurate titles since the AI's response context was missing.

### Solution
Modified the title generation to wait until the AI's first response is complete, then generate the title using both the first user message AND the first AI response.

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
- ✅ Navigator agent with Amap integration and real-time traffic awareness

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

- **Navigator Tool Order**: `get_current_time` first, then `web_search`, then other tools
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
- **Navigator Agent**: Real-time traffic info is essential for accurate route planning
- Frontend modernization completed successfully with React + TypeScript + Tailwind + shadcn/ui