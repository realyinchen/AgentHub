# Active Context

## Current Work Focus

**Quote Feature Persistence Fix (3/24/2026)**

### Problem
After page refresh, quoted messages lost their special styling (clickable quote block with truncated preview). The `quoted_message_id` and `user_content` were stored in frontend state but not persisted to the backend.

### Solution
Implemented full persistence of `custom_data` through the LangGraph checkpointer:

1. **Backend UserInput Schema** - Added `custom_data` field
2. **Backend handle_input** - Store `custom_data` in `HumanMessage.additional_kwargs`
3. **Backend langchain_to_chat_message** - Restore `custom_data` from `additional_kwargs`
4. **Frontend UserInput type** - Added `custom_data` field
5. **Frontend streamChat** - Pass `custom_data` to backend

### Data Flow
```
Send: Frontend -> streamChat({ content, custom_data: { quoted_message_id, user_content } })
    -> Backend handle_input -> HumanMessage(content, additional_kwargs={custom_data})
    -> LangGraph Checkpointer stores

Load: getHistory -> langchain_to_chat_message(HumanMessage)
    -> ChatMessage(custom_data=additional_kwargs.custom_data)
    -> Frontend displays quote block correctly
```

### Files Modified
- `backend/app/schemas/chat.py` - UserInput with custom_data
- `backend/app/utils/message_utils.py` - handle_input + langchain_to_chat_message
- `frontend/src/types.ts` - UserInput type
- `frontend/src/App.tsx` - streamChat call with custom_data

---

**Previous: Grok-Style Branching Chat Implementation (3/23/2026)**

### Overview
Implementing a tree-structured conversation history system that supports:
1. **Message Retry** - Regenerate any assistant message (creates new branch)
2. **Quote** - Quote any historical message and continue conversation
3. **Edit** - Edit user messages and create new branches

### Completed Work

#### Backend (✅ Complete)
1. **Database Schema** (`backend/scripts/sql/database_change_001.sql`)
   - `message_nodes` table with parent_id, branch_index for tree structure
   - Added `current_leaf_id` to `conversations` table
   - Indexes for efficient tree traversal

2. **SQLAlchemy Model** (`backend/app/models/message_node.py`)
   - `MessageNode` model with all required fields
   - Relationship to parent/children nodes

3. **Pydantic Schemas** (`backend/app/schemas/message_node.py`)
   - `MessageNodeCreate`, `MessageNodeUpdate`, `MessageNodeInDB`
   - `MessageTree` for complete tree response
   - `CurrentLeafUpdate` for branch switching

4. **CRUD Operations** (`backend/app/crud/message_node.py`)
   - `create_message_node` - Create node with auto branch_index
   - `get_message_node_by_id` - Get single node
   - `get_message_tree` - Get complete tree for conversation
   - `update_message_node` - Update content after streaming
   - `update_current_leaf_id` - Switch active branch
   - `get_path_to_node` - Get path from root to node
   - `get_next_branch_index` - Calculate next sibling index

5. **API Endpoints** (`backend/app/api/v1/chat.py`)
   - `GET /chat/tree/{thread_id}` - Get message tree
   - `POST /chat/nodes` - Create node
   - `GET /chat/nodes/{node_id}` - Get node
   - `PATCH /chat/nodes/{node_id}` - Update node
   - `PATCH /chat/conversations/{thread_id}/current-leaf` - Update current leaf
   - `GET /chat/nodes/{node_id}/path` - Get path to node
   - `GET /chat/nodes/{parent_id}/next-branch-index` - Get next branch index

#### Frontend (🔄 In Progress)
1. **Type Definitions** (`frontend/src/types/message-tree.ts`) ✅
   - `MessageNode`, `MessageTree`, `MessageNodeCreate`, `MessageNodeUpdate`

2. **Tree Manager** (`frontend/src/store/message-tree.ts`) ✅
   - `MessageTreeManager` class for client-side tree operations
   - Path traversal, branch switching, node management

3. **API Functions** (`frontend/src/lib/api.ts`) ✅
   - `getMessageTree`, `createMessageNode`, `updateMessageNode`
   - `updateCurrentLeaf`, `getNodePath`, `getNextBranchIndex`

4. **React Context** (`frontend/src/store/conversation-context.tsx`) ✅
   - `ConversationProvider` with full state management
   - `sendMessage`, `retry`, `quote`, `editUserMessage`, `switchBranch`
   - Streaming integration with tree updates

### Pending Work
- [x] User executes SQL migration ✅
- [x] Add branch selector UI component ✅ (`branch-selector.tsx`)
- [x] Add retry/quote/edit buttons to messages ✅ (`chat-message-item.tsx`)
- [x] Add i18n translations ✅
- [ ] Integrate `ConversationProvider` into `App.tsx`
- [ ] Update `chat-main-panel.tsx` for new data structure
- [ ] Testing and verification

### Key Architecture Decisions
- **Tree stored in database** - All nodes persisted with parent_id reference
- **Frontend manages tree state** - `MessageTreeManager` handles path traversal
- **Backend is stateless** - Each request includes full context via `currentPath`
- **Branch switching via current_leaf_id** - Single source of truth for active branch

---

**Previous: Navigator Agent Improvements (3/23/2026)**

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