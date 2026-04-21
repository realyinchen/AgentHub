# Active Context: AgentHub

## Current Work Focus

**User-Configurable Embedding Models (2026-04-21)**

Implemented user-configurable embedding models in the model configuration dialog:

**Changes Made**:
1. **Backend - ModelManager** (`backend/app/core/model_manager.py`):
   - Added `get_embedding_model_instance()` method to retrieve embedding model config from database
   - Returns `(model_name, api_key)` tuple for LiteLLMEmbeddings

2. **Backend - Vector Store** (`backend/app/tools/vectorstore_retriever.py`):
   - Modified `_get_vectorstore()` to use ModelManager instead of `.env` configuration
   - Added async `_aget_vectorstore()` for async contexts

3. **Frontend - Model Configuration Dialog** (`frontend/src/features/chat/components/provider-config-dialog.tsx`):
   - Extended `MODEL_TYPES` to include `"embedding"`
   - Added Default Embedding selector alongside LLM and VLM selectors
   - Default model selectors now ordered: LLM → VLM → Embedding
   - Hidden thinking switch for embedding models (both in new model form and existing model editing)
   - Removed filtering that excluded embedding models from the UI

4. **Frontend - i18n** (`frontend/src/i18n/useI18n.tsx`):
   - Added `model.defaultEmbedding` translation key (English: "Default Embedding", Chinese: "默认嵌入模型")

**Key Decisions**:
- Embedding models are now fully configurable via database (same as LLM/VLM)
- `.env` embedding configuration is kept for reference but no longer used as fallback
- Each model type (LLM/VLM/EMBEDDING) can have one default model
- Embedding models don't have thinking mode (hidden in UI)

**Files Modified**:
- `backend/app/core/model_manager.py`
- `backend/app/tools/vectorstore_retriever.py`
- `frontend/src/features/chat/components/provider-config-dialog.tsx`
- `frontend/src/i18n/useI18n.tsx`

---

**Steps Display & Sidebar Optimization (2026-04-17)**

Optimized the steps display logic and sidebar UI:

**Changes Made**:
1. **Main Chat UI** (`chat-message-item.tsx`):
   - Added `InlineProcessSteps` component for displaying steps during agent execution
   - Steps show in main chat area while AI is processing (before final content streams)
   - Once final AI response starts streaming, steps move to sidebar

2. **Sidebar** (`agent-timeline-sidebar.tsx`):
   - Removed overall collapse functionality - title and steps always visible
   - Simplified title to just "执行步骤" / "Execution Steps" with step count
   - Each step detail remains individually collapsible (default collapsed)

3. **Scrollbar Styling** (`index.css`):
   - Added `.process-steps-scroll` class for dark mode compatible scrollbar
   - Reduced scrollbar width from 8px to 4px for finer appearance
   - Scrollbar colors adapt to theme using CSS variables

4. **i18n** (`useI18n.tsx`):
   - Added `process.executionSteps` translation key

**Files Modified**:
- `frontend/src/features/chat/components/chat-message-item.tsx`
- `frontend/src/features/chat/components/agent-timeline-sidebar.tsx`
- `frontend/src/index.css`
- `frontend/src/i18n/useI18n.tsx`
- `frontend/src/App.tsx`

---

**Agent Execution Steps UI Overhaul (2026-04-16)**

Moved agent execution steps display from sidebar to main chat UI during streaming:

**Changes Made**:
1. **Main Chat UI** (`chat-message-item.tsx`):
   - Added inline process steps display during streaming
   - Steps show in main chat area while AI is processing
   - Once final AI response arrives, steps move back to sidebar

2. **Sidebar** (`agent-timeline-sidebar.tsx`):
   - Changed "LLM Response" label to "AI Thinking" with 🧠 icon
   - Show reasoning directly without "thinking" label
   - Added separator line (`=====`) between reasoning and content
   - Removed "Result/结果" title from tool execution details

3. **App Flow** (`App.tsx`):
   - Sidebar process panel only shows when NOT streaming
   - Process session and message sequence passed to ChatMainPanel

4. **i18n** (`useI18n.tsx`):
   - Added `process.aiThinking` translation key

---

**Sidebar Real-time Saving Optimization (2026-04-16)**

Fixed sidebar inconsistency after page refresh:

**Problem**:
- During streaming: step0 → step1 → step2 → ... → step7
- After refresh: step0, step2, step7 (step1 merged into step7)
- AI thinking content from multiple LLM calls was merged into one step

**Root Cause**: 
1. All message steps were saved in `finally` block after streaming ended
2. `accumulated_thinking` was never cleared between LLM calls, causing all thinking content to be merged

**Solution**:
1. Save tool step immediately in `on_tool_end` event
2. Save AI step immediately in `on_chain_end` event
3. **Save AI thinking step in `on_tool_start` event** (when LLM decides to call a tool)
4. **Clear `accumulated_thinking` and `accumulated_content` after saving**
5. Remove batch saving in `finally` block
6. Use `get_max_step_number()` for consistent step numbering
7. Frontend: Reset `expandedSteps` when `messageSequence` changes (thread switch)

**Files Modified**:
- `backend/app/utils/message_utils.py` — Real-time saving logic with thinking step separation
- `frontend/src/features/chat/components/agent-timeline-sidebar.tsx` — Reset state on thread switch

---

**Sidebar Display Optimization (2026-04-16)**

Fixed multiple sidebar display issues and optimized the user experience:

**Problems Fixed**:
1. **Step display inconsistency** — After refresh, step1 (AI message) disappeared, step7 contained step1's content
2. **User message in sidebar** — User messages should not appear in sidebar
3. **Step numbering** — "step x" numbering was unnecessary and cluttered the UI
4. **Tool call display** — Tool calls should only show merged input/output, not separate steps
5. **Conversation switching** — Old steps persisted when switching to new conversation

**Root Cause Analysis**:
- Backend saved AI thinking content incorrectly, causing duplicate saves
- `message_type` had too many types (`tool_call`, `tool_result`, `ai_response`) causing confusion
- Frontend displayed all message types including human messages
- `App.tsx` didn't clear `messageSequence` when switching conversations

**Solution**:
1. Simplified `message_type` to three types: `human`, `ai`, `tool`
2. Backend: Added `tool_calls` field to `MessageStep` model for storing tool call info
3. Backend: Refactored `message_utils.py` with `save_tool_step()` and `save_ai_step()`
4. Frontend: Sidebar only shows `tool` and `ai` type messages
5. Frontend: Removed "step x" numbering
6. Frontend: Tool steps show name, args, and result merged
7. Frontend: Clear `messageSequence` when switching conversations

**Files Modified**:
- `backend/app/schemas/chat.py` — Simplified `MessageType` enum
- `backend/app/models/message_step.py` — Added `tool_calls` field
- `backend/app/crud/message_step.py` — Updated CRUD operations
- `backend/app/utils/message_utils.py` — Refactored save logic
- `frontend/src/types.ts` — Updated TypeScript types
- `frontend/src/features/chat/components/agent-timeline-sidebar.tsx` — New display logic
- `frontend/src/App.tsx` — Clear state on conversation switch

---

**Code Review: Sidebar Message Sequence Feature (2026-04-16)**

Reviewed uncommitted code for the Agent Timeline Sidebar feature. Found and fixed the following issues:

**Issues Fixed**:
1. **Missing i18n keys** — Added `process.toolCalls`, `process.step`, `process.userMessage`, `process.llmThinking`, `process.toolCall`, `process.llmResponse` to both English and Chinese translations
2. **Hardcoded English strings** — Updated `getTimelineStepsFromSequence()` and `getTimelineStepsFromSession()` to use i18n for step titles
3. **Unused code** — Removed `STEP_TITLES` constant and `parseProcessSteps()` function from `chat-message-item.tsx`
4. **Unused import** — Removed `HistoricalProcessStep` type import

**Files Modified**:
- `frontend/src/i18n/useI18n.tsx` — Added 6 new i18n keys
- `frontend/src/features/chat/components/agent-timeline-sidebar.tsx` — Internationalized step titles
- `frontend/src/features/chat/components/chat-message-item.tsx` — Removed unused code

---

**Sidebar Message Sequence Refactoring (2026-04-15)**

Refactored the right sidebar to display Agent execution steps based on LangChain's message system, similar to LangSmith's node input/output display.

**Key Changes**:

1. **Backend - New `MessageStep` schema** (`backend/app/schemas/chat.py`):
   - `step_number`: Step number (1-indexed)
   - `message_type`: "human" | "ai" | "tool"
   - `content`: Message content
   - `tool_calls`: Tool calls for AI messages
   - `thinking`: Reasoning content for AI messages with thinking mode

2. **Backend - Modified history API** (`backend/app/api/v1/chat.py`):
   - Returns `messages` (for main chat UI) and `message_sequence` (for sidebar)
   - `messages`: Only Human and final AI messages
   - `message_sequence`: All messages as independent steps

3. **Frontend - New sidebar component** (`frontend/src/features/chat/components/agent-timeline-sidebar.tsx`):
   - Streaming mode: Real-time thinking and tool call display
   - History mode: Step-by-step display from `message_sequence`
   - Each step is expandable/collapsible
   - Auto-expands latest step

**Display Format**:
```
Step 1: User Message      (HumanMessage)
Step 2: Tool Call         (AIMessage with tool_calls)
Step 3: Tool Result       (ToolMessage)
Step 4: LLM Response      (AIMessage final, with thinking if any)
```

**Design Principles**:
- Each message is an independent step
- No merging by type (multiple AIMessages stay separate)
- Sidebar renders in message order
- Auto-generates Step 1, Step 2...

---

**Offline Token Counting - Complete Migration (2026-04-15)**

The system now uses **100% offline token estimation** via `litellm.token_counter()`. All dependencies on provider-returned `usage_metadata` have been removed.

**Why this change**:
- ChatLiteLLM in streaming + LangGraph `astream_events` scenarios often loses `usage_metadata`
- `stream_options: {"include_usage": true}` is unreliable across different providers
- Many users reported token stats completely broken in streaming mode

**What was removed**:
- `bind_tools_with_usage_tracking()` function from `model_manager.py`
- `stream_options: {"include_usage": true}` from `_build_litellm_model_list()`
- `stream_options: {"include_usage": true}` from `get_llm()` bind call
- `stream_usage=True` from `get_chat_litellm()` in `llm.py`

**Key Benefits**:
- Completely offline, no extra API calls, fast
- Input tokens calculated before LLM call (accurate)
- Output tokens accumulated during streaming (real-time)
- Does NOT depend on provider returning `usage_metadata`
- Works with all providers (OpenAI, DashScope, ZhipuAI, DeepSeek, etc.)

**Implementation**:
- `count_input_tokens(messages, model)` — Calculate prompt tokens before call
- `count_output_tokens(content, model)` — Calculate output tokens from accumulated content
- Token counts sent via SSE `usage` events (initial + final)

## Recent Changes

### Offline Token Counting (2026-04-15)

**Problem**: ChatLiteLLM in streaming + LangGraph `astream_events` scenarios often loses `usage_metadata`. Many users reported:
- `usage_metadata` missing or only in last special chunk
- Getting filtered out during streaming
- Token stats completely broken

**Solution**: Implemented offline token estimation using LiteLLM's built-in `token_counter()`:

```python
# In llm.py
def count_input_tokens(messages: List[Union[BaseMessage, Dict]], model: str) -> int:
    """Offline calculation of prompt tokens (accurate)"""
    litellm_messages = [msg.model_dump() if hasattr(msg, 'model_dump') else msg for msg in messages]
    return litellm.token_counter(model=model, messages=litellm_messages)

def count_output_tokens(content: str, model: str) -> int:
    """Offline calculation of output tokens"""
    return litellm.token_counter(model=model, text=content)
```

**How it works in `streaming_message_generator()`**:
1. **Before LLM call**: Calculate input tokens from messages
2. **During streaming**: Accumulate content and reasoning text
3. **After streaming**: Calculate output tokens from accumulated content
4. **Send usage events**: Initial (input only) + Final (all tokens)

**Key Files Modified**:
- `backend/app/utils/llm.py` — Added `count_input_tokens()` and `count_output_tokens()`
- `backend/app/utils/message_utils.py` — Refactored to use offline token counting

### Thinking Mode Fix - Round 2 (2026-04-14)

**Problem**: Thinking mode still not working after first fix.

**Root Cause**: `bind_tools()` creates a new Runnable that does NOT inherit `extra_body` from the constructor!

```python
# Before (broken):
llm = ChatLiteLLM(**llm_kwargs)  # extra_body passed here
if tools:
    llm = llm.bind_tools(tools)  # New Runnable WITHOUT extra_body!

# After (fixed):
llm = ChatLiteLLM(**llm_kwargs)
if tools:
    llm = llm.bind_tools(tools, extra_body=extra_body)  # Pass extra_body again!
```

**Solution**: Pass `extra_body` to `bind_tools()` explicitly.

### Provider Prefix Fix (2026-04-14)

**Problem**: When using model ID without provider prefix (e.g., `qwen3.5-flash`), LiteLLM throws error:
```
LLM Provider NOT provided. Pass in the LLM provider you are trying to call. You passed model=qwen3.5-flash
```

**Root Cause**: `get_chat_litellm()` didn't auto-add provider prefix. LiteLLM requires format `provider/model_name`.

**Solution**: Auto-add provider prefix from database `provider` field:
```python
# Auto-add prefix if not present
if "/" not in model and model_config:
    litellm_model = f"{model_config.provider.lower()}/{model}"
```

**Key File Modified**:
- `backend/app/utils/llm.py` - Added provider prefix auto-detection using database field

### Thinking Mode & Token Usage Fix (2026-04-14)

**Problem**: Two critical issues in streaming + LangGraph astream_events:
1. Token usage data was missing in streaming responses
2. Thinking mode was auto-enabling even when `thinking_mode=False`

**Root Cause Analysis**:
1. In `get_chat_litellm()`, `extra_body` was incorrectly passed as `default_headers` (HTTP headers) instead of `extra_body` (request body parameters)
2. `build_extra_body()` didn't explicitly disable thinking mode for all providers, allowing LiteLLM to auto-enable based on model name

**Solution**:
1. Fixed `llm.py`: Changed `llm_kwargs["default_headers"]` to `llm_kwargs["extra_body"]`
2. Enhanced `build_extra_body()` in `model_manager.py`:
   - DashScope: `{"enable_thinking": false}` when disabled
   - ZhipuAI: `{"thinking": {"type": "disabled"}}` when disabled
   - DeepSeek: No extra params (reasoning is model-dependent)
   - OpenAI: `{"reasoning_effort": "medium"}` only when enabled

**Key Files Modified**:
- `backend/app/utils/llm.py` - Fixed `extra_body` parameter passing
- `backend/app/core/model_manager.py` - Enhanced `build_extra_body()` for multiple providers

### Streaming Output Fix (2026-04-14)

**Problem**: Token usage was displayed correctly but streaming output was completely broken.

**Root Cause Analysis**:
1. `streaming_completion()` in `llm.py` used `asyncio.run()` which blocks the event loop
2. The function accumulated all chunks before yielding, defeating streaming purpose
3. Token tracking was done via `litellm.token_counter` instead of actual provider usage

**Solution**:
1. Created `get_chat_litellm()` function that returns a `ChatLiteLLM` instance
2. Refactored `chatbot.py` and `navigator.py` to use `llm.ainvoke()` instead of `streaming_completion()`
3. Rewrote `message_utils.py` to use `astream_events(v2)` for fine-grained streaming:
   - `on_chat_model_stream`: token-by-token streaming
   - `on_tool_start`: tool call initiation
   - `on_tool_end`: tool execution result
   - `on_chat_model_end`: token usage extraction

**Key Files Modified**:
- `backend/app/utils/llm.py` - Added `get_chat_litellm()` function
- `backend/app/agents/chatbot.py` - Refactored `llm_call` node
- `backend/app/agents/navigator.py` - Refactored `llm_call` node
- `backend/app/utils/message_utils.py` - Rewrote `streaming_message_generator()` with `astream_events`

### Model Configuration Page Improvements (2026-04-14)

**Goal**: Fix multiple issues in the model configuration page:
1. Frontend error display for duplicate model_id/model_name
2. API key encryption at rest
3. Password visibility toggle for new models only
4. Physical delete for models
5. Remove unnecessary placeholder text

**Completed**:
- [x] Frontend now shows centered error dialog for duplicate model_id/model_name errors
- [x] API key encryption using AES-GCM with SHA-256 derived key
- [x] Password visibility toggle (eye icon) only when adding new models
- [x] Backend physical delete for model removal
- [x] Removed "模型名称，如: qwen3.5-27b" placeholder text
- [x] Fixed double eye icon issue by hiding browser's native password toggle
- [x] Created reusable `ErrorAlertDialog` component with `useErrorAlert` hook

**Key Files**:
- `backend/app/utils/crypto.py` - AES-GCM encryption/decryption utilities
- `backend/app/crud/model.py` - Model CRUD with encryption
- `backend/app/api/v1/model.py` - Model API endpoints with error handling
- `frontend/src/components/ui/error-alert-dialog.tsx` - Reusable error dialog component
- `frontend/src/features/chat/components/provider-config-dialog.tsx` - Model configuration UI

### SSE 2.0 Protocol Implementation (Completed)

**Goal**: Build a unified SSE event protocol supporting:
- LiteLLM streaming completion
- LangGraph agent workflow
- Multi-agent orchestration
- Tool calling (with partial args streaming)
- RAG citations (streaming)
- Usage + latency + observability

**Completed**:
- [x] Created `backend/app/utils/sse_protocol.py` with SSE 2.0 core types and formatters
- [x] Implemented `SSEEventBuilder` class for building all event types
- [x] Added `format_sse()`, `format_sse_done()`, `format_sse_comment()` helpers
- [x] Updated `message_utils.py` to use SSE 2.0 format for all events
- [x] Added LangGraph node hooks for agent.node.start events
- [x] Implemented tool.call.start, tool.call.end, tool.result events
- [x] Added usage event with latency tracking
- [x] Updated frontend types with SSE 2.0 event definitions
- [x] Added backward-compatible SSE parsing in frontend

**Key Files**:
- `backend/app/utils/sse_protocol.py` - SSE 2.0 protocol layer
- `backend/app/utils/message_utils.py` - Streaming message generator
- `frontend/src/types.ts` - TypeScript types for SSE 2.0 events
- `frontend/src/lib/api.ts` - API client with SSE 2.0 parsing

### Previous Features

- **Token Stats Display** — Real-time token consumption visualization with vertical bar chart showing Input/Output/Reasoning tokens
- **Image Zoom & Drag** — Universal feature for all agents to zoom and pan images in markdown
- **Quote Messages** — Ability to quote historical messages with persistence across page refreshes
- **Thinking Mode** — Separate UI for thought process and tool calls

## Available Agents

### chatbot
Conversational agent with tools:
- `get_current_time` — Get current time in any timezone
- `web_search` — Search the web for real-time information (via Tavily)
- Supports real-time queries (weather, news, current time, etc.)

### navigator
Navigation agent with Amap (高德地图) integration:
- `get_current_time` — Get current time in any timezone
- `amap_geocode` — Convert address to coordinates (geocoding)
- `amap_place_search` — Search POI by keywords (restaurants, hotels, etc.)
- `amap_place_around` — Search POI around a location
- `amap_driving_route` — Plan driving route with distance, time, and navigation URL
- `amap_route_preview` — Generate complete route preview URL with waypoints
- `amap_weather` — Query weather information for a city
- Features: Time conflict detection, itinerary planning, weather-aware suggestions
- **Parallel tool execution** — Multiple tools execute simultaneously for faster planning

## Next Steps

1. Test token usage tracking fix with actual streaming requests
2. Verify thinking mode is only enabled when explicitly requested
3. Add additional agent types (SQL agent, code agent, multi-agent workflows)
2. Implement comprehensive test suite for backend and frontend
3. Add agent graph visualization in React UI
4. Implement conversation search and filtering
5. Create document upload UI for Qdrant population
6. Build agent performance metrics dashboard

## Active Decisions & Considerations

- Agent registration is controlled via PostgreSQL database
- LLM/VLM models are configured in `init_database.sql`, not in `.env`
- Embedding models are configured in `.env`
- API design uses only GET, POST, DELETE (no PATCH/PUT) to avoid URL encoding issues with `/` character in model_id

## Important Patterns

- Use `aget_llm()`, `aembedding_model()` in FastAPI async endpoints
- Use `get_chat_litellm()` for LangGraph agents with native streaming support
- Token tracking is automatic via `astream_events` in `message_utils.py`
- LangGraph agents use `ainvoke()` for node execution; streaming is handled by `astream_events`
