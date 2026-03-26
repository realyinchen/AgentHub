# Active Context

## Current Work Focus

**Chat Minimap Feature (3/26/2026)**

Successfully implemented a VSCode-style minimap for the chat interface, replacing the previous message ruler. The minimap provides a visual overview of the entire conversation with interactive navigation.

### Implementation Details

**New Files:**
- `frontend/src/features/chat/components/chat-minimap.tsx` - VSCode-style minimap component

**Modified Files:**
- `frontend/src/App.tsx` - Integrated ChatMinimap, added scrollContainerRef
- `frontend/src/features/chat/components/chat-main-panel.tsx` - Added scrollContainerRef prop
- `frontend/src/features/chat/components/index.ts` - Export ChatMinimap
- `frontend/src/index.css` - Added minimap-preview CSS styles

### Features

1. **Mini Text Display**: Shows actual conversation text in miniature (2.5px font size)
2. **Color Coding**: User messages in cyan, AI messages in violet
3. **Viewport Indicator**: Semi-transparent slider showing current scroll position
4. **Hover Preview**: Mouse hover on viewport shows visible messages with Markdown rendering
5. **Click to Jump**: Click any line to jump to that message
6. **Drag to Scroll**: Drag the viewport indicator for fast navigation
7. **Immediate Close**: Preview closes immediately when mouse leaves viewport or tooltip

### Bug Fixes (3/26/2026)

1. **Viewport Click Navigation**: Fixed transparent viewport block not responding to clicks. Now clicking on the viewport indicator scrolls to the clicked position.

2. **Preview Tooltip Close**: Fixed preview tooltip not closing when mouse leaves. Now the preview closes immediately when mouse leaves either the viewport or the tooltip content.

3. **Bottom Position Preview**: Fixed "暂无消息" (no messages) showing when viewport is at the bottom. The visible messages calculation now correctly uses minimap line positions instead of estimated message heights.

4. **Message ID Matching**: Fixed minimap message IDs to match ChatMainPanel's `msg-${index}` format for correct jump-to-message functionality.

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
- ✅ Image zoom & drag feature for all markdown images (universal, full-screen immersive viewer)
- ✅ Quote message feature (Grok-style with `> quoted content` format)
- ✅ Edit message feature (creates new branch from edited message)
- ✅ **Chat Minimap** (VSCode-style minimap with hover preview and navigation)

### Core Features

#### Chat Minimap Feature
- VSCode-style minimap showing miniature conversation text
- Viewport indicator with hover preview
- Markdown rendering in preview (images, code blocks, lists, etc.)
- Click to jump, drag to scroll
- Delayed close for better UX

#### Quote Message Feature
- Click quote button on any message (user or assistant)
- Shows quoted content preview above input (truncated to 100 chars)
- Sends message with format: `> quoted content\n\nuser's new message`
- Quoted messages display with special styling and can jump to original

#### Edit Message Feature
- Edit button only shows on user messages (on hover)
- Click to enter edit mode with textarea
- Save creates new branch: removes messages from edited index onwards
- Streams new AI response automatically

#### Image Viewer Feature
- Full-screen immersive viewer (no dialog popup)
- Mouse wheel zoom (0.5x - 5x)
- Free drag when zoomed in (no boundary limits, no black borders)
- Keyboard support: ESC to close, +/- to zoom, 0 to reset
- Click outside image to close

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
- **Simple State Management**: Use React useState instead of complex context providers
- **Minimap Width**: 100px fixed width, balances visibility and space efficiency

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
- **Code Cleanup**: Remove unused code early to avoid maintenance burden
- **Tooltip Hover State**: Need delayed close + combined hover state for tooltip to remain visible when mouse moves to content