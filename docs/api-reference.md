# AgentHub Backend API 接口文档

> 自动生成于 2026-05-29 | 基于 FastAPI 路由扫描 + 前端 API 调用分析

---

## 目录

- [1. 概览](#1-概览)
- [2. 健康检查](#2-健康检查)
- [3. Chat 模块](#3-chat-模块)
- [4. Models 模块](#4-models-模块)
- [5. Traces 模块](#5-traces-模块)
- [6. 前端 API 使用矩阵](#6-前端-api-使用矩阵)

---

## 1. 概览

| 模块 | 路由前缀 | Endpoint 数量 |
|------|---------|--------------|
| Health | `/` | 1 |
| Chat | `/api/v1/chat` | 12 |
| Models | `/api/v1/models` | 8 |
| Traces | `/api/v1/traces` | 4 |

**总计：25 个 Endpoint**

**认证方式：** 当前版本无全局认证中间件（通过 `user_id` 参数区分用户）。

**全局错误处理：** `app.api.errors.register_exception_handlers` 集中注册。

---

## 2. 健康检查

### `GET /health`

- **Tag:** `Health`
- **描述：** 应用存活探针，返回 `"ok"`。由 Kubernetes / Docker 健康检查使用。
- **请求参数：** 无
- **响应：** `"ok"`（纯文本）
- **前端使用：** ❌ 无

---

## 3. Chat 模块

**路由前缀：** `/api/v1/chat`

**源文件：**
- `backend/app/api/v1/chat/run.py` — 流式/非流式对话
- `backend/app/api/v1/chat/conversation.py` — 会话 CRUD
- `backend/app/api/v1/chat/title.py` — 标题生成
- `backend/app/api/v1/chat/stats.py` — 统计数据
- `backend/app/api/v1/chat/thinking_mode.py` — 思考模式
- `backend/app/api/v1/chat/agents.py` — Agent 列表

---

### 3.1 `POST /api/v1/chat/run/stream`

**描述：** SSE 流式运行 Agent 对话。前端通过 `fetch` + `ReadableStream` 消费。

**请求体 `UserInput`：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `content` | `string` | ✅ | — | 用户输入消息 |
| `user_id` | `string` | ✅ | — | 用户 ID（长期记忆与个性化） |
| `thread_id` | `UUID` | ✅ | — | 会话线程 ID（多轮对话） |
| `request_id` | `string` | ✅ | — | 请求 ID（追踪与幂等性） |
| `model_name` | `string \| null` | ❌ | `null` | 指定模型名 |
| `thinking_mode` | `bool` | ❌ | `false` | 启用思考模式 |
| `timezone` | `string` | ❌ | `"Asia/Shanghai"` | IANA 时区 |
| `custom_data` | `dict \| null` | ❌ | `null` | 自定义数据（如引用消息） |

**示例：**
```json
{
  "content": "今天北京的天气怎么样？",
  "user_id": "user-123",
  "thread_id": "f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c",
  "request_id": "req-abc-123",
  "model_name": "qwen3.5-27b",
  "thinking_mode": false,
  "timezone": "Asia/Shanghai"
}
```

**响应：** `text/event-stream`，每条格式 `data: <JSON>\n\n`

**StreamEvent 类型：**

| type | 描述 |
|------|------|
| `token` | LLM 逐 token 输出 |
| `llm` | LLM 单步完整响应 |
| `tool` | 工具调用开始 |
| `tool_result` | 工具调用结果 |
| `message` | 完整消息（含 metadata） |
| `usage` | Token 用量统计 |
| `error` | 错误信息 |

**涉及的 Agent：** Supervisor Agent → 子 Agent（Chatbot 等），`app.agents.supervisor.init_supervisor`

**关键实现：** `app.api.v1.chat._streaming.stream_agent_response()`, `app.utils.stream_helpers`

**前端调用：** `api.streamChat()`

---

### 3.2 `POST /api/v1/chat/run/invoke`

**描述：** 非流式运行 Agent 对话，返回完整响应。

**请求体：** 同 `UserInput`（见 3.1）

**响应 `ChatMessage`：**
```json
{
  "type": "ai",
  "content": "北京今天晴，25°C...",
  "tool_calls": [],
  "tool_call_id": null,
  "name": null,
  "run_id": "847c6285-8fc9-4560-a83f-4e6285809254",
  "response_metadata": {},
  "custom_data": {}
}
```

**前端调用：** `api.invokeChat()`

---

### 3.3 `GET /api/v1/chat/conversations`

**描述：** 获取用户活跃会话列表。

**Query 参数：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `user_id` | `string` | ✅ | — | 用户 ID |
| `limit` | `int` | ❌ | `50` | 返回数量上限 |
| `offset` | `int` | ❌ | `0` | 分页偏移量 |

**响应 `list[ConversationInDB]`：**
```json
[
  {
    "thread_id": "f47ac10b-...",
    "user_id": "user-123",
    "title": "北京天气查询",
    "created_at": "2026-05-29T00:00:00Z",
    "updated_at": "2026-05-29T08:00:00Z",
    "is_deleted": false,
    "input_tokens": 150,
    "cache_read": 0,
    "output_tokens": 80,
    "reasoning": 0,
    "total_tokens": 230
  }
]
```

**前端调用：** `api.listConversations()`

---

### 3.4 `GET /api/v1/chat/conversations/{thread_id}`

**描述：** 获取指定会话的聊天历史（消息 + 执行序列）。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**响应 `ChatHistory`：**
```json
{
  "messages": [
    { "type": "human", "content": "...", "tool_calls": [], ... },
    { "type": "ai", "content": "...", "tool_calls": [], ... }
  ],
  "message_sequence": [
    {
      "step_number": 1,
      "message_type": "ai",
      "content": "...",
      "timestamp": "2026-05-29T08:00:00Z",
      "message_id": "msg-001",
      "checkpoint_id": "1f0e3f...",
      "node_name": "chatbot",
      "ai_metadata": { "thinking": null, "tool_calls": null, "model_name": "qwen3.5-27b" },
      "tool_metadata": null
    }
  ]
}
```

**前端调用：** `api.getChatHistory()`

---

### 3.5 `GET /api/v1/chat/conversation-info/{thread_id}`

**描述：** 获取会话的模型信息（判断是否发生模型回退）。

**Path 参数：** `thread_id` (UUID)

**响应 `ConversationInfoResponse`：**
```json
{
  "model_name": "qwen3.5-27b",
  "model_fallback": false
}
```

- `model_fallback`: `true` 表示原模型已停用，回退到了默认模型

**前端调用：** `api.getConversationInfo()`

---

### 3.6 `PATCH /api/v1/chat/conversations/{thread_id}`

**描述：** 部分更新会话（标题、软删除标记）。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**请求体 `ConversationUpdate`：**

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `title` | `string \| null` | ❌ | 新标题 (1-64 字符) |
| `is_deleted` | `bool \| null` | ❌ | 软删除标记 |

**响应：** `ConversationInDB`

**前端调用：** `api.updateConversation()`

---

### 3.7 `DELETE /api/v1/chat/conversations/{thread_id}`

**描述：** 硬删除会话。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**响应：** `204 No Content`

**前端调用：** `api.deleteConversation()`

---

### 3.8 `POST /api/v1/chat/title`

**描述：** 自动生成会话标题。

**请求体 `TitleGenerateRequest`：**

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `user_message` | `string` | ✅ | 用户消息 |
| `ai_response` | `string \| null` | ❌ | AI 回复（可选上下文） |

**响应 `TitleGenerateResponse`：**
```json
{ "title": "北京天气查询" }
```

**前端调用：** `api.generateTitle()`

---

### 3.9 `GET /api/v1/chat/thinking-mode`

**描述：** 检查是否支持思考模式。

**响应 `ThinkingModeStatus`：**
```json
{ "available": true }
```

**前端调用：** `api.getThinkingModeStatus()` → `hooks/use-thinking-mode.ts`

---

### 3.10 `GET /api/v1/chat/agents`

**描述：** 获取活跃 Agent 列表。

**响应 `list[AgentInDB]`：**
```json
[
  {
    "agent_id": "chatbot",
    "description": "通用聊天助手",
    "is_active": true,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z"
  }
]
```

**前端调用：** `api.listAgents()`

---

### 3.11 `GET /api/v1/chat/stats/daily`

**描述：** 每日会话数 + Token 用量统计。

**Query 参数：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `days` | `int` | ❌ | `30` | 统计天数 (1-365) |
| `user_id` | `string \| null` | ❌ | `null` | 按用户过滤 |

**响应 `list[DailyStatsItem]`：**
```json
[
  {
    "date": "2026-05-29",
    "conversation_count": 12,
    "input_tokens": 1500,
    "cache_read": 200,
    "output_tokens": 800,
    "reasoning": 100,
    "total_tokens": 2600
  }
]
```

**前端调用：** `api.getDailyStats()`

---

### 3.12 `GET /api/v1/chat/conversations/{thread_id}/stats`

**描述：** 单会话累计 Token 用量。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**响应：** `ConversationInDB`

**前端调用：** `api.getConversationStats()`

---

## 4. Models 模块

**路由前缀：** `/api/v1/models`

**源文件：**
- `backend/app/api/v1/models/models.py` — 模型 CRUD
- `backend/app/api/v1/models/providers.py` — 提供商管理

---

### 4.1 `GET /api/v1/models`

**描述：** 获取所有模型 + 默认模型。

**响应 `ModelsResponse`：**
```json
{
  "models": [
    {
      "id": "uuid-001",
      "provider": "dashscope",
      "model_type": "llm",
      "model_id": "dashscope/qwen3.5-27b",
      "thinking": true,
      "priority": 10,
      "is_default": true,
      "is_active": true,
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ],
  "default_llm": "uuid-001",
  "default_vlm": "uuid-002",
  "default_embedding": "uuid-003"
}
```

**前端调用：** `hooks/use-models.ts` → `getAvailableModels()`

---

### 4.2 `POST /api/v1/models`

**描述：** 创建新模型配置。

**请求体 `ModelCreate`：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `provider` | `string` | ✅ | — | 提供商 (e.g. `dashscope`, `zai`) |
| `model_type` | `"llm" \| "vlm" \| "embedding"` | ❌ | `"llm"` | 模型类型 |
| `model_id` | `string` | ✅ | — | 模型 ID (含 provider 前缀) |
| `thinking` | `bool` | ❌ | `false` | 支持思考模式 |
| `priority` | `int` | ❌ | `0` | 优先级 |
| `is_default` | `bool` | ❌ | `false` | 设为默认 |
| `is_active` | `bool` | ❌ | `true` | 启用状态 |

**响应：** `ModelInDB`

**前端调用：** `api.createModel()`

---

### 4.3 `PATCH /api/v1/models/{model_id}`

**描述：** 部分更新模型配置。

**Path 参数：** `model_id` (string, UUID)

**请求体 `ModelUpdateRequest`：** 所有字段可选 (`provider`, `model_type`, `model_id`, `thinking`, `is_default`, `is_active`)

**响应：** `ModelInDB`

**前端调用：** `api.updateModel()`

---

### 4.4 `DELETE /api/v1/models/{model_id}`

**描述：** 删除模型配置。

**Path 参数：** `model_id` (string, UUID)

**响应：** 成功消息

**前端调用：** `api.deleteModel()`

---

### 4.5 `PATCH /api/v1/models/{model_id}/set-default`

**描述：** 设置某类型模型的默认值。

**Path 参数：** `model_id` (string, UUID)

**响应：** `ModelInDB`

**前端调用：** `api.setDefaultModel()`

---

### 4.6 `POST /api/v1/models/test-connection`

**描述：** 测试模型连接。

**请求体 `TestConnectionRequest`：**

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `provider` | `string` | ✅ | 提供商 |
| `model_id` | `string` | ✅ | 模型 ID |
| `api_key` | `string` | ✅ | API 密钥 |
| `model_type` | `"llm" \| "vlm" \| "embedding"` | ❌ | 模型类型 |

**响应 `TestConnectionResponse`：**
```json
{ "success": true, "message": "Connection successful" }
```

**前端调用：** `api.testModelConnection()`

---

### 4.7 `GET /api/v1/models/providers`

**描述：** 获取所有提供商及其配置状态。

**响应 `ProvidersResponse`：**
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

**前端调用：** `api.getProviders()`

---

### 4.8 `PUT /api/v1/models/providers/{provider}`

**描述：** 更新提供商配置（API Key, Base URL）。

**Path 参数：** `provider` (string)

**请求体 `ProviderUpdateRequest`：**

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `provider` | `string` | ✅ | 提供商名 |
| `api_key` | `string \| null` | ❌ | API 密钥（自动加密） |
| `base_url` | `string \| null` | ❌ | OpenAI-Compatible Base URL |

**响应：** `ProviderInfo`

**前端调用：** `api.updateProvider()`

---

## 5. Traces 模块

**路由前缀：** `/api/v1/traces`

**源文件：** `backend/app/api/v1/traces/`

---

### 5.1 `GET /api/v1/traces`

**描述：** 分页获取所有 Trace 列表（Kanban 视图数据源）。

**Query 参数：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `page` | `int` | ❌ | `0` | 页码（0-indexed） |
| `page_size` | `int` | ❌ | `20` | 每页条数 |
| `filter_hours` | `int` | ❌ | `24` | 时间过滤（小时） |
| `user_id` | `string \| null` | ❌ | `null` | 按用户过滤 |

**响应 `TraceListResponse`：**
```json
{
  "items": [
    {
      "thread_id": "f47ac10b-...",
      "title": "北京天气查询",
      "total_steps": 5,
      "total_latency_ms": 3200,
      "last_updated": "2026-05-29T08:00:00Z"
    }
  ],
  "total": 42,
  "total_pages": 3,
  "page": 0,
  "page_size": 20,
  "has_more": true,
  "filter_hours": 24
}
```

**前端调用：** `api.listTraces()` → `features/kanban/`

---

### 5.2 `GET /api/v1/traces/{thread_id}`

**描述：** 获取指定会话的完整 Trace 执行记录。

**Path 参数：** `thread_id` (UUID)

**响应 `ExecutionTrace`：**
```json
{
  "thread_id": "f47ac10b-...",
  "steps": [
    {
      "step_number": 1,
      "message_type": "ai",
      "content": "...",
      "timestamp": "2026-05-29T08:00:00Z",
      "message_id": "msg-001",
      "checkpoint_id": "1f0e3f...",
      "node_name": "chatbot",
      "ai_metadata": { "thinking": null, "tool_calls": null, "model_name": "qwen3.5-27b" },
      "tool_metadata": null
    }
  ],
  "total_steps": 5,
  "first_step_at": "2026-05-29T08:00:00Z",
  "last_step_at": "2026-05-29T08:00:03Z"
}
```

**前端调用：** `api.getTrace()`

---

### 5.3 `GET /api/v1/traces/{thread_id}/dag`

**描述：** 获取会话执行 DAG（节点 + 边，用于可视化）。

**Path 参数：** `thread_id` (UUID)

**响应 `ExecutionDag`：**
```json
{
  "thread_id": "f47ac10b-...",
  "nodes": [
    {
      "node_id": "node-1",
      "step_number": 1,
      "node_name": "chatbot",
      "title": "Chatbot Response",
      "message_type": "ai",
      "step": { ... }
    }
  ],
  "edges": [["node-1", "node-2"]],
  "total_steps": 5,
  "steps": [...]
}
```

**前端调用：** `api.getTraceDag()`

---

### 5.4 `GET /api/v1/traces/{thread_id}/checkpoints`

**描述：** 获取会话的 LangGraph Checkpoint 列表。

**Path 参数：** `thread_id` (UUID)

**响应 `list[CheckpointInfo]`：**
```json
[
  {
    "checkpoint_id": "1f0e3f...",
    "thread_id": "f47ac10b-...",
    "parent_checkpoint_id": null,
    "node_name": "chatbot",
    "timestamp": "2026-05-29T08:00:00Z",
    "message_count": 1,
    "last_message_type": "ai",
    "has_next": true,
    "next_nodes": ["chatbot"]
  }
]
```

**前端调用：** `api.getTraceCheckpoints()`

---

## 6. 前端 API 使用矩阵

**API 层：** `frontend/src/lib/api.ts`

### 6.1 Chat 模块调用

| Endpoint | API 函数 | 前端模块/组件 |
|----------|----------|-------------|
| `POST /chat/run/stream` | `streamChat()` | `features/chat/` 核心对话组件 |
| `POST /chat/run/invoke` | `invokeChat()` | `features/chat/` (非流式备用) |
| `GET /chat/conversations` | `listConversations()` | 侧边栏会话列表 |
| `GET /chat/conversations/{thread_id}` | `getChatHistory()` | 历史消息加载 |
| `GET /chat/conversation-info/{thread_id}` | `getConversationInfo()` | 模型回退提示 |
| `PATCH /chat/conversations/{thread_id}` | `updateConversation()` | 标题编辑/软删除 |
| `DELETE /chat/conversations/{thread_id}` | `deleteConversation()` | 会话删除 |
| `POST /chat/title` | `generateTitle()` | 自动标题生成 |
| `GET /chat/thinking-mode` | `getThinkingModeStatus()` | `hooks/use-thinking-mode.ts` |
| `GET /chat/agents` | `listAgents()` | Agent 选择器 |
| `GET /chat/stats/daily` | `getDailyStats()` | 统计仪表盘 |
| `GET /chat/conversations/{thread_id}/stats` | `getConversationStats()` | 会话 Token 详情 |

### 6.2 Models 模块调用

| Endpoint | API 函数 | 前端模块/组件 |
|----------|----------|-------------|
| `GET /models` | `getAvailableModels()` | `hooks/use-models.ts` (模型选择器) |
| `POST /models` | `createModel()` | 模型管理面板 |
| `PATCH /models/{model_id}` | `updateModel()` | 模型编辑 |
| `DELETE /models/{model_id}` | `deleteModel()` | 模型删除 |
| `PATCH /models/{model_id}/set-default` | `setDefaultModel()` | 设置默认模型 |
| `POST /models/test-connection` | `testModelConnection()` | 连接测试 |
| `GET /models/providers` | `getProviders()` | 提供商列表 |
| `PUT /models/providers/{provider}` | `updateProvider()` | 提供商配置 |

### 6.3 Traces 模块调用

| Endpoint | API 函数 | 前端模块/组件 |
|----------|----------|-------------|
| `GET /traces` | `listTraces()` | `features/kanban/` 看板视图 |
| `GET /traces/{thread_id}` | `getTrace()` | Trace 详情页 |
| `GET /traces/{thread_id}/dag` | `getTraceDag()` | DAG 可视化 |
| `GET /traces/{thread_id}/checkpoints` | `getTraceCheckpoints()` | Checkpoint 调试 |

### 6.4 前端类型定义

**文件：** `frontend/src/types.ts`

| 类型 | 对应后端 Schema | 用途 |
|------|---------------|------|
| `UserInput` | `app.schemas.chat.UserInput` | 对话请求 |
| `ChatMessage` | `app.schemas.chat.ChatMessage` | 聊天消息 |
| `ChatHistory` | `app.schemas.chat.ChatHistory` | 历史记录 |
| `ConversationInDB` | `app.schemas.chat.ConversationInDB` | 会话信息 |
| `ModelInfo` | `app.schemas.model.ModelInfo` | 模型信息 |
| `ModelsResponse` | `app.schemas.model.ModelsResponse` | 模型列表响应 |
| `ProviderInfo` | `app.schemas.provider.ProviderInfo` | 提供商信息 |
| `StreamEvent` | (SSE 事件联合类型) | 流式事件解析 |
| `MessageStep` | `app.schemas.trace.StepOutput` | 执行步骤 |

### 6.5 关键前端 Hooks

| Hook | 文件 | 调用的 API |
|------|------|-----------|
| `useModels()` | `hooks/use-models.ts` | `GET /models` |
| `useThinkingMode()` | `hooks/use-thinking-mode.ts` | `GET /chat/thinking-mode` |

### 6.6 关键前端 Feature 模块

| 模块 | 目录 | 主要 API |
|------|------|---------|
| Chat 对话 | `features/chat/` | `streamChat`, `getChatHistory`, `listConversations`, `generateTitle` |
| Kanban 看板 | `features/kanban/` | `listTraces`, `getTrace`, `getTraceDag` |

---

> **文档版本：** v1.0 | **后端路由文件：** `backend/app/api/v1/chat/`, `backend/app/api/v1/models/`, `backend/app/api/v1/traces/` | **前端 API 层：** `frontend/src/lib/api.ts`
