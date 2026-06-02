# AgentHub Backend API 接口文档

> 自动生成于 2026-06-02 | 基于 FastAPI 路由扫描 + 源码分析

---

## 目录

- [1. 概览](#1-概览)
- [2. 健康检查](#2-健康检查)
- [3. Chat 模块](#3-chat-模块)
- [4. Models 模块](#4-models-模块)
- [5. Traces 模块](#5-traces-模块)
- [6. 数据模型汇总](#6-数据模型汇总)
- [7. 前端 API 使用矩阵](#7-前端-api-使用矩阵)

---

## 1. 概览

| 模块 | 路由前缀 | Endpoint 数量 |
|------|---------|--------------|
| Health | `/` | 1 |
| Chat | `/api/v1/chat` | 11 |
| Models | `/api/v1/models` | 6 |
| Traces | `/api/v1/traces` | 6 |

**总计：24 个 Endpoint**

**认证方式：** 当前版本无全局认证中间件（通过 `user_id` 参数区分用户）。

**全局错误处理：** `app.api.errors.register_exception_handlers` 集中注册。

**API 前缀：** `/api/v1`

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
- `backend/app/api/v1/chat/conversations.py` — 会话 CRUD + 标题管理
- `backend/app/api/v1/chat/history.py` — 对话历史
- `backend/app/api/v1/chat/stats.py` — 统计数据

---

### 3.1 `POST /api/v1/chat/stream`

**描述：** SSE 流式运行 Agent 对话。前端通过 `fetch` + `ReadableStream` 消费。

**请求体 `UserInput`：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `content` | `string` | ✅ | — | 用户输入消息 |
| `user_id` | `string` | ✅ | — | 用户 ID（长期记忆与个性化） |
| `thread_id` | `UUID` | ✅ | — | 会话线程 ID（多轮对话） |
| `request_id` | `string` | ✅ | — | 请求 ID（追踪与幂等性） |
| `model_name` | `string \| null` | ❌ | `null` | 指定模型名 (e.g. `qwen3.5-27b`) |
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

**SSE Event 类型：**

| type | 描述 |
|------|------|
| `step` | 执行步骤（human/ai_thinking/tool_call/tool_result） |
| `token` | LLM 逐 token 输出 |
| `reasoning` | 思考模式推理增量 |
| `usage` | Token 用量统计 |
| `message` | 完整消息（含 metadata） |
| `error` | 错误信息 |

**示例 SSE 流：**
```
: [2048 spaces for proxy flush]

data: {"type": "step", "step": 1, "action": "human", "content": "..."}

data: {"type": "token", "content": "Hello"}

data: {"type": "reasoning", "content": "Let me think..."}

data: {"type": "step", "step": 2, "action": "ai_thinking", "status": "thinking..."}

data: {"type": "step", "step": 3, "action": "tool_call", "name": "web_search", "status": "calling"}

data: {"type": "usage", "content": {"node": "model", "usage": {"input_tokens": 100, "output_tokens": 50}}}

data: {"type": "message", "content": {...}}

data: [DONE]
```

**涉及的 Agent：** Supervisor Agent (单一入口)，`app.agents.supervisor`

**关键实现：** `app.services.streaming.ChatStreamingService`, `app.utils.sse`

---

### 3.2 `POST /api/v1/chat/invoke`

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

**关键实现：** `app.services.chat.ChatService.invoke()`

---

### 3.3 `GET /api/v1/chat/conversations`

**描述：** 获取用户活跃会话列表。

**Query 参数：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `user_id` | `string` | ✅ | — | 用户 ID |
| `limit` | `int` | ❌ | `20` | 返回数量上限 (1-100) |
| `offset` | `int` | ❌ | `0` | 分页偏移量 |

**响应头：** `X-Total-Count: 100`

**响应 `list[ConversationInDB]`：**
```json
[
  {
    "thread_id": "f47ac10b-...",
    "user_id": "user-123",
    "title": "北京天气查询",
    "created_at": "2026-06-01T00:00:00Z",
    "updated_at": "2026-06-02T00:00:00Z",
    "is_deleted": false,
    "input_tokens": 150,
    "cache_read": 0,
    "output_tokens": 80,
    "reasoning": 0,
    "total_tokens": 230
  }
]
```

---

### 3.4 `POST /api/v1/chat/conversations`

**描述：** 创建新会话。

**Query 参数：** `user_id` (string, 必填)

**请求体 `ConversationCreate`：**
```json
{
  "thread_id": "f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c",
  "user_id": "user-123",
  "title": "新对话"
}
```

**响应：** `ConversationInDB`

---

### 3.5 `DELETE /api/v1/chat/conversations/{thread_id}`

**描述：** 软删除会话。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**响应：** `204 No Content`

---

### 3.6 `GET /api/v1/chat/conversations/{thread_id}/info`

**描述：** 获取会话的模型信息（判断是否发生模型回退）。用于历史对话进入时恢复模型。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**响应 `ConversationInfoResponse`：**
```json
{
  "model_name": "qwen3.5-27b",
  "model_fallback": false
}
```

- `model_fallback`: `true` 表示原模型已停用，回退到了默认模型

---

### 3.7 `GET /api/v1/chat/conversations/{thread_id}/title`

**描述：** 获取会话标题。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**响应：** `ConversationInDB | null`

---

### 3.8 `PATCH /api/v1/chat/conversations/{thread_id}/title`

**描述：** 更新会话标题。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**请求体 `ConversationUpdate`：**
```json
{
  "title": "新标题"
}
```

**响应：** `ConversationInDB`

---

### 3.9 `POST /api/v1/chat/conversations/{thread_id}/title/generate`

**描述：** 自动生成会话标题。使用系统默认 LLM 生成。

**Path 参数：** `thread_id` (UUID)

**请求体 `TitleGenerateRequest`：**
```json
{
  "user_message": "今天北京的天气怎么样？",
  "ai_response": "北京今天晴，25°C..."  // 可选
}
```

**响应 `TitleGenerateResponse`：**
```json
{
  "title": "北京天气查询"
}
```

---

### 3.10 `GET /api/v1/chat/history/{thread_id}`

**描述：** 获取指定会话的聊天历史（消息 + 执行序列）。

**Path 参数：** `thread_id` (UUID)

**响应 `ChatHistory`：**
```json
{
  "messages": [
    { "type": "human", "content": "...", "tool_calls": [], "custom_data": {} },
    { "type": "ai", "content": "...", "tool_calls": [], "custom_data": { "tool_info": [...] } }
  ],
  "message_sequence": [
    {
      "step_number": 1,
      "message_type": "human",
      "content": "...",
      "timestamp": "2026-06-01T00:00:00Z",
      "message_id": "msg-001",
      "checkpoint_id": "1f0e3f...",
      "node_name": "human",
      "ai_metadata": null,
      "tool_metadata": null
    },
    {
      "step_number": 2,
      "message_type": "ai",
      "content": "...",
      "timestamp": "2026-06-01T00:00:01Z",
      "message_id": "msg-002",
      "checkpoint_id": "2f1e4g...",
      "node_name": "model",
      "ai_metadata": {
        "thinking": "Let me search...",
        "tool_calls": [{"name": "web_search", "args": {"query": "weather"}}],
        "model_name": "qwen3.5-27b"
      },
      "tool_metadata": null
    }
  ]
}
```

**关键实现：** `app.api.v1.chat.history.history()`

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
    "date": "2026-06-01",
    "conversation_count": 12,
    "input_tokens": 1500,
    "cache_read": 200,
    "output_tokens": 800,
    "reasoning": 100,
    "total_tokens": 2600
  }
]
```

---

### 3.12 `GET /api/v1/chat/conversations/{thread_id}/stats`

**描述：** 单会话累计 Token 用量。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**响应：** `ConversationInDB`（包含 token 字段）

---

## 4. Models 模块

**路由前缀：** `/api/v1/models`

**源文件：** `backend/app/api/v1/models.py`

---

### 4.1 `GET /api/v1/models`

**描述：** 获取所有模型 + 默认模型。

**Query 参数：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `include_inactive` | `bool` | ❌ | `false` | 是否包含禁用模型 |

**响应 `ModelsResponse`：**
```json
{
  "models": [
    {
      "id": "uuid-001",
      "provider": "dashscope",
      "model_type": "llm",
      "model_id": "qwen3.5-27b",
      "thinking": true,
      "is_default": true,
      "is_active": true,
      "created_at": "2026-06-01T00:00:00Z",
      "updated_at": "2026-06-01T00:00:00Z"
    }
  ],
  "default_llm": "dashscope/qwen3.5-27b",
  "default_vlm": null,
  "default_embedding": null
}
```

---

### 4.2 `POST /api/v1/models`

**描述：** 创建新模型配置。

**请求体 `ModelCreate`：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `provider` | `string` | ✅ | — | 提供商 (e.g. `dashscope`, `zai`) |
| `model_type` | `"llm" \| "vlm"` | ❌ | `"llm"` | 模型类型 |
| `model_id` | `string` | ✅ | — | 模型 ID (不含 provider 前缀) |
| `thinking` | `bool` | ❌ | `false` | 支持思考模式 |
| `is_default` | `bool` | ❌ | `false` | 设为默认 |
| `is_active` | `bool` | ❌ | `true` | 启用状态 |

**响应：** `201 Created` + `ModelInfo`

---

### 4.3 `PATCH /api/v1/models/{model_id}`

**描述：** 部分更新模型配置。设置 `is_default: true` 可将该模型设为默认。

**Path 参数：** `model_id` (UUID)

**请求体 `ModelUpdateRequest`：**

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `model_id` | `string \| null` | ❌ | 新模型 ID |
| `provider` | `string \| null` | ❌ | 提供商 |
| `model_type` | `"llm" \| "vlm" \| null` | ❌ | 模型类型 |
| `thinking` | `bool \| null` | ❌ | 支持思考模式 |
| `is_default` | `bool \| null` | ❌ | 设为默认 |
| `is_active` | `bool \| null` | ❌ | 启用状态 |

**响应：** `ModelInfo`

---

### 4.4 `DELETE /api/v1/models/{model_id}`

**描述：** 删除模型配置。

**Path 参数：** `model_id` (UUID)

**响应：** `204 No Content`

---

### 4.5 `GET /api/v1/models/providers`

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
      "created_at": "2026-06-01T00:00:00Z",
      "updated_at": "2026-06-01T00:00:00Z"
    }
  ]
}
```

---

### 4.6 `PATCH /api/v1/models/providers/{provider_name}`

**描述：** 更新提供商配置（API Key, Base URL）。

**Path 参数：** `provider_name` (string)

**请求体 `ProviderUpdateRequest`：**

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `provider` | `string` | ✅ | 提供商名 |
| `api_key` | `string \| null` | ❌ | API 密钥（自动加密存储） |
| `base_url` | `string \| null` | ❌ | OpenAI-Compatible Base URL |

**响应：** `ProviderInfo`

---

### 4.7 `GET /api/v1/models/thinking-mode`

**描述：** 检查是否支持思考模式。

**响应 `ThinkingModeStatus`：**
```json
{
  "available": true
}
```

---

## 5. Traces 模块

**路由前缀：** `/api/v1/traces`

**源文件：** `backend/app/api/v1/traces.py`

**数据来源：** 所有端点从持久化的 `trace_executions` 表读取，不依赖 graph 编译。

---

### 5.1 `GET /api/v1/traces`

**描述：** 分页获取所有 Trace 列表（Kanban 视图数据源）。

**Query 参数：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `page` | `int` | ❌ | `0` | 页码（0-indexed） |
| `page_size` | `int` | ❌ | `10` | 每页条数 (1-100) |
| `hours` | `int` | ❌ | `24` | 时间过滤（小时，1-168） |
| `user_id` | `string` | ✅ | — | 按用户过滤 |

**响应 `TraceListResponse`：**
```json
{
  "items": [
    {
      "thread_id": "f47ac10b-...",
      "title": "北京天气查询",
      "total_steps": 5,
      "total_latency_ms": 0,
      "last_updated": "2026-06-02T08:00:00Z"
    }
  ],
  "total": 42,
  "total_pages": 5,
  "page": 0,
  "page_size": 10,
  "has_more": true,
  "filter_hours": 24
}
```

---

### 5.2 `GET /api/v1/traces/{thread_id}/steps`

**描述：** 获取指定会话的所有执行步骤。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**响应 `list[StepOutput]`：**
```json
[
  {
    "step_number": 1,
    "message_type": "human",
    "content": "What is the weather?",
    "timestamp": "2026-06-02T08:00:00Z",
    "message_id": "msg-001",
    "checkpoint_id": "1f0e3f...",
    "node_name": "human",
    "ai_metadata": null,
    "tool_metadata": null
  },
  {
    "step_number": 2,
    "message_type": "ai",
    "content": "The weather is sunny.",
    "timestamp": "2026-06-02T08:00:01Z",
    "message_id": "msg-002",
    "checkpoint_id": "2f1e4g...",
    "node_name": "model",
    "ai_metadata": {
      "thinking": null,
      "tool_calls": null,
      "model_name": "qwen3.5-27b"
    },
    "tool_metadata": null
  }
]
```

---

### 5.3 `GET /api/v1/traces/{thread_id}/dag`

**描述：** 获取会话执行 DAG（节点 + 边，用于可视化）。

**Path 参数：** `thread_id` (UUID)

**Query 参数：** `user_id` (string, 必填)

**响应 `ExecutionDag`：**
```json
{
  "thread_id": "f47ac10b-...",
  "nodes": [
    {
      "node_id": "node-1",
      "step_number": 1,
      "node_name": "human",
      "title": "User Input",
      "message_type": "human",
      "step": { ... }
    }
  ],
  "edges": [["node-1", "node-2"]],
  "total_steps": 5,
  "steps": [...]
}
```

---

### 5.4 `GET /api/v1/traces/{thread_id}/steps/{step_number}`

**描述：** 按步骤号获取特定步骤。

**Path 参数：**
- `thread_id` (UUID)
- `step_number` (int)

**Query 参数：** `user_id` (string, 必填)

**响应：** `StepOutput`

---

### 5.5 `GET /api/v1/traces/{thread_id}/checkpoints/{checkpoint_id}`

**描述：** 按 Checkpoint ID 获取特定步骤。

**Path 参数：**
- `thread_id` (UUID)
- `checkpoint_id` (string)

**Query 参数：** `user_id` (string, 必填)

**响应：** `StepOutput`

---

### 5.6 `GET /api/v1/traces/{thread_id}/replay`

**描述：** 回放指定范围的执行步骤。

**Path 参数：** `thread_id` (UUID)

**Query 参数：**

| 字段 | 类型 | 必填 | 默认值 | 描述 |
|------|------|------|--------|------|
| `from_step` | `int` | ❌ | `1` | 起始步骤 (≥1) |
| `to_step` | `int \| null` | ❌ | `null` | 结束步骤 |
| `user_id` | `string` | ✅ | — | 用户 ID |

**响应：** `list[StepOutput]`

---

## 6. 数据模型汇总

### 6.1 请求模型

| 模型 | 用途 | 源文件 |
|------|------|--------|
| `UserInput` | Agent 调用请求 | `app.schemas.chat` |
| `ConversationCreate` | 创建对话 | `app.schemas.chat` |
| `ConversationUpdate` | 更新对话 | `app.schemas.chat` |
| `TitleGenerateRequest` | 生成标题 | `app.schemas.chat` |
| `ModelCreate` | 创建模型 | `app.schemas.model` |
| `ModelUpdateRequest` | 更新模型 | `app.schemas.model` |
| `ProviderUpdateRequest` | 更新 Provider | `app.schemas.provider` |

### 6.2 响应模型

| 模型 | 用途 | 源文件 |
|------|------|--------|
| `ChatMessage` | 单条消息 | `app.schemas.chat` |
| `ChatHistory` | 对话历史 + 步骤序列 | `app.schemas.chat` |
| `ConversationInDB` | 对话详情 | `app.schemas.chat` |
| `ConversationInfoResponse` | 对话信息（模型） | `app.schemas.chat` |
| `TitleGenerateResponse` | 生成的标题 | `app.schemas.chat` |
| `DailyStatsItem` | 每日统计 | `app.schemas.chat` |
| `ModelsResponse` | 模型列表 | `app.schemas.model` |
| `ModelInfo` | 模型详情 | `app.schemas.model` |
| `ProvidersResponse` | Provider 列表 | `app.schemas.provider` |
| `ProviderInfo` | Provider 详情 | `app.schemas.provider` |
| `ThinkingModeStatus` | 思考模式状态 | `app.schemas.model` |
| `TraceListResponse` | 追踪列表 | `app.schemas.trace` |
| `StepOutput` | 执行步骤 | `app.schemas.trace` |
| `ExecutionDag` | 执行 DAG | `app.schemas.trace` |

---

## 7. 前端 API 使用矩阵

### 7.1 Chat 模块调用

| Endpoint | 前端模块/组件 |
|----------|-------------|
| `POST /chat/stream` | 核心对话组件 (流式) |
| `POST /chat/invoke` | 核心对话组件 (非流式备用) |
| `GET /chat/conversations` | 侧边栏会话列表 |
| `POST /chat/conversations` | 创建新对话 |
| `DELETE /chat/conversations/{thread_id}` | 会话删除 |
| `GET /chat/conversations/{thread_id}/info` | 模型回退提示 |
| `GET /chat/conversations/{thread_id}/title` | 获取标题 |
| `PATCH /chat/conversations/{thread_id}/title` | 标题编辑 |
| `POST /chat/conversations/{thread_id}/title/generate` | 自动标题生成 |
| `GET /chat/history/{thread_id}` | 历史消息加载 |
| `GET /chat/stats/daily` | 统计仪表盘 |
| `GET /chat/conversations/{thread_id}/stats` | 会话 Token 详情 |

### 7.2 Models 模块调用

| Endpoint | 前端模块/组件 |
|----------|-------------|
| `GET /models` | 模型选择器、模型管理面板 |
| `POST /models` | 模型管理面板 |
| `PATCH /models/{model_id}` | 模型编辑 |
| `DELETE /models/{model_id}` | 模型删除 |
| `GET /models/providers` | 提供商列表 |
| `PATCH /models/providers/{provider}` | 提供商配置 |
| `GET /models/thinking-mode` | 思考模式状态 |

### 7.3 Traces 模块调用

| Endpoint | 前端模块/组件 |
|----------|-------------|
| `GET /traces` | 看板视图 |
| `GET /traces/{thread_id}/steps` | Trace 详情页 |
| `GET /traces/{thread_id}/dag` | DAG 可视化 |
| `GET /traces/{thread_id}/steps/{step_number}` | 单步详情 |
| `GET /traces/{thread_id}/checkpoints/{checkpoint_id}` | Checkpoint 详情 |
| `GET /traces/{thread_id}/replay` | Trace 回放 |

---

## 8. 架构说明

### 8.1 服务层设计

```
API Route (FastAPI)
    │
    ├── UserInput validation (Pydantic v2)
    │
    ▼
Service Layer
    │
    ├── ChatService / ChatStreamingService
    │       ├── build_agent_kwargs() → config + context
    │       └── Agent execution + persistence
    │
    ▼
Agent Layer (LangChain v1)
    │
    ├── create_agent(middleware=[...])
    │       ├── @dynamic_prompt → MD 模板 + 时间上下文
    │       ├── @wrap_model_call → 运行时模型切换
    │       └── SummarizationMiddleware → 多轮对话压缩
    │
    └── LiteLLM Router → Fallback + Retry
```

### 8.2 中间件链

```python
middleware = [
    supervisor_prompt,      # @dynamic_prompt: MD模板 + TTLCache
    dynamic_model,          # @wrap_model_call: 运行时模型切换
    SummarizationMiddleware(  # 多轮对话历史压缩
        model=get_system_llm(),
        trigger=("tokens", 4000),
        keep=("messages", 20),
    ),
]
```

### 8.3 SSE 流式处理

```
agent.astream_events(version="v3")
    │
    ├── .messages projection → token deltas
    ├── .tool_calls projection → tool lifecycle
    └── .values projection → final state
    │
    ▼
AsyncIO Queue (sentinel-based)
    │
    ▼
SSE Stream Response
```

---

> **文档版本：** v2.0 | **后端路由文件：** `backend/app/api/v1/` | **架构参考：** `memory-bank/systemPatterns.md`