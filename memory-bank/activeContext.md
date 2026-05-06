# Active Context

## Current Work Focus

TODO.md 审查报告更新 — 对比当前实现与优化蓝图，标注已完成项和新增待办。

## Recent Changes

### TODO.md V8 审查更新 (2026-05-05)
- **审查范围**：全面对比 TODO.md V7 与当前后端代码实现
- **已完成项标注**：
  - ✅ Agent Registry 装饰器模式（`app/agents/base.py`）
  - ✅ 标准图构建工厂（`build_standard_agent_graph()`）
  - ✅ 流式基础架构（`astream_events` v2）
- **新增待办项**：
  - ❌ Agent 元数据系统（display_name, description, keywords）
  - ❌ Hybrid Router（关键词 + LLM 兜底路由）
  - ❌ AsyncWriteQueue 异步写入队列
  - ❌ ModelManager.acompletion() 统一调用入口
  - ❌ LiteLLM Router Fallback + 重试机制
- **版本评分调整**：99/100 → 85/100（反映实际进度）
- **实施里程碑**：保留 3 天开发计划，明确任务优先级

### Model Configuration API Key Validation (2026-04-30)
- **Strong validation rule**: Can only add/edit models AFTER provider API key is successfully saved
- **Disabled buttons when no API key saved**:
  - "Add Model" button (initial state)
  - "Continue Add" button (when new model forms exist)
  - Model edit (pencil) button on each model card
- **Tooltip hints**: Hovering disabled buttons shows "Please save the API Key first before adding/editing models"
- **Empty list message**: Shows different messages based on API key status — guides user to save API key first
- **Validation logic**: Uses `provider.has_api_key` (backend state), NOT frontend input value — ensures key is actually saved before allowing model operations

### Docker Compose Profiles Overhaul (2026-04-28 v3)
- **Profiles-based `docker-compose.yml`**: Three modes — dev (default), prod (`--profile prod`), postgres (`--profile postgres`)
- **Frontend dev & prod both use nginx**: `frontend` service (default) and `frontend-prod` (profile) both use the same multi-stage Dockerfile with nginx. The difference is `frontend-prod` is behind `profiles: ["prod"]` for explicit production targeting.
- **Frontend Dockerfile**: Multi-stage build — Stage 1: `node:24` builds React app; Stage 2: `nginx:stable-alpine3.23-perl` serves static assets. Uses `nginx.conf.template` (envsubst pattern) for dynamic backend proxy config.
- **Build args**: `VITE_API_BASE_URL` (default `/api/v1`), `NGINX_BACKEND_HOST` (default `backend`), `NGINX_BACKEND_PORT` (default `8080`).
- **Named Docker volumes**: `backend-data`, `postgres-data`, `qdrant-data` instead of bind mounts.
- **Non-blocking `depends_on`**: Removed `service_healthy` condition. Frontend just depends on backend starting, not passing health.
- **Optimized healthchecks**: Backend `wget` (interval 10s, timeout 3s, retries 2, start_period 5s). Non-blocking.
- **PostgreSQL + Qdrant**: Both under `profiles: ["postgres"]`. Only start when explicitly requested. PostgreSQL uses `postgres:latest`.
- **Docker network**: `agenthub-network` (bridge) for inter-service communication.
- **README updates**: Both English and Chinese READMEs updated — dev mode no longer described as Vite dev server; both modes described as nginx-based. `nginx.conf.template` documented. `NGINX_BACKEND_HOST` default corrected to `backend`.

### Key Design Decisions
- Docker profiles for flexibility — dev (default, nginx), prod (nginx, explicit profile), postgres (optional DB)
- No blocking healthcheck dependencies — faster startup, no cascading waits
- Both frontend modes use nginx multi-stage build — same Dockerfile, `frontend-prod` just gated behind `profiles: ["prod"]`
- Named volumes over bind mounts for data persistence in Docker

## Next Steps

根据 TODO.md V8 里程碑，按优先级实施：
1. Agent 元数据扩展（前置依赖，0.3 天）
2. Hybrid Router 实现（0.5 天）
3. AsyncWriteQueue 异步写入（0.5 天）
4. ModelManager.acompletion()（0.2 天）
5. LiteLLM Router Fallback + 重试（0.5 天）

## Active Decisions and Considerations

- Agent Registry 已实现，但缺少元数据系统（keywords 用于路由匹配）
- Hybrid Router 采用关键词优先 + LLM 兜底策略
- AsyncWriteQueue 使用 Context Manager 模式确保异常安全
- ModelManager.acompletion() 作为统一非流式调用入口

## Important Patterns and Preferences

- Agent 注册使用装饰器模式（`@register_agent(agent_id)`）
- 标准图构建使用工厂函数（`build_standard_agent_graph()`）
- 流式输出使用 `astream_events` v2 版本
- 路由决策优先关键词匹配（0 延迟），LLM 仅复杂查询时调用