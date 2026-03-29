# Progress

## What Works

### Core Features
- ✅ Multi-agent chat system with chatbot, RAG agent, and navigator agent
- ✅ Conversation persistence with PostgreSQL + LangGraph checkpointer
- ✅ Message history with tool call tracking
- ✅ Sidebar navigation for conversations
- ✅ Internationalization (English/Chinese)
- ✅ Dark/Light theme support
- ✅ Agent selection UI
- ✅ URL-based conversation sharing
- ✅ **Quote message feature with persistence** (3/24/2026)
- ✅ **Docker deployment for backend and frontend** (3/29/2026)

### Recently Completed

#### Docker Deployment Simplification (2026-03-29)
- ✅ **Removed one-click deployment** (`docker-compose.yml` deleted)
- ✅ **Fixed nginx env var substitution** - Removed `upstream` block, use `proxy_pass` with env vars
- ✅ **Fixed CORS issue** - Changed `VITE_API_BASE_URL` to relative path `/api/v1`
- ✅ **Updated documentation** - README.md and README.zh.md updated for new deployment flow
- ✅ **Deployment architecture**: Separate backend and frontend deployments with external databases

#### Quote Feature Persistence Fix (2026-03-24)
- ✅ **Problem Solved**: Quoted messages lost styling after page refresh
- ✅ **Backend UserInput Schema**: Added `custom_data` field for persistence
- ✅ **Backend handle_input**: Store `custom_data` in `HumanMessage.additional_kwargs`
- ✅ **Backend langchain_to_chat_message**: Restore `custom_data` from `additional_kwargs`
- ✅ **Frontend UserInput type**: Added `custom_data` field
- ✅ **Frontend streamChat**: Pass `custom_data` to backend
- ✅ **Result**: Quote blocks now persist correctly across page refreshes

#### Quote Feature UI Improvements (2026-03-24)
- ✅ **Quote display**: Truncated to 100 chars with underscore indicator
- ✅ **Quote editing**: Only edit user content, not the quoted text
- ✅ **Quote reconstruction**: Rebuild full content with quote on save
- ✅ **Jump to original**: Click quote block to scroll to original message

#### Navigator Agent Improvements (2026-03-23)
- ✅ **Weather Checking Requirement**
  - Added mandatory `amap_weather` call in workflow (step 3)
  - Must check weather for all user-mentioned locations and potential waypoints
  - Ensures user safety and pleasant travel experience
  - Added "Weather Conditions" section in example output

- ✅ **English Translation**
  - Complete translation of navigator prompt to authentic English
  - Maintained consistent terminology (Leg, Itinerary, etc.)
  - Preserved all formatting, tables, and code examples

- ✅ **Type Annotation Fix**
  - Fixed Pylance error in `backend/app/tools/amap.py`
  - Added `Any` to typing imports
  - Added explicit type annotation: `result: dict[str, Any]`

- ✅ **Web Search Integration**
  - Added `web_search` tool (Tavily) for real-time traffic information
  - Checks road closures, construction, traffic control, major events
  - Mandatory step before route planning

- ✅ **Simplified Output Format**
  - Removed `amap_static_map` tool (not needed)
  - Changed from 3-step to 2-step output
  - Step 1: Itinerary Table
  - Step 2: Navigation Links

- ✅ **Enforced Tool Execution Order**
  - `get_current_time` must be called FIRST
  - `web_search` must be called BEFORE route planning
  - `amap_weather` must check weather for all locations
  - Clear mandatory steps in prompt

- ✅ **Code Cleanup**
  - Removed unused imports
  - Changed Chinese comments to English in code files
  - Updated docstrings

#### Thinking Mode Feature (2026-03-10 - 2026-03-11)
- ✅ **Frontend Thinking Mode Toggle**
  - Brain icon button in prompt input area (left side of submit row)
  - Colorful icon = enabled, grayscale icon = disabled
  - Per-conversation persistence via localStorage
  - State survives page refresh and navigation

- ✅ **Frontend Message Display**
  - Separate display for tool calls (wrench icon) vs thinking process (brain icon)
  - Collapsible sections for both tool calls and thinking content
  - Clean separation of concerns in UI

- ✅ **Backend Thinking Mode Support**
  - Pure LangGraph implementation with dynamic model selection
  - `UserInput` schema with `thinking_mode` field
  - Streaming support via `astream` method
  - DashScope thinking mode integration with `reasoning_content` extraction

- ✅ **Backend Streaming**
  - Token-level streaming
  - Separate `thinking` events for reasoning content
  - Tool call streaming with status updates

- ✅ **Bug Fix - Message Content Filtering**
  - Fixed white screen bug when sending messages after previous thinking mode conversations
  - Root cause: `thinking` type blocks are OUTPUT format, not INPUT format
  - Added `_filter_message_content_for_model()` to filter historical messages
  - Filters apply to both thinking and non-thinking modes

- ✅ **UI Improvements**
  - Right-aligned top buttons with consistent width (w-40)
  - Sidebar toggle button scaled 1.5x
  - Logo area height reduced
  - All Chinese comments converted to English

#### Navigator Agent Feature (2026-03-20)
- ✅ **Amap (Gaode Map) Integration**
  - `amap_geocode` - Convert addresses to coordinates
  - `amap_place_search` - Search POI by keywords
  - `amap_place_around` - Search POI around a location
  - `amap_driving_route` - Plan driving routes with waypoints
  - `amap_route_preview` - Generate complete route URL with waypoints
  - `amap_weather` - Query weather information

- ✅ **Time & Weather Integration**
  - `get_current_time` - Get current time for time-sensitive decisions
  - `web_search` - Query weather for outdoor activities
  - Intelligent suggestions based on time (e.g., store closing hours)
  - Weather-based alternative recommendations (e.g., indoor activities for rain)

- ✅ **Navigation Agent Implementation**
  - Pure LangGraph StateGraph architecture
  - Dynamic model selection with thinking mode support
  - Streaming support for real-time responses
  - Intelligent understanding of fuzzy descriptions
  - Multi-step task handling capability
  - Time context in system prompt (like chatbot)

- ✅ **Configuration & Documentation**
  - Added `AMAP_KEY` to environment configuration
  - Updated memory bank documentation

## What's Left to Build

### Current Phase: Grok-Style Branching Chat (In Progress)
- [x] Database: message_nodes table + current_leaf_id column
- [x] Backend: SQLAlchemy models, Pydantic schemas, CRUD operations
- [x] Backend: Tree-related APIs (get tree, create node, switch branch)
- [x] Frontend: Type definitions (MessageNode, MessageTree, BranchInfo)
- [x] Frontend: MessageTree class with path management
- [x] Frontend: ConversationContext provider
- [x] Frontend: useConversationTree hook
- [x] Frontend: API functions for tree operations
- [x] Frontend: Branch selector component
- [x] Frontend: Quote dialog component
- [x] Frontend: Message item with retry/quote/edit buttons
- [ ] Frontend: Integrate ConversationProvider in App.tsx
- [ ] Testing: New conversation + send message
- [ ] Testing: Refresh page + load history
- [ ] Testing: Share link locked view
- [ ] Testing: Retry and branch switching
- [ ] Testing: Quote functionality
- [ ] Testing: Edit and branch functionality

### Next Phase: Powerful RAG Agent
- [ ] Improve document retrieval quality
- [ ] Add hybrid search (vector + keyword)
- [ ] Implement re-ranking for better relevance
- [ ] Add source citation in responses
- [ ] Support multiple document formats
- [ ] Add document upload UI

### Potential Enhancements
- [ ] Streaming for RAG agent (currently only chatbot supports full streaming)
- [ ] Thinking mode for RAG agent
- [ ] Message feedback/reactions
- [ ] Export conversation feature
- [ ] Multiple model provider support

## Current Status

**Stable** - Navigator agent improvements complete. Thinking mode feature is complete and functional. Ready for RAG agent development.

### Recent Bug Fixes

**Thinking Content Fragmentation (3/11/2026)**: Fixed an issue where thinking process content appeared fragmented when viewing historical conversations. The root cause was improper joining of streaming chunks with newlines in `_extract_thinking_content()`. Changed to join blocks directly without adding separators.

## Evolution of Project Decisions

1. **Navigator Weather Checking (2026-03-23)**
   - Added mandatory weather checking for all user-mentioned locations
   - Ensures user safety and pleasant travel experience
   - Weather info displayed in output for transparency
   - Especially important for outdoor activities

2. **Navigator English Translation (2026-03-23)**
   - Translated all prompts from Chinese to authentic English
   - Maintained consistent terminology across the codebase
   - Better alignment with international development standards

3. **Navigator Tool Execution Order (2026-03-23)**
   - Enforced mandatory tool call sequence
   - `get_current_time` first for accurate time context
   - `web_search` before planning for real-time traffic awareness
   - Prevents outdated or incorrect route suggestions

4. **Navigator Output Simplification (2026-03-23)**
   - Removed static map generation (not practical)
   - Focus on navigation URLs that open in Amap app/web
   - Two-step output: table + links

5. **Message Content Filtering (2026-03-11)**
   - Discovered `thinking` type blocks cause API errors when sent as input
   - Solution: Filter all historical messages to remove `thinking` type blocks
   - Only keep supported INPUT types: `text`, `image_url`, `video_url`, `video`
   - Applied universally, regardless of thinking mode

6. **Thinking Mode Implementation**
   - Initially considered storing in conversation metadata
   - Decided on localStorage for simplicity and persistence without backend changes
   - Per-thread storage ensures each conversation has independent settings

7. **Pure LangGraph Architecture (2026-03-10)**
   - Replaced `create_agent` + middleware pattern with pure StateGraph
   - Dynamic model selection directly in `llm_call` node function
   - Better async support and finer control over agent behavior

8. **Tool Call vs Thinking Display**
   - Separated the UI concerns clearly
   - Tool calls use wrench icon (functional operations)
   - Thinking uses brain icon (reasoning process)
   - Both are collapsible for cleaner UX