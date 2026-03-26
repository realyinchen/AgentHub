# Active Context

## Current Work Focus

**Unused MessageNode Tree Code Cleanup (3/26/2026)**

Successfully removed all unused MessageNode tree-structured conversation code from both frontend and backend. This code was originally implemented for Grok-style branching chat but was never integrated into the main application flow.

### Deleted Files

**Frontend:**
- `frontend/src/hooks/use-conversation-tree.ts` - Unused hook for tree management
- `frontend/src/store/conversation-context.tsx` - Unused ConversationProvider
- `frontend/src/store/message-tree.ts` - Unused MessageTreeManager class
- `frontend/src/types/message-tree.ts` - Unused MessageNode/MessageTree types
- `frontend/src/features/chat/components/branch-selector.tsx` - Unused branch selector component
- `frontend/src/features/chat/components/quote-dialog.tsx` - Unused quote dialog component

**Backend:**
- `backend/app/crud/message_node.py` - Unused CRUD operations for message nodes
- `backend/app/models/message_node.py` - Unused SQLAlchemy model
- `backend/app/schemas/message_node.py` - Unused Pydantic schemas

### Modified Files

**Frontend:**
- `frontend/src/lib/api.ts` - Removed unused API functions: `getMessageTree`, `createMessageNode`, `getMessageNode`, `updateMessageNode`, `updateCurrentLeaf`, `getNodePath`, `getNextBranchIndex`
- `frontend/src/features/chat/components/index.ts` - Removed exports for deleted components

**Backend:**
- `backend/app/api/v1/chat.py` - Removed MessageNode API endpoints: `/tree/{thread_id}`, `/nodes`, `/nodes/{node_id}`, `/conversations/{thread_id}/current-leaf`, `/nodes/{node_id}/path`, `/nodes/{parent_id}/next-branch-index`
- `backend/app/models/chat.py` - Removed `current_leaf_id` column and `current_leaf` relationship to MessageNode
- `backend/app/models/__init__.py` - Removed MessageNode import

### Reason for Removal
The MessageNode tree structure was a complex implementation that was never actually used. The current application uses LangGraph's built-in checkpointer for conversation persistence, which is simpler and works well. The tree structure added unnecessary complexity without providing any benefit.

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

### Core Features

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