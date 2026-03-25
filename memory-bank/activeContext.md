# Active Context

## Current Work Focus

**Navigator Agent: Static Map with Image Zoom & Drag (3/25/2026)**

### Changes Made

#### 1. Static Map Route Preview
- Modified `amap_driving_route` tool to generate static map image URL
- Uses Amap v3 driving API with `extensions=all` to get polyline data
- Extracts real route coordinates from each step's polyline
- Generates static map with:
  - Green marker "A" for origin
  - Orange markers "C, D, E..." for waypoints
  - Red marker "B" for destination
  - Blue polyline showing the actual route

#### 2. Fixed paths Parameter Format
- Corrected paths parameter format for Amap static map API
- Format: `weight,color,transparency,,:points` (2 commas to skip fillcolor/fillTransparency)
- Official example: `paths=10,0x0000ff,1,,:116.31604,39.96491;...`

#### 3. Added Marker Labels for Map Legend
- Added `marker_labels` field to `amap_driving_route` output
- Format: `[{"label": "A", "name": "起点名称", "color": "green"}, ...]`
- Updated navigator prompt to display Map Legend below the image
- Uses colored circles: 🟢 for origin, 🟠 for waypoints, 🔴 for destination

#### 4. Image Zoom & Drag Feature (Frontend)
- Added `ImageWithZoom` component in `markdown-content.tsx`
- Features:
  - Click image to open fullscreen modal
  - Zoom in/out buttons (50%-500%)
  - Reset zoom button
  - **Drag to pan** when zoomed in (scale > 1)
  - Grab cursor changes to grabbing when dragging
  - Auto-reset position when zooming out to 1x or less
- **Universal Design**: All markdown images automatically get zoom & drag feature
- Any agent can use this feature by outputting `![alt](url)` syntax

### Files Modified
- `backend/app/tools/amap.py` - Added `_generate_static_map_url_from_route`, `marker_labels`, fixed paths format
- `backend/app/prompt/navigator.py` - Updated output format with Map Legend display
- `frontend/src/components/ui/markdown-content.tsx` - Added `ImageWithZoom` component with zoom & drag

### Current Navigator Tools
| Tool | Purpose |
|------|---------|
| `get_current_time` | Get current accurate time (MUST call first) |
| `amap_geocode` | Convert address to coordinates |
| `amap_place_search` | Search POI by keywords |
| `amap_place_around` | Search POI around location |
| `amap_driving_route` | Plan route + generate static map + navigation URLs + marker labels |
| `amap_weather` | Query weather information |

### amap_driving_route Output Fields
| Field | Description |
|-------|-------------|
| `static_map_url` | URL to static map image showing the route |
| `marker_labels` | List of marker labels for Map Legend |
| `navigation_url` | Complete route with all waypoints |
| `segment_navigation_urls` | List of segment links [{from, to, url}, ...] |
| `distance` | Total distance in meters |
| `duration` | Total duration in seconds |
| `cost` | Toll, taxi fee, traffic lights info |

---

**Previous: Navigator Agent Optimization (3/24/2026)**

### Changes Made

#### 1. Removed web_search Tool
- Removed `create_web_search` import and usage from `backend/app/agents/navigator.py`
- Navigator now uses only Amap tools + time tool

#### 2. Rewrote Navigator Prompt (Authentic English)
- Complete rewrite of `backend/app/prompt/navigator.py` in authentic English
- Simplified output format: Itinerary Table + Weather + Navigation Links
- Added time conflict detection logic

#### 3. Weather Query via amap_weather
- Uses `amap_weather` tool instead of web_search for weather information

#### 4. Frontend Link Styling
- All hyperlinks in markdown now display as green buttons
- Added `ExternalLinkIcon` to indicate external links

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
- ✅ Image zoom & drag feature for all markdown images (universal)

## Next Steps

- [ ] Add more agents to the hub (e.g., SQL agent, code agent, multi-agent workflows)
- [ ] Document upload UI for Qdrant population
- [ ] Unit/integration tests for backend

## Active Decisions and Considerations

- **Navigator Tool Order**: `get_current_time` first, then weather check, then other tools
- **No web_search for Navigator**: Uses `amap_weather` for weather, no traffic news search
- **Time Conflict Detection**: Check for conflicts before providing navigation links
- **Link Styling**: Green button style for all external links in markdown
- **Image Feature**: Universal zoom & drag for all markdown images, any agent can use
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
- **Image Zoom & Drag**: Universal feature that works for any agent outputting markdown images
- **Amap Static Map**: paths parameter format requires exact comma placement for optional fields