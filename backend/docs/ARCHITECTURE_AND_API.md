# AgentHub — 项目整体架构分析 & API 接口文档

> **版本**: 1.0.0  
> **最后更新**: 2026-05-26  
> **技术栈**: FastAPI + LangChain v1.3 + LangGraph v1.2 + PostgreSQL (pgvector)

---

## 一、项目整体架构分析

### 1.1 分层架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (React + Vite)                             │
│                       Nginx 反向代理 → :8080 后端                            │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │ HTTP/SSE
┌──────────────────────────────────┴──────────────────────────────────────────┐
│                        API 层 (app/api/)                                     │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │  /health    │ │ /api/v1/agents│ │ /api/v1/chat │ │ /api/v1/traces       │ │
│  │  (main.py)  │ │ (CRUD Agent) │ │ (Stream/     │ │ (Kanban Viewer)      │ │
│  │             │ │              │ │  Invoke/Hist)│ │                      │ │
│  └─────────────┘ └──────────────┘ └──────────────┘ └──────────────────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────────────────┐ │
│  │/api/v1/models│ │/api/v1/      │ │       errors.py                      │ │
│  │(Model CRUD)  │ │ providers    │ │  (统一异常处理 + 错误码体系)          │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────────────────┘ │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴──────────────────────────────────────────┐
│                      Service / 业务编排层                                     │
│  ┌────────────────────┐  ┌─────────────────────┐  ┌───────────────────────┐ │
│  │  app/crud/          │  │  app/utils/          │  │  app/observability/   │ │
│  │  agent / chat /     │  │  request_handler     │  │  checkpoint / dag     │ │
│  │  model / provider   │  │  message_utils       │  │  parsers / trace      │ │
│  │  / trace            │  │  stream_events       │  │                       │ │
│  │                     │  │  stream_helpers      │  │                       │ │
│  │  DB 读写 + 业务逻辑  │  │  token_utils         │  │  Trace DAG 持久化      │ │
│  └────────────────────┘  └─────────────────────┘  └───────────────────────┘ │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴──────────────────────────────────────────┐
│                        Agent 层 (app/agents/)                                │
│  ┌──────────────────────────┐  ┌──────────────────────────────────────────┐ │
│  │  registry.py             │  │  factory.py                              │ │
│  │  ┌─────────────────────┐ │  │  AgentSpec (不可变 dataclass)             │ │
│  │  │ RegistrySnapshot    │ │  │  create_standard_agent()                 │ │
│  │  │ (frozen dataclass)  │ │  │    → langchain.agents.create_agent()     │ │
│  │  │ graphs + metadata   │ │  │                                          │ │
│  │  │ 原子替换, 零开销查找 │ │  │  标准中间件链:                           │ │
│  │  └─────────────────────┘ │  │    1. @dynamic_prompt (MD模板渲染)        │ │
│  │                          │  │    2. @wrap_model_call (动态模型切换)     │ │
│  │  register_factory()      │  │    3. SummarizationMiddleware (可选)      │ │
│  │  reload_agents()         │  │                                          │ │
│  │  reload_agent()          │  │                                          │ │
│  │  get_graph()             │  │                                          │ │
│  └──────────────────────────┘  └──────────────────────────────────────────┘ │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  具体 Agent 实现 (app/agents/chatbot/)                                │   │
│  │  chatbot.py — 当前唯一实现, 使用 AgentSpec + create_standard_agent()  │   │
│  │  扩展方式: 新建 app/agents/rag_agent/ → register_factory("rag", ...)  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Middleware (app/agents/middleware/)                                   │   │
│  │  model.py  — @wrap_model_call: 从 context 读取 model_name/thinking    │   │
│  │  prompt.py — @dynamic_prompt: MD 模板加载 + 缓存 + 时间上下文注入      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴──────────────────────────────────────────┐
│                        Tool 层 (app/infra/tools/)                            │
│  ┌─────────────────┐ ┌────────────────┐ ┌─────────────────────────────────┐ │
│  │ time.py         │ │ web.py         │ │ vectorstore_retriever.py         │ │
│  │ 获取当前时间     │ │ Tavily 搜索    │ │ pgvector 向量检索                │ │
│  │ (无外部依赖)     │ │ (需 API Key)   │ │ (需 embedding 模型)              │ │
│  └─────────────────┘ └────────────────┘ └─────────────────────────────────┘ │
│  ┌─────────────────┐                                                        │
│  │ execute_sql_    │  SQL 查询工具 (只读 SELECT, 参数化安全)                │
│  │ query.py         │                                                       │
│  └─────────────────┘                                                        │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴──────────────────────────────────────────┐
│                     Memory / Storage 层 (app/infra/database/)                │
│  ┌─────────────────────────┐ ┌──────────────────┐ ┌───────────────────────┐ │
│  │ postgres/database.py    │ │ postgres/        │ │ postgres/store.py     │ │
│  │ SQLAlchemy async session │ │ vectorstore.py   │ │ LangGraph BaseStore   │ │
│  │ (asyncpg + psycopg)     │ │ PGVector (RAG)   │ │ (长期记忆存储)         │ │
│  ├─────────────────────────┤ └──────────────────┘ └───────────────────────┘ │
│  │ postgres/checkpointer.py│                                                │
│  │ AsyncPostgresSaver       │ ┌──────────────────────────────────────────┐  │
│  │ (对话状态持久化)          │ │ factory.py                              │  │
│  └─────────────────────────┘ │ init_database / init_vectorstore /       │  │
│                               │ init_checkpointer / init_store /         │  │
│                               │ dispose_all                              │  │
│                               └──────────────────────────────────────────┘  │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴──────────────────────────────────────────┐
│                        LLM 层 (app/infra/llm/)                               │
│  ┌─────────────────────────┐ ┌──────────────────┐ ┌──────────────────────┐ │
│  │ model_manager.py        │ │ factory.py       │ │ system.py            │ │
│  │ LiteLLM Router 管理      │ │ get_llm()        │ │ 系统默认 LLM         │ │
│  │ 模型加载 / 刷新 / 查询   │ │ Router + fallback │ │ (title生成等)        │ │
│  │ 默认模型 / Thinking Mode │ │ + retry 一体     │ │                      │ │
│  └─────────────────────────┘ └──────────────────┘ └──────────────────────┘ │
│  ┌─────────────────────────┐                                                │
│  │ extra_body.py           │  Provider 特定参数注入                         │
│  │ (thinking.enabled 等)   │  (Doubao/Zhipu/DashScope/Ollama)               │
│  └─────────────────────────┘                                                │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴──────────────────────────────────────────┐
│                         Config 层                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  app/infra/config.py (pydantic-settings)                             │   │
│  │  Settings: MODE / PostgreSQL / PGVector / CORS / LangSmith / LLM     │   │
│  │  @lru_cache — 全局单例, 验证器链确保配置完整                           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### 1.2 核心模块与文件依赖关系

```
main.py (FastAPI 入口)
├── lifespan (async context manager)
│   ├── init_all()              → infra/database/factory.py
│   │   ├── PostgresDatabase    → infra/database/postgres/database.py
│   │   ├── PostgresVectorStore → infra/database/postgres/vectorstore.py
│   │   ├── PostgresCheckPointer→ infra/database/postgres/checkpointer.py
│   │   └── PostgresStore       → infra/database/postgres/store.py
│   ├── ModelManager.refresh()  → infra/llm/model_manager.py
│   └── reload_agents()         → agents/registry.py
│       ├── 读取 agents 表 → models/agent.py
│       ├── factory(checkpointer, store) → agents/chatbot/chatbot.py
│       └── 原子替换 RegistrySnapshot
├── register_exception_handlers → api/errors.py
└── include_router(api_router)  → api/v1/router.py
    ├── agent.api_router        → api/v1/agent.py
    │   ├── GET  /agents/       → registry.list_metadata()
    │   ├── GET  /agents/{id}   → registry.get_metadata()
    │   └── PATCH /agents/{id}  → DB + registry.reload_agent()
    ├── chat.api_router         → api/v1/chat.py
    │   ├── POST /chat/stream   → stream.py::streaming_message_generator()
    │   │   ├── build_agent_kwargs()  → utils/request_handler.py
    │   │   ├── agent.astream_events(v3)
    │   │   ├── _consume_messages_projection()
    │   │   ├── _consume_tool_calls_projection()
    │   │   └── persist_tokens_and_dag() → observability/
    │   ├── POST /chat/invoke   → agent.ainvoke()
    │   └── GET  /chat/history  → checkpointer.aget_state() + trace_crud
    ├── chat_title.api_router   → api/v1/chat_title.py
    │   ├── GET  /chat/title/{thread_id}
    │   ├── POST /chat/title
    │   └── POST /chat/title/generate → LLM 自动生成标题
    ├── chat_session.api_router → api/v1/chat_session.py
    │   ├── GET    /chat/conversations
    │   ├── POST   /chat/conversations
    │   ├── DELETE /chat/conversations/{thread_id}
    │   ├── GET    /chat/stats/daily
    │   └── GET    /chat/thinking-mode
    ├── model.api_router        → api/v1/model.py
    │   ├── GET  /models/       → crud/model.py
    │   ├── GET  /models/all
    │   ├── POST /models/       → ModelManager.refresh()
    │   ├── POST /models/update
    │   ├── POST /models/delete
    │   └── POST /models/set-default
    ├── provider.api_router     → api/v1/provider.py
    │   ├── GET  /providers/    → crud/provider.py
    │   └── POST /providers/update → encrypt_api_key() + ModelManager.refresh()
    └── trace.api_router        → api/v1/trace.py
        ├── GET /traces                    → trace_executions 表
        ├── GET /traces/{thread_id}/steps
        ├── GET /traces/{thread_id}/dag
        ├── GET /traces/{thread_id}/steps/{n}
        ├── GET /traces/{thread_id}/checkpoints/{ckpt}
        └── GET /traces/{thread_id}/replay
```

---

### 1.3 技术栈与关键依赖

| 层级 | 技术 / 库 | 版本 | 用途 |
|------|----------|------|------|
| **Web 框架** | FastAPI | 0.121.2 | 提供 REST + SSE 接口, 内置 OpenAPI 文档 |
| **ASGI 服务器** | Uvicorn | 0.38.0 | 高性能 ASGI, 支持 async/await |
| **Agent 框架** | LangChain | 1.3.1 | 统一 LLM 接口 + 中间件体系 |
| | LangGraph | 1.2.0 | 有状态的 Agent 图执行引擎 |
| | langchain-litellm | 0.6.5 | LiteLLM Router 集成 (fallback + retry) |
| **LLM 网关** | LiteLLM (via langchain-litellm) | — | 统一多 Provider 接入, 内置 fallback/retry |
| **Checkpoint** | langgraph-checkpoint-postgres | 3.1.0 | AsyncPostgresSaver (对话状态持久化) |
| **向量存储** | langchain-postgres | 0.0.17 | PGVector (向量检索) |
| **搜索工具** | langchain-tavily | 0.2.18 | Tavily Web Search API |
| **数据库** | asyncpg | 0.31.0 | PostgreSQL 异步驱动 (连接池) |
| | psycopg-binary | 3.3.2 | PostgreSQL 同步驱动 (LiteLLM 内部) |
| **加密** | cryptography | 46.0.7 | API Key AES-256 加密存储 |
| **缓存** | cachetools | 5.5.0 | TTLCache (提示词模板缓存) |
| **配置** | pydantic-settings | — | .env 文件加载 + 多环境验证 |
| **可观测性** | LangSmith | 0.8.5 | 开发环境 Tracing (生产禁用) |

---

### 1.4 设计模式与关键决策

| 决策 | 说明 |
|------|------|
| **AgentSpec (不可变 dataclass)** | 新 Agent 只需定义 tools_factory + agent_id，无 copy-paste 中间件 |
| **RegistrySnapshot (frozen dataclass + 原子替换)** | 编译后的 graph 缓存, lookup 是零开销 dict 读取 |
| **@wrap_model_call 中间件** | 从 AgentRuntimeContext 读 model_name → 动态切换 LLM，LiteLLM Router 内置 fallback |
| **@dynamic_prompt 中间件** | MD 模板缓存 300s TTL, 渲染 `{current_datetime}` 等上下文变量 |
| **SummarizationMiddleware** | tokens > 4000 时自动摘要, 保留最近 20 条消息 |
| **Event-driven SSE 消费** | asyncio.Queue + sentinel 模式 零轮询延迟 |
| **API Key 加密存储** | AES-256 加密入库, API_KEY_ENCRYPTION_KEY 必填 |
| **Trace 持久化与 Agent 解耦** | trace_executions 表独立查询, 不依赖 Agent 存活 |
| **Dev/Prod 模式分离** | MODE=prod 禁用 LangSmith, MODE=dev 允许 |

---

## 二、API 接口文档

### 2.1 路由总览

所有 API v1 路由统一挂载在 `/api/v1` 前缀下, 由 `api/v1/router.py` 注册。加上 `main.py` 中直接定义的 `/health` 端点, 完整路由表如下:

| # | 路由前缀 | 文件 | 核心功能 | 优先级 |
|---|---------|------|---------|--------|
| 1 | `GET /health` | main.py | 健康检查 (K8s liveness probe) | 🔴 必须保留 |
| 2 | `/api/v1/agents` | api/v1/agent.py | Agent 发现与管理 | 🟡 必须保留 |
| 3 | `/api/v1/chat` | api/v1/chat.py | 核心对话 (stream + invoke) | 🔴 必须保留 |
| 4 | `/api/v1/chat` | api/v1/chat_session.py | 会话管理 (CRUD + 统计) | 🟡 必须保留 |
| 5 | `/api/v1/chat` | api/v1/chat_title.py | 标题管理 + 自动生成 | 🟢 建议保留 |
| 6 | `/api/v1/models` | api/v1/model.py | 模型 CRUD + 默认模型设置 | 🟡 必须保留 |
| 7 | `/api/v1/providers` | api/v1/provider.py | Provider API Key 管理 | 🟡 必须保留 |
| 8 | `/api/v1/traces` | api/v1/trace.py | Trace 看板 (DAG + Steps) | 🟢 建议保留 |

---

### 2.2 详细接口文档

#### 2.2.1 健康检查

```
GET /health
```

**功能**: 验证数据库连通性, 用于 Docker HEALTHCHECK 和 K8s liveness probe。

**响应**:
- `200 OK`:
  ```json
  {
    "status": "healthy",
    "database": "ok"
  }
  ```
- `503 Service Unavailable`:
  ```json
  {
    "detail": "database_unhealthy"
  }
  ```

**业务逻辑**: 执行 `SELECT 1` 轻量查询验证 asyncpg 连接池可用。

---

#### 2.2.2 Agent 发现与管理

##### GET /api/v1/agents/
**功能**: 列出所有激活的 Agent (从内存缓存零 DB 查询读取)。

**请求参数**: 无

**响应** (`200 OK`):
```json
{
  "agents": [
    {
      "agent_id": "chatbot",
      "description": "A simple chatbot with time and web search",
      "is_active": true,
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ],
  "total": 1,
  "timestamp": "2026-05-26T07:00:00Z"
}
```

**涉及的 Agent 类型**: 所有 `is_active=True` 的 Agent (当前: chatbot)

---

##### GET /api/v1/agents/{agent_id}
**功能**: 获取单个 Agent 的元数据。

**路径参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agent_id | string | ✅ | Agent 唯一标识 |

**响应** (`200 OK`):
```json
{
  "agent_id": "chatbot",
  "description": "A simple chatbot with time and web search",
  "is_active": true,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

**错误**: `404` — Agent 未找到或未激活

---

##### PATCH /api/v1/agents/{agent_id}
**功能**: 更新 Agent 的 DB 记录并触发缓存热重载 (支持在线/离线切换)。

**路径参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agent_id | string | ✅ | Agent 唯一标识 |

**请求体** (JSON, 所有字段可选):
```json
{
  "description": "Updated description",
  "is_active": false
}
```

**响应** (`200 OK`): 同 `GET /agents/{agent_id}` 响应格式

**业务逻辑**: DB flush → refresh → `reload_agent()` (编译新 graph 或从缓存移除)。`is_active=false` → Agent 立即下线。

---

#### 2.2.3 核心对话 (Stream + Invoke)

##### POST /api/v1/chat/stream
**功能**: SSE 流式 Agent 响应 — **核心接口**。

**请求体** (`UserInput`):
```json
{
  "content": "What is the weather in Hefei?",
  "agent_id": "chatbot",
  "user_id": "user-123",
  "thread_id": "f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c",
  "request_id": "req-abc-123",
  "model_name": "dashscope/qwen3.5-27b",
  "thinking_mode": false,
  "timezone": "Asia/Shanghai",
  "custom_data": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| content | string | ✅ | 用户输入内容 |
| agent_id | string | ✅ | 目标 Agent ID |
| user_id | string | ✅ | 用户标识 (多租户) |
| thread_id | UUID | ✅ | 对话线程 ID (多轮记忆) |
| request_id | string | ✅ | 请求追踪 ID (幂等) |
| model_name | string? | ❌ | 覆盖默认模型 (provider/model-id) |
| thinking_mode | bool | ❌ | 启用深度思考模式 (默认 false) |
| timezone | string | ❌ | IANA 时区 (默认 Asia/Shanghai) |
| custom_data | object? | ❌ | 自定义数据 (如引用消息) |

**响应** (`200 OK`, `Content-Type: text/event-stream`):
```
data: {"type":"step","step":1,"action":"human","content":"What is..."}

data: {"type":"token","content":"The"}

data: {"type":"token","content":" weather"}

data: {"type":"step","step":2,"action":"tool_call","name":"get_current_time","status":"calling"}

data: {"type":"step","step":2,"action":"tool_result","status":"completed"}

data: {"type":"step","step":3,"action":"ai_thinking","status":"thinking..."}

data: {"type":"token","content":" in"}

data: {"type":"token","content":" Hefei..."}

data: {"type":"usage","content":{"node":"model","usage":{"input_tokens":150,"output_tokens":80,"total_tokens":230}}}

data: {"type":"message","content":{...}}

data: [DONE]
```

**SSE 事件类型**:
| type | 说明 |
|------|------|
| `token` | LLM 逐 token 增量输出 |
| `reasoning` | 思考模型推理过程 (DeepSeek-R1/Qwen3 等) |
| `step` | 执行步骤通知 (human / tool_call / tool_result / ai_thinking) |
| `usage` | Token 用量统计 (按 node) |
| `message` | 最终组装消息 |

**业务逻辑**: 
1. `resolve_model_name()` → 模型回退链
2. `build_agent_kwargs()` → 构建 AgentRuntimeContext
3. `agent.astream_events(version="v3")` → v3 投影流
4. 3 个消费者协程并发: `stream.messages` / `stream.tool_calls` / `stream.values`
5. asyncio.Queue + sentinel 零轮询 drain
6. 流结束后异步持久化 token 用量 + DAG

**涉及的 Agent 类型**: 所有已编译的 Agent (当前: chatbot, 含时间查询 + 网页搜索工具)

---

##### POST /api/v1/chat/invoke
**功能**: 异步单次 Agent 调用 (非流式) — **核心接口**。

**请求体**: 同 `POST /chat/stream` 的 `UserInput`

**响应** (`200 OK`):
```json
{
  "type": "ai",
  "content": "The weather in Hefei today is sunny, 25°C.",
  "tool_calls": [],
  "tool_call_id": null,
  "name": null,
  "run_id": "847c6285-8fc9-4560-a83f-4e6285809254",
  "response_metadata": {},
  "custom_data": {}
}
```

**业务逻辑**: 
1. `agent.ainvoke(stream_mode=["updates", "values"])`
2. 从 `response_events[-1]` 提取最终输出
3. 遍历所有 AI 消息累积 token 用量
4. `persist_tokens_and_dag()` 持久化

---

##### GET /api/v1/chat/history/{agent_id}/{thread_id}
**功能**: 获取对话历史 (主聊天 UI + 侧边栏步骤序列)。

**路径参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agent_id | string | ✅ | Agent ID |
| thread_id | UUID | ✅ | 对话线程 ID |

**响应** (`200 OK`):
```json
{
  "messages": [
    {"type": "human", "content": "Hi", "tool_calls": [], ...},
    {"type": "ai", "content": "Hello! How can I help?", "tool_calls": [], ...}
  ],
  "message_sequence": [
    {
      "step_number": 1,
      "message_type": "human",
      "content": "Hi",
      ...
    },
    {
      "step_number": 2,
      "message_type": "ai",
      "content": "Hello!",
      "ai_metadata": {"model_name": "qwen3.5-27b", ...},
      ...
    }
  ]
}
```

**数据来源**:
- `messages`: LangGraph checkpointer (`AsyncPostgresSaver`) → `agent.aget_state()`
- `message_sequence`: `trace_executions` 表 (持久化 DAG)

---

##### GET /api/v1/chat/conversation-info/{thread_id}
**功能**: 获取历史对话的最后使用 Agent 和模型 (进入历史对话时使用)。

**路径参数**: `thread_id` (UUID)

**Query 参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | ✅ | 用户 ID (验证所有权) |

**响应** (`200 OK`):
```json
{
  "agent_id": "chatbot",
  "model_name": "dashscope/qwen3.5-27b",
  "model_fallback": false
}
```

**业务逻辑**: 从 `trace_executions` 读取最近一次模型 → 验证模型是否仍活跃 → 必要时回退到默认模型 → `model_fallback=true`

---

#### 2.2.4 会话管理

##### GET /api/v1/chat/conversations
**功能**: 获取用户会话列表 (分页, 按更新时间倒序)。

**Query 参数**:
| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| user_id | string | ✅ | — | 用户 ID |
| limit | int (1-100) | ❌ | 20 | 每页数量 |
| offset | int (≥0) | ❌ | 0 | 跳过条数 |

**响应** (`200 OK`, Header: `X-Total-Count`):
```json
[
  {
    "thread_id": "f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c",
    "user_id": "user-123",
    "title": "Weather Inquiry",
    "agent_id": "chatbot",
    "created_at": "2026-05-26T06:00:00Z",
    "updated_at": "2026-05-26T06:05:00Z",
    "is_deleted": false,
    "input_tokens": 500,
    "cache_read": 0,
    "output_tokens": 300,
    "reasoning": 0,
    "total_tokens": 800
  }
]
```

---

##### POST /api/v1/chat/conversations
**功能**: 创建新会话。

**Query 参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | ✅ | 用户 ID |

**请求体**:
```json
{
  "thread_id": "f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c",
  "user_id": "user-123",
  "title": "New Chat",
  "agent_id": "chatbot"
}
```

**响应**: 同 `GET /conversations` 单项格式

---

##### DELETE /api/v1/chat/conversations/{thread_id}
**功能**: 软删除会话。

**路径参数**: `thread_id` (UUID)

**Query 参数**: `user_id` (string, ✅)

**响应**: `204 No Content`

---

##### GET /api/v1/chat/stats/daily
**功能**: 获取每日对话统计 (含 token 用量)。

**Query 参数**:
| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| days | int (1-365) | ❌ | 30 | 统计天数 |
| user_id | string? | ❌ | null | 用户过滤 |

**响应** (`200 OK`):
```json
[
  {
    "date": "2026-05-26",
    "conversation_count": 5,
    "input_tokens": 2500,
    "cache_read": 0,
    "output_tokens": 1500,
    "reasoning": 100,
    "total_tokens": 4100
  }
]
```

---

##### GET /api/v1/chat/thinking-mode
**功能**: 检查是否有支持深度思考模式的模型可用。

**响应** (`200 OK`):
```json
{
  "available": true
}
```

---

#### 2.2.5 标题管理

##### GET /api/v1/chat/title/{thread_id}
**功能**: 获取会话标题。

**路径参数**: `thread_id` (UUID)

**Query 参数**: `user_id` (string, ✅)

**响应**: `ConversationInDB` 格式

---

##### POST /api/v1/chat/title
**功能**: 手动设置/更新会话标题。

**Query 参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| thread_id | UUID | ✅ | 线程 ID |
| user_id | string | ✅ | 用户 ID |

**请求体**:
```json
{
  "title": "New Title"
}
```

---

##### POST /api/v1/chat/title/generate
**功能**: 使用系统默认 LLM 自动生成会话标题 (max 20 字符, 同语言)。

**请求体**:
```json
{
  "user_message": "What is the weather in Beijing?",
  "ai_response": "The weather in Beijing is sunny, 25°C."
}
```

**响应** (`200 OK`):
```json
{
  "title": "Beijing Weather"
}
```

**业务逻辑**: 
- SystemMessage + HumanMessage 分离 → 防止 prompt injection
- 用户输入截断至 200 字符
- 回退策略: 调用失败时截取用户消息前 30 字符作为标题

---

#### 2.2.6 模型管理

##### GET /api/v1/models/
**功能**: 获取可用于前端下拉框的模型列表 (仅返回已配置 API Key 的 Provider 模型)。

**响应** (`200 OK`):
```json
{
  "models": [
    {
      "id": "uuid-1",
      "provider": "dashscope",
      "model_type": "llm",
      "model_id": "dashscope/qwen3.5-27b",
      "thinking": false,
      "priority": 0,
      "is_default": true,
      "is_active": true,
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ],
  "default_llm": "uuid-1",
  "default_vlm": null,
  "default_embedding": null
}
```

---

##### GET /api/v1/models/all
**功能**: 获取所有模型 (含未配置 API Key 的, 用于配置页面)。

**响应**: 同 `GET /models/` 格式

---

##### POST /api/v1/models/
**功能**: 创建新模型。

**请求体**:
```json
{
  "provider": "dashscope",
  "model_type": "llm",
  "model_id": "dashscope/qwen3.5-27b",
  "thinking": false,
  "priority": 0,
  "is_default": false,
  "is_active": true
}
```

**响应**: `201 Created`, `ModelInfo` 格式

**业务逻辑**: 创建后自动 `ModelManager.refresh()` 更新 LiteLLM Router。

---

##### POST /api/v1/models/update
**功能**: 更新模型配置 (含启用/禁用)。

**请求体**:
```json
{
  "id": "uuid-1",
  "is_active": false,
  "is_default": true
}
```

**业务逻辑**: 设置 `is_default` 时使用原子 `CASE` SQL 清空同类型其他默认模型。

---

##### POST /api/v1/models/delete
**功能**: 删除模型。
**请求体**: `{"id": "uuid-1"}`
**响应**: `204 No Content`

---

##### POST /api/v1/models/set-default
**功能**: 设置某模型的默认状态。

**请求体**: `{"id": "uuid-1"}`
**响应**: `ModelInfo`

**业务逻辑**: 原子 CASE 语句 → 同类型其他模型 `is_default=false`

---

#### 2.2.7 Provider 管理

##### GET /api/v1/providers/
**功能**: 获取所有 Provider 及其配置状态。

**响应** (`200 OK`):
```json
{
  "providers": [
    {
      "provider": "dashscope",
      "has_api_key": true,
      "base_url": null,
      "is_openai_compatible": false,
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

---

##### POST /api/v1/providers/update
**功能**: 更新 Provider 的 API Key 和/或 Base URL。

**请求体**:
```json
{
  "provider": "dashscope",
  "api_key": "sk-xxx",
  "base_url": null
}
```

**业务逻辑**: 
- `encrypt_api_key()` → AES-256 加密后存储
- 更新后自动 `ModelManager.refresh()` (重新构建 LiteLLM Router)

---

#### 2.2.8 Trace 看板

##### GET /api/v1/traces
**功能**: 分页列出 Trace 记录 (Kanban 列表)。

**Query 参数**:
| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| page | int (≥0) | ❌ | 0 | 页码 (0-indexed) |
| page_size | int (1-100) | ❌ | 10 | 每页数量 |
| hours | int (1-168) | ❌ | 24 | 时间过滤 (最近 N 小时) |
| agent_id | string | ❌ | "all" | Agent 过滤 |
| user_id | string | ✅ | — | 用户 ID |

**响应** (`200 OK`):
```json
{
  "items": [
    {
      "thread_id": "f47ac10b-...",
      "title": "Weather Inquiry",
      "total_steps": 5,
      "total_latency_ms": 0,
      "last_updated": "2026-05-26T07:00:00Z",
      "agent_id": "chatbot"
    }
  ],
  "total": 100,
  "total_pages": 10,
  "page": 0,
  "page_size": 10,
  "has_more": true,
  "filter_hours": 24
}
```

**业务逻辑**: 从 `conversations` 表 + `trace_executions` 表联合查询, **不依赖 Agent 图编译**。

---

##### GET /api/v1/traces/{thread_id}/steps
**功能**: 获取某线程的所有执行步骤。

**路径参数**: `thread_id` (UUID)

**Query 参数**: `user_id` (string, ✅), `agent_id` (string, ❌, 默认 "all")

**响应** (`200 OK`):
```json
[
  {
    "step_number": 1,
    "message_type": "human",
    "content": "What is the weather?",
    "timestamp": "2026-05-26T06:00:00Z",
    ...
  },
  {
    "step_number": 2,
    "message_type": "ai",
    "content": "The weather is sunny.",
    "ai_metadata": {"model_name": "qwen3.5-27b", ...},
    ...
  }
]
```

---

##### GET /api/v1/traces/{thread_id}/dag
**功能**: 获取执行 DAG (节点 + 边, 用于可视化)。

**响应** (`200 OK`):
```json
{
  "thread_id": "f47ac10b-...",
  "nodes": [
    {
      "node_id": "node-1",
      "step_number": 1,
      "node_name": "__start__",
      "title": "Human Input",
      "message_type": "human",
      "step": { ... }
    }
  ],
  "edges": [["node-1", "node-2"]],
  "total_steps": 5,
  "steps": [ ... ]
}
```

---

##### GET /api/v1/traces/{thread_id}/steps/{step_number}
**功能**: 按步骤编号获取单步详情。

##### GET /api/v1/traces/{thread_id}/checkpoints/{checkpoint_id}
**功能**: 按 checkpoint ID 获取单步详情。

##### GET /api/v1/traces/{thread_id}/replay
**功能**: 回放指定步骤范围。

**Query 参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| from_step | int (≥1) | ❌ | 起始步骤 (默认 1) |
| to_step | int? | ❌ | 结束步骤 |

---

### 2.3 核心接口标注

| 优先级 | 标识 | 接口 | 原因 |
|--------|------|------|------|
| 🔴 必须保留 | P0 | `GET /health` | 运维基础设施, K8s/Docker 健康检查依赖 |
| 🔴 必须保留 | P0 | `POST /chat/stream` | **核心业务接口** — 所有用户对话通过此接口完成, SSE 流式输出 |
| 🔴 必须保留 | P0 | `POST /chat/invoke` | **核心业务接口** — 非流式 Agent 调用, 用于批处理/后台场景 |
| 🟡 必须保留 | P1 | `GET /chat/history` | 前端进入历史对话必需, 含消息列表 + 步骤序列 |
| 🟡 必须保留 | P1 | `GET /chat/conversations` | 前端侧边栏会话列表, UI 核心组件 |
| 🟡 必须保留 | P1 | `POST /chat/conversations` | 创建新会话, 前端入口操作 |
| 🟡 必须保留 | P1 | `DELETE /chat/conversations/{id}` | 删除会话 |
| 🟡 必须保留 | P1 | `GET /chat/conversation-info/{id}` | 进入历史对话时恢复上次模型/Agent |
| 🟡 必须保留 | P1 | `GET /agents/` + `GET /agents/{id}` | Agent 发现, 前端 Agent 选择器依赖 |
| 🟡 必须保留 | P1 | `PATCH /agents/{id}` | Agent 在线/下线管理 |
| 🟡 必须保留 | P1 | `GET /models/` + `GET /models/all` | 模型选择器 + 配置页 |
| 🟡 必须保留 | P1 | `POST /models/*` | 模型 CRUD, 管理员必需 |
| 🟡 必须保留 | P1 | `GET /providers/` + `POST /providers/update` | API Key 配置, 管理员必需 |
| 🟢 建议保留 | P2 | `GET /chat/title/*` | 标题管理 + 自动生成, 提升 UX |
| 🟢 建议保留 | P2 | `GET /chat/stats/daily` | 使用统计, Dashboard |
| 🟢 建议保留 | P2 | `GET /chat/thinking-mode` | 前端判断是否显示思考模式开关 |
| 🟢 建议保留 | P2 | `GET /traces/*` | Trace Kanban 看板, 调试/审计 |

---

### 2.4 统一错误响应格式

所有 API 错误由 `api/errors.py` 统一处理, 返回格式:

```json
{
  "detail": "Agent 'unknown' not found or not active",
  "error_code": "AGENT_NOT_FOUND",
  "status_code": 404
}
```

**全局异常映射**:
| 异常类型 | HTTP 状态码 |
|---------|------------|
| `AgentNotFoundError` | 404 |
| `HTTPException` | 按 raise 时指定 |
| `ValueError` | 422 |
| `ValidationError` (Pydantic) | 422 |
| 未捕获异常 | 500 (dev 模式含 traceback) |

---

## 三、项目结构速查

```
backend/
├── app/
│   ├── main.py                    # FastAPI 入口, lifespan, /health
│   ├── api/
│   │   ├── errors.py              # 统一异常处理
│   │   └── v1/
│   │       ├── router.py          # 路由聚合
│   │       ├── agent.py           # Agent 发现 API
│   │       ├── chat.py            # 核心对话 API (stream + invoke + history)
│   │       ├── chat_session.py    # 会话管理 API
│   │       ├── chat_title.py      # 标题 API
│   │       ├── stream.py          # SSE 流式引擎 (astream_events v3)
│   │       ├── model.py           # 模型管理 API
│   │       ├── provider.py        # Provider 管理 API
│   │       ├── trace.py           # Trace 看板 API
│   │       └── dependencies.py    # FastAPI Depends (get_db)
│   ├── agents/
│   │   ├── registry.py            # Agent 注册表 (RegistrySnapshot + 原子替换)
│   │   ├── types.py               # AgentRuntimeContext (共享 dataclass)
│   │   ├── factory.py             # AgentSpec + create_standard_agent()
│   │   ├── chatbot/
│   │   │   ├── chatbot.py         # Chatbot Agent 实现
│   │   │   └── types.py           # ChatbotContext (继承 AgentRuntimeContext)
│   │   └── middleware/
│   │       ├── model.py           # @wrap_model_call (动态模型切换)
│   │       └── prompt.py          # @dynamic_prompt (MD 模板注入)
│   ├── schemas/
│   │   ├── chat.py                # UserInput, ChatMessage, ChatHistory, ...
│   │   ├── agent.py               # AgentResponse, AgentListResponse
│   │   ├── model.py               # ModelInfo, ModelsResponse
│   │   ├── provider.py            # ProviderInfo, ProvidersResponse
│   │   ├── trace.py               # StepOutput, ExecutionDag, TraceListResponse
│   │   └── interrupt_message.py   # 中断消息 schema
│   ├── models/
│   │   ├── base.py                # SQLAlchemy Base + 工具函数
│   │   ├── agent.py               # Agent ORM Model
│   │   ├── chat.py                # Conversation ORM Model
│   │   ├── model.py               # Model ORM Model
│   │   ├── provider.py            # Provider ORM Model
│   │   └── trace.py               # TraceExecution ORM Model
│   ├── crud/
│   │   ├── agent.py               # Agent 数据库操作
│   │   ├── chat.py                # Conversation 数据库操作
│   │   ├── model.py               # Model 数据库操作
│   │   ├── provider.py            # Provider 数据库操作
│   │   └── trace.py               # Trace 数据库操作
│   ├── infra/
│   │   ├── config.py              # Settings (pydantic-settings, cached)
│   │   ├── database/
│   │   │   ├── factory.py         # init_all / dispose_all / get_xxx
│   │   │   ├── base.py            # 数据库基类
│   │   │   └── postgres/
│   │   │       ├── database.py    # PostgresDatabase (asyncpg 连接池)
│   │   │       ├── vectorstore.py # PostgresVectorStore (pgvector)
│   │   │       ├── checkpointer.py# PostgresCheckPointer (AsyncPostgresSaver)
│   │   │       └── store.py       # PostgresStore (LangGraph BaseStore)
│   │   ├── llm/
│   │   │   ├── __init__.py        # get_llm, get_system_default_llm
│   │   │   ├── factory.py         # LiteLLM Router 工厂 (fallback + retry)
│   │   │   ├── model_manager.py   # ModelManager (DB → Router 同步)
│   │   │   ├── system.py          # 系统默认 LLM 获取
│   │   │   └── extra_body.py      # Provider 特定 extra_body 注入
│   │   └── tools/
│   │       ├── time.py            # 当前时间工具
│   │       ├── web.py             # Tavily 网页搜索工具
│   │       ├── vectorstore_retriever.py  # pgvector 向量检索工具
│   │       └── execute_sql_query.py      # SQL 查询工具
│   ├── observability/
│   │   ├── checkpoint.py          # Checkpoint 数据提取
│   │   ├── dag.py                 # DAG 构建 (节点 + 边)
│   │   ├── parsers.py             # 数据解析器
│   │   └── trace.py               # Trace 持久化
│   ├── prompts/
│   │   └── chatbot.md             # Chatbot 系统提示词模板
│   └── utils/
│       ├── request_handler.py     # build_agent_kwargs (UserInput → Agent input)
│       ├── message_utils.py       # LangChain message ↔ ChatMessage 转换
│       ├── stream_events.py       # SSE 格式化工具 (sse / sse_error)
│       ├── stream_helpers.py      # 模型名解析 + token/DAG 持久化
│       ├── token_utils.py         # Token 提取/累积工具
│       ├── async_writer.py        # 异步写入队列
│       ├── cache.py               # TTLCache 封装
│       └── crypto.py              # encrypt_api_key / decrypt_api_key
├── requirements.txt               # Python 依赖
├── Dockerfile                     # 生产镜像
├── docker-compose.yml             # 本地开发
├── .env.example                   # 环境变量模板
├── entrypoint.sh                  # 容器启动脚本
└── scripts/
    └── init_database.py           # 数据库初始化 (建表 + 种子数据)
```

---

> **文档说明**: 本文档基于 2026-05-26 代码快照生成, 涵盖 `backend/app/` 全部模块。新 Agent (RAG, 多 Agent 协作等) 添加时, 仅需在 `agents/` 下新增目录、实现 factory、调用 `register_factory()`, DB 插入 `is_active=True` 行即可自动上线。无需修改 API 层或注册表。