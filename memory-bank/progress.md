# Progress: AgentHub

## What Works

### Core Features
- ✅ FastAPI backend with async lifespan management
- ✅ React frontend with Vite + TypeScript + Tailwind CSS + shadcn/ui
- ✅ LangChain/LangGraph agent integration
- ✅ **SSE 2.0 Protocol** — Enterprise-grade streaming with unified event format
- ✅ PostgreSQL database integration
- ✅ Qdrant vector store integration
- ✅ Docker deployment (separate for backend and frontend)
- ✅ **Model Configuration UI** — Dynamic model management with API key encryption

### Agents
- ✅ **chatbot** — Conversational agent with time and web search tools
- ✅ **navigator** — Navigation agent with Amap integration and parallel tool execution

### UI Features
- ✅ Thinking Mode with separate UI for thought process and tool calls
- ✅ Quote Messages with persistence across page refreshes
- ✅ Multi-language Support (English, Chinese)
- ✅ Dark/Light Theme
- ✅ Image Zoom & Drag in markdown
- ✅ Token Stats Display with vertical bar chart
- ✅ **Sidebar Message Sequence** — Step-by-step display of agent execution (LangSmith-style)
- ✅ **Solar System Agent Grid** — Master chatbot as sun, agents as planets with 3D glassmorphism effect

### Recent Feature (2026-04-23)

1. **Agent Sidebar**: Right-side fixed-width sidebar for agent selection
   - **Design**: Minimalist, lightweight style with light color scheme
   - **Width**: Fixed 240px with card width 100% adaptive
   - **Card Structure**:
     - Title: 14px, font-weight 600, color #1d2129, max 2 lines with ellipsis
     - Description: 12px, font-weight 400, color #666666, max 2 lines with ellipsis
     - Gap between title and description: 4px
   - **Card Container**:
     - Padding: 12px 14px
     - Gap between cards: 8px
     - Border radius: 10px
     - Background: white (#ffffff)
     - Left border: 4px transparent (for selected state highlight)
   - **Interactions**:
     - Hover: Background #f5f7fa, 0.2s ease transition
     - Selected: Brand color light transparent rgba(255,107,0,0.1), left border brand color #ff6b00
   - **Features**:
     - Vertical scroll for overflow
     - Min-height 72px, auto-expand for content
     - Search functionality with i18n support
     - Load more pagination (10 agents at a time)
     - chatbot always displayed first
     - Light/Dark theme adaptation
   - **Files**: `agent-sidebar.tsx`, `agent-sidebar-card.tsx`

2. **Solar System Agent Grid**: Redesigned agent selection with solar system layout
   - **Design**: Master chatbot as center sun (恒星), agents as planets (行星)
   - **Features**:
     - Center sun with Bot icon and prompt text "不知道从哪开始就点我吧"
     - 8 planet positions with non-uniform scattered layout
     - 3D glassmorphism bubbles with gradient + highlight + shadow effects
     - Agent names centered and bold in planet bubbles
     - Light/Dark theme adaptation
     - Placeholders smaller and semi-transparent for empty slots
   - **Files**: `solar-system-agent-grid.tsx`

### Development Experience
- ✅ Database initialization scripts
- ✅ Environment configuration via .env files
- ✅ OpenAPI documentation (Swagger UI)
- ✅ Hot reload for frontend development

## What's Left to Build

### High Priority
- [ ] Comprehensive test suite (unit/integration tests)
- [ ] Additional agent types (SQL agent, code agent)
- [ ] Multi-agent workflows

### Medium Priority
- [ ] Agent graph visualization in React UI
- [ ] Conversation search and filtering
- [ ] Document upload UI for Qdrant population

### Low Priority
- [ ] Agent performance metrics dashboard
- [ ] Advanced RAG features

## Current Status

The project is in a **stable, production-ready state** with two fully functional agents. The main branch contains tested, production-ready features. The dev branch contains the latest features and improvements.

### Branches
- **main** (default): Stable release branch
- **dev**: Development branch with latest features

## Known Issues

1. **Testing**: No unit/integration tests currently implemented

### Recent Feature (2026-04-16)

1. **Session Isolation for Process Steps**: Each conversation turn now has its own session
   - **Problem**: All AI messages shared one big steps process in sidebar, no way to see which steps belonged to which message
   - **Solution**:
     - Added `session_id` (UUID) to `message_steps` table to group steps by conversation turn
     - Backend generates a new `session_id` at the start of each streaming call
     - All steps (tool calls, AI responses) are saved with the same `session_id`
     - Frontend sidebar now shows session cards with summary stats (tool count, thinking)
     - Click on a session card to view detailed steps for that session
     - Card-style UI matching token-stats-panel design
   - **Files**: `init_database.sql`, `message_step.py` (model), `message_step.py` (crud), `message_utils.py`, `types.ts`, `agent-timeline-sidebar.tsx`, `App.tsx`

2. **Token Usage Tracking & Display**: Added comprehensive token tracking and visualization
   - **Backend Changes**:
     - Added token fields to `conversations` table: `input_tokens`, `cache_read`, `output_tokens`, `reasoning`, `total_tokens`
     - Updated `Conversation` model with new token fields (default to 0)
     - Updated `ConversationInDB` schema with token fields
     - Added `update_conversation_tokens()` CRUD function for cumulative token updates
     - Modified `message_utils.py` to extract and accumulate token usage from `usage_metadata`:
       - `input_tokens` from `usage_metadata.input_tokens`
       - `cache_read` from `usage_metadata.input_token_details.cache_read`
       - `output_tokens` from `usage_metadata.output_tokens`
       - `reasoning` from `usage_metadata.output_token_details.reasoning`
       - `total_tokens` from `usage_metadata.total_tokens`
     - Token updates saved to database after each conversation turn
   - **Frontend Changes**:
     - Updated `ConversationInDB` type with token fields
     - Created `TokenStatsPanel` component with horizontal bar charts
     - Refactored right sidebar into three sections:
       - Top: Configuration (buttons, model selector, agent selector)
       - Middle: Agent Process Panel (scrollable)
       - Bottom: Token Stats Panel (fixed at bottom)
     - Added `currentInteractionTokens` state to track current interaction tokens
     - Updated `usage` event handling to accumulate tokens during streaming
     - Reset tokens when switching conversations
   - **UI Features**:
     - 4 horizontal bar charts: Input, Cache Read, Output, Reasoning
     - Total tokens summary bar
     - Current interaction shown as highlighted portion of cumulative bar
     - Color-coded bars for easy identification
   - **Files**: `init_database.sql`, `chat.py` (model), `chat.py` (schema), `chat.py` (crud), `message_utils.py`, `types.ts`, `token-stats-panel.tsx`, `App.tsx`

### Recent Fix (2026-04-16)

1. **Real-time Message Steps Saving**: Fixed sidebar inconsistency after page refresh
   - **Problem**: After refresh, sidebar showed different steps than during streaming
     - During streaming: step0 → step1 → step2 → ... → step7
     - After refresh: step0, step2, step7 (step1 merged into step7)
   - **Cause**: All message steps were saved in `finally` block after streaming ended
   - **Solution**:
     - Save tool step immediately in `on_tool_end` event
     - Save AI step immediately in `on_chain_end` event
     - Remove batch saving in `finally` block
     - Use `get_max_step_number()` for consistent step numbering
   - **Files**: `backend/app/utils/message_utils.py`

2. **Sidebar Display Optimization**: Fixed multiple sidebar display issues
   - **Problem 1**: After refresh, step1 (AI message) disappeared, step7 contained step1's content
   - **Problem 2**: User message showing in sidebar
   - **Problem 3**: "step x" numbering not needed
   - **Problem 4**: Tool calls should only show input/output merged
   - **Problem 5**: Switching conversations didn't clear old steps
   - **Solution**:
     - Simplified `message_type` to three types: `human`, `ai`, `tool`
     - Backend: Added `tool_calls` field to `MessageStep` model
     - Backend: Refactored `message_utils.py` with `save_tool_step()` and `save_ai_step()`
     - Frontend: Sidebar only shows `tool` and `ai` type messages
     - Frontend: Removed "step x" numbering
     - Frontend: Tool steps show name, args, and result merged
     - Frontend: Clear `messageSequence` when switching conversations in `App.tsx`
   - **Files**: `chat.py`, `message_step.py`, `message_step.py` (crud), `message_utils.py`, `types.ts`, `agent-timeline-sidebar.tsx`, `App.tsx`

2. **Code Review: Sidebar i18n Issues**: Fixed internationalization issues in sidebar component
   - **Problem**: Hardcoded English strings in timeline step titles, missing i18n keys
   - **Solution**:
     - Added 6 new i18n keys: `process.toolCalls`, `process.step`, `process.userMessage`, `process.llmThinking`, `process.toolCall`, `process.llmResponse`
     - Updated `getTimelineStepsFromSequence()` and `getTimelineStepsFromSession()` to use i18n
     - Removed unused `STEP_TITLES` constant and `parseProcessSteps()` function
   - **Files**: `useI18n.tsx`, `agent-timeline-sidebar.tsx`, `chat-message-item.tsx`

2. **Message Steps Persistence**: Fixed sidebar not showing all messages after page refresh
   - **Problem**: Intermediate messages (human, tool calls, tool results) were not persisted, only AI responses
   - **Solution**: 
     - Created `message_steps` table to store all message steps
     - Added `MessageStep` model and CRUD operations in backend
     - Updated streaming logic to save steps in real-time
     - Updated history API to return `message_sequence` from new table
     - Updated frontend sidebar to display all message types properly
   - **Features**:
     - Human messages displayed as user steps (step 0)
     - Tool calls with arguments and results
     - AI responses with thinking content
     - Brain icon toggle to show/hide sidebar process panel

3. **Sidebar Improvements**: Enhanced sidebar display and persistence
   - **Problem**: Sidebar display inconsistent between streaming and after refresh
   - **Solution**:
     - Tool call titles now show tool names for better correspondence with results
     - Streaming ends with fetching updated `message_sequence` from backend
     - Human message saved as step 0 in both frontend and backend
     - AI response step includes content and thinking
   - **Features**:
     - Real-time streaming display matches post-refresh display
     - Better tool call/result correspondence with tool names in titles
     - Sidebar automatically updates after streaming ends (no refresh needed)

### Recent Fix (2026-04-14)
2. **SSE True Streaming**: Fixed LLM token streaming not working in real-time
   - **Problem**: `ainvoke()` was called without passing `config` parameter, preventing LangGraph from intercepting and streaming LLM tokens
   - **Solution**: Pass `RunnableConfig` to `ainvoke()` in both chatbot and navigator agents
   - **Reference**: LangGraph docs - "Manual config required for async in Python < 3.11"

3. **Streaming Output Complete Fix**: Fixed streaming output completely broken while token stats worked
   - **Problem**: `streaming_completion()` used `asyncio.run()` blocking event loop, accumulated chunks before yielding
   - **Solution**: 
     - Created `get_chat_litellm()` returning `ChatLiteLLM` instance for LangGraph
     - Refactored agents to use `llm.ainvoke()` instead of `streaming_completion()`
     - Rewrote `message_utils.py` to use `astream_events(v2)` for fine-grained streaming
   - **Events**: `on_chat_model_stream` (tokens), `on_tool_start`, `on_tool_end`, `on_chat_model_end` (usage)

## Evolution of Project Decisions

### API Design Decision
- **Decision**: Use only GET, POST, DELETE endpoints (no PATCH/PUT)
- **Reason**: Avoid URL encoding issues with `/` character in model_id (e.g., `zai/glm-5`)
- **Implementation**: Model update/delete operations use POST with model_id in request body

### Model Configuration Decision
- **Decision**: Store LLM/VLM configurations in database, not .env
- **Reason**: Allows dynamic model management without code changes
- **Implementation**: Use `init_database.sql` for model configurations, `.env` for embedding models

### Token Tracking Decision
- **Decision**: Automatic token tracking via `streaming_completion()`
- **Reason**: Simplifies agent implementation and ensures consistent tracking
- **Implementation**: New agents automatically get token tracking by using this function

### Async-First Decision
- **Decision**: Primary use of async APIs
- **Reason**: Better performance in FastAPI async context
- **Implementation**: `aget_llm()`, `aembedding_model()` recommended; sync wrappers for compatibility only

### SSE 2.0 Protocol Decision
- **Decision**: Unified SSE event protocol for all streaming events
- **Reason**: Enable enterprise-grade streaming with observability, multi-agent support, and RAG citations
- **Implementation**: `SSEEventBuilder` class in `sse_protocol.py` with standardized event format:
  - `llm.token` / `llm.thinking` — LLM streaming tokens
  - `agent.node.start` / `agent.node.end` — LangGraph node tracking
  - `tool.call.start` / `tool.call.delta` / `tool.call.end` — Tool partial streaming
  - `tool.result` — Tool execution results
  - `rag.citation` / `rag.citation.delta` — RAG document citations
  - `usage` — Token usage and latency metrics
  - `error` — Error handling

### API Key Encryption Decision (2026-04-14)
- **Decision**: Encrypt API keys at rest using AES-GCM
- **Reason**: Protect sensitive credentials stored in database
- **Implementation**: `crypto.py` module with:
  - AES-256-GCM encryption via SHA-256 derived key
  - Automatic encryption on save, decryption on read
  - Environment-based encryption key (`API_KEY_ENCRYPTION_KEY` or `SECRET_KEY`)
  - Graceful fallback for plaintext keys during migration
