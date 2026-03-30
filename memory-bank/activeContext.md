# Active Context

## Current Work Focus

**Automatic Environment Detection for Database Connections (3/30/2026)**

Implemented automatic runtime environment detection for `POSTGRES_HOST` and `QDRANT_HOST`, eliminating the need to manually switch between `localhost` (local development) and `host.docker.internal` (Docker deployment).

### Changes Made

**Files Modified:**
- `backend/app/core/config.py` - Added `is_running_in_docker()` and `get_default_host()` functions, plus `model_post_init()` hook for intelligent defaults
- `backend/.env` - Removed explicit `POSTGRES_HOST` and `QDRANT_HOST` values, added explanatory comments

### Key Technical Decisions

1. **Docker Detection**: Check `/.dockerenv` file and `/proc/1/cgroup` content for Docker indicators
2. **Smart Defaults**: Automatically use `host.docker.internal` in Docker, `localhost` otherwise
3. **Override Support**: Users can still explicitly set values in `.env` if needed
4. **Pydantic Hook**: Use `model_post_init()` to set defaults after model initialization

### How It Works

```python
# Local development: POSTGRES_HOST=localhost, QDRANT_HOST=localhost
# Docker deployment: POSTGRES_HOST=host.docker.internal, QDRANT_HOST=host.docker.internal
# No manual configuration needed!
```

---

**Parallel Tool Execution for Navigator Agent (3/30/2026)**

Implemented true parallel tool execution using `asyncio.gather()` in the Navigator agent, enabling all tool calls to start simultaneously for significantly faster route planning.

### Changes Made

**Files Modified:**
- `backend/app/agents/navigator.py` - Refactored `tool_node` with `asyncio.gather()` for parallel execution
- `backend/app/prompt/navigator.py` - Added "Parallel Tool Calling" section with guidance and examples

### Key Technical Decisions

1. **asyncio.gather with return_exceptions=True**: All tools start simultaneously; one failure doesn't crash others
2. **Inner execute_single_call() coroutine**: Encapsulates single tool execution with error handling
3. **Prompt Guidance**: Explicitly instruct LLM to call multiple tools in parallel for faster planning

### Performance Improvement

```
Before: Tool A (1s) → Tool B (2s) → Tool C (1s) = 4s total
After:  Tool A (1s) + Tool B (2s) + Tool C (1s) = 2s total (max time)
```

---

**Docker Deployment Simplification (3/29/2026)**

Simplified Docker deployment by removing the one-click deployment option and keeping only separate backend and frontend deployments. Fixed nginx environment variable substitution issue that caused frontend container startup failures.

### Changes Made

**Files Modified:**
- `docker-compose.yml` - **DELETED** (removed one-click deployment)
- `frontend/nginx.conf` - Removed `upstream` block, use `proxy_pass` with env vars directly
- `frontend/Dockerfile` - Fixed entrypoint script creation for proper envsubst execution
- `docker-compose.frontend.yml` - Changed `VITE_API_BASE_URL` to `/api/v1` (relative path) to avoid CORS issues
- `README.md` - Updated deployment documentation
- `README.zh.md` - Updated deployment documentation

### Key Technical Decisions

1. **Nginx Variable Substitution**: Use `envsubst` in entrypoint script to replace `${NGINX_BACKEND_HOST}:${NGINX_BACKEND_PORT}` before nginx starts
2. **CORS Avoidance**: Use relative path `/api/v1` for `VITE_API_BASE_URL` so browser sends requests to same origin (nginx), which then proxies to backend
3. **Separate Deployments**: Backend and frontend are deployed independently, requiring external PostgreSQL and Qdrant instances

### Docker Deployment Architecture

```
Browser → Frontend (nginx:5173) → /api/* → Backend (host.docker.internal:8080)
                                    ↓
                              Nginx proxy_pass
```

---

**Multi-Model Support Feature (3/26/2026)**

Successfully implemented multi-model support with dynamic model selection, enabling users to choose from multiple LLM providers (阿里云 DashScope, 智谱 GLM, local vLLM) through a model selector in the chat interface.

### Implementation Details

**Backend Changes:**
- `backend/app/core/config.py` - Added `get_model_info_list()` method to return model info with `is_thinking` flag
- `backend/app/core/models.py` - Modified `get_llm()` to accept `model_name` parameter with caching
- `backend/app/schemas/chat.py` - Added `model_name` field to `UserInput` schema
- `backend/app/utils/message_utils.py` - Updated `handle_input()` to pass `model_name` through config
- `backend/app/api/v1/chat.py` - Added `/models` endpoint to list all available models

**Frontend Changes:**
- `frontend/src/types.ts` - Added `ModelInfo` type and `model_name` to `UserInput`
- `frontend/src/lib/api.ts` - Added `getAvailableModels()` function
- `frontend/src/hooks/use-models.ts` - Created hook for model selection with localStorage persistence
- `frontend/src/features/chat/components/model-selector.tsx` - Created model selector dropdown component
- `frontend/src/features/chat/components/chat-main-panel.tsx` - Integrated model selector into chat input footer
- `frontend/src/App.tsx` - Added `useModels` hook and passed model props to `ChatMainPanel`
- `frontend/src/i18n/index.tsx` - Added translations for model selector

### Model Naming Convention

**Critical**: Models with `model_name` ending with "thinking" suffix are automatically classified as thinking/reasoning models:
- Thinking models: `"qwen3.5-flash-thinking"`, `"glm5-thinking"`, `"deepseek-thinking"`
- Regular models: `"qwen3.5-27b"`, `"glm5"`, `"gpt-4"`

When thinking mode is enabled, only models with "thinking" suffix appear in the selector.

### Configuration Format

```env
LLM_MODELS=[{"model_name":"qwen3.5-27b","litellm_params":{"model":"dashscope/qwen3.5-27b","api_key":"sk-xxx"}},{"model_name":"qwen3.5-flash-thinking","litellm_params":{"model":"dashscope/qwen3.5-flash-2026-02-23","api_key":"sk-xxx","extra_body":{"enable_thinking":true}}},{"model_name":"glm5","litellm_params":{"model":"zai/glm-5","api_key":"xxx.xxx"}},{"model_name":"glm5-thinking","litellm_params":{"model":"zai/glm-5","api_key":"xxx.xxx","extra_body":{"thinking":{"type":"enabled"}}}}]
```

### Supported Providers
- `dashscope` - 阿里云 (Qwen models)
- `zai` - 智谱 (GLM models)
- Any OpenAI-compatible API (local vLLM, etc.)

---

## Current State of the Project

The project has a complete core implementation:
- ✅ FastAPI backend with `/api/v1/chat` and `/api/v1/agent` endpoints
- ✅ Modern React frontend with i18n, theme toggle, thinking mode toggle
- ✅ **Multi-model support with model selector** (NEW)
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
- ✅ Chat Minimap (VSCode-style minimap with hover preview and navigation)

### Core Features

#### Multi-Model Support
- Model selector dropdown next to thinking mode toggle
- Models filtered based on thinking mode state
- Selection persists per conversation in localStorage
- Supports multiple providers: DashScope, 智谱, local vLLM

#### Chat Minimap Feature
- VSCode-style minimap showing miniature conversation text
- Viewport indicator with hover preview
- Markdown rendering in preview (images, code blocks, lists, etc.)
- Click to jump, drag to scroll

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

- **Model Naming**: "thinking" suffix determines model classification for UI selector
- **Model Caching**: LLM instances cached by model_name for performance
- **Navigator Tool Order**: `get_current_time` first, then weather check, then other tools
- **No web_search for Navigator**: Uses `amap_weather` for weather, no traffic news search
- **Time Conflict Detection**: Check for conflicts before providing navigation links
- **Link Styling**: Green button style for all external links in markdown
- **Image Feature**: Universal zoom & drag for all markdown images, any agent can use
- **Message Content Filtering**: Always filter `thinking` type blocks from historical messages
- **Pure LangGraph over create_agent**: Chose StateGraph for better control and async support
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
- **Model Selection**: Persisted per conversation, filtered by thinking mode

## Learnings and Project Insights

- **Multi-Provider Support**: LiteLLM provides unified interface for multiple LLM providers
- **Thinking Model Detection**: Simple suffix-based naming convention is cleaner than explicit flags
- **Model Caching**: Essential for performance when switching between models frequently
- **Thinking Type is OUTPUT only**: `thinking` type content blocks are output formats, not input formats
- **LangGraph StateGraph**: Provides fine-grained control for agent orchestration
- **Navigator Agent**: Time conflict detection improves user experience significantly
- **Link Styling**: Green buttons provide better visual distinction for clickable links
- **Image Zoom & Drag**: Universal feature that works for any agent outputting markdown images
- **Amap Static Map**: paths parameter format requires exact comma placement for optional fields
- **Code Cleanup**: Remove unused code early to avoid maintenance burden
- **Tooltip Hover State**: Need delayed close + combined hover state for tooltip to remain visible when mouse moves to content