# AgentHub API 接口文档

> 基准路径：`/api/v1` | 全局异常处理：`app/api/errors.py` | 传输格式：JSON / SSE (text/event-stream)

---

## 目录

1. [Chat — 对话](#1-chat--对话)
2. [Chat Session — 会话管理](#2-chat-session--会话管理)
3. [Chat Title — 标题管理](#3-chat-title--标题管理)
4. [Agent — Agent 管理](#4-agent--agent-管理)
5. [Model — 模型管理](#5-model--模型管理)
6. [Provider — Provider 配置](#6-provider--provider-配置)
7. [Trace — 执行追踪](#7-trace--执行追踪)
8. [Health — 健康检查](#8-health--健康检查)

---

## 1. Chat — 对话

核心对话能力：流式输出、同步调用、对话历史回溯。

### `POST /api/v1/chat/stream`

SSE 流式 Agent 响应。返回 token 级别的事件流，附带工具调用和最终消息。

- **响应类型**：`text/event-stream` (SSE)
- **Agent 类型**：所有通过 `get_graph()` 可获取的 Agent

**请求体**：`UserInput`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `content` | `str` | ✅ | 用户输入内容 |
| `agent_id` | `str` | ✅ | Agent 标识符（如 `"chatbot"`） |
| `user_id` | `str` | ✅ | 用户标识，用于长期记忆和个性化 |
| `thread_id` | `UUID` | ✅ | 会话线程 ID，持久化多轮对话 |
| `request_id` | `str` | ✅ | 请求 ID，用于端到端追踪和幂等 |
| `model_name` | `str \| None` | ❌ | 运行时覆盖模型（不传则用默认模型） |
| `thinking_mode` | `bool` | ❌ | 是否启用思考模式（默认 `false`） |
| `timezone` | `str` | ❌ | IANA 时区名（默认 `"Asia/Shanghai"`） |
| `custom_data` | `dict \| None` | ❌ | 自定义数据（如引用消息） |

**SSE 事件类型**：

| 事件类型 | 说明 | 示例 payload |
|---------|------|-------------|
| `token` | LLM 输出的单个 token | `{"type":"token","content":"北京"}` |
| `reasoning` | thinking mode 推理内容 | `{"type":"reasoning","content":"用户询问天气..."}` |
| `tool_call` | Agent 发起工具调用 | `{"type":"tool_call","tool_call_id":"...","name":"web_search","args":{...}}` |
| `tool_result` | 工具执行结果 | `{"type":"tool_result","tool_call_id":"...","result":"..."}` |
| `usage` | Token 用量统计 | `{"type":"usage","input_tokens":150,"output_tokens":80}` |
| `custom` | 自定义事件 | `{"type":"custom","data":{...}}` |
| `message` | 最终完整消息 | `{"type":"message","content":{...ChatMessage}}` |
| `[DONE]` | 流结束信号 | `data: [DONE]` |

**请求示例**：

```json
{
  "content": "北京今天天气怎么样？",
  "agent_id": "chatbot",
  "user_id": "user-123",
  "thread_id": "f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c",
  "request_id": "req-abc-001",
  "model_name": "qwen3.5-27b",
  "thinking_mode": false,
  "timezone": "Asia/Shanghai"
}
```

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `400` | `agent_id` 未提供或 Agent 不存在/未激活 |

---

### `POST /api/v1/chat/invoke`

同步调用 Agent，返回完整 AI 响应。适用于非流式场景。

- **Agent 类型**：所有 Agent
- **请求体**：同 `UserInput`（参见 `/chat/stream`）

**响应模型**：`ChatMessage`

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `"human" \| "ai" \| "tool" \| "custom"` | 消息角色 |
| `content` | `str` | 消息内容 |
| `tool_calls` | `list[ToolCall]` | 工具调用列表 |
| `tool_call_id` | `str \| None` | 工具调用 ID（tool 消息） |
| `name` | `str \| None` | 工具名（tool 消息） |
| `run_id` | `str \| None` | 运行 ID |
| `response_metadata` | `dict` | 响应元数据（token 用量等） |
| `custom_data` | `dict` | 自定义数据 |

**请求示例**：

```json
{
  "content": "1+1等于几？",
  "agent_id": "chatbot",
  "user_id": "user-123",
  "thread_id": "f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c",
  "request_id": "req-abc-002"
}
```

**响应示例**：

```json
{
  "type": "ai",
  "content": "1+1等于2。",
  "tool_calls": [],
  "tool_call_id": null,
  "name": null,
  "run_id": "847c6285-8fc9-4560-a83f-4e6285809254",
  "response_metadata": {},
  "custom_data": {}
}
```

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `400` | `agent_id` 未提供或 Agent 不活跃 |
| `500` | Agent 调用返回空事件 |

---

### `GET /api/v1/chat/history/{agent_id}/{thread_id}`

获取对话历史，包含主聊天消息和侧边栏执行步骤序列。

- **Agent 类型**：所有 Agent（需活跃才能读 checkpointer）

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `agent_id` | `str` | Agent ID（必需） |
| `thread_id` | `UUID` | 线程 ID |

**响应模型**：`ChatHistory`

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages` | `list[ChatMessage]` | 主聊天 UI 消息（human + 最终 AI，无 tool） |
| `message_sequence` | `list[StepOutput]` | 侧边栏完整执行步骤（含 tool_call/tool_result） |

**响应示例**：

```json
{
  "messages": [
    {"type": "human", "content": "北京天气？", "tool_calls": [], ...},
    {"type": "ai", "content": "北京今天晴天，25°C", "tool_calls": [], ...}
  ],
  "message_sequence": [
    {"step_number": 1, "message_type": "human", "content": "北京天气？", ...},
    {"step_number": 2, "message_type": "ai", "content": null,
     "ai_metadata": {"tool_calls": [{"name": "web_search", "args": {"query": "北京天气"}}]}, ...},
    {"step_number": 3, "message_type": "tool", "content": "晴天 25°C",
     "tool_metadata": {"tool_name": "web_search", "tool_args": {...}}, ...},
    {"step_number": 4, "message_type": "ai", "content": "北京今天晴天，25°C", ...}
  ]
}
```

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `400` | `agent_id` 未提供 |
| `404` | Agent 不存在或不活跃 |

---

### `GET /api/v1/chat/conversation-info/{thread_id}`

获取会话最后使用的 Agent 和模型信息。进入历史会话时使用。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | `str` | ✅ | 会话所有者 ID |

**响应模型**：`ConversationInfoResponse`

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_id` | `str` | 会话使用的 Agent ID |
| `model_name` | `str \| None` | 最后一次使用的模型名 |
| `model_fallback` | `bool` | 模型是否已回退到默认（原模型不再 active） |

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `404` | 会话不存在或不属于该用户 |
| `500` | 内部错误 |

---

## 2. Chat Session — 会话管理

会话持久化、统计查询、thinking mode 状态。

### `GET /api/v1/chat/conversations`

分页列出用户最近的会话（按最后更新时间降序）。

- **无 Agent 依赖**：纯 DB 查询

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | `str` | ✅ | 用户 ID |
| `limit` | `int` | ❌ | 每页数量（1-100，默认 `20`） |
| `offset` | `int` | ❌ | 偏移量（默认 `0`） |

**响应头部**：

| 头部 | 说明 |
|------|------|
| `X-Total-Count` | 符合条件的会话总数 |

**响应模型**：`list[ConversationInDB]`

| 字段 | 类型 | 说明 |
|------|------|------|
| `thread_id` | `UUID` | 会话 ID |
| `user_id` | `str` | 用户 ID |
| `title` | `str` | 会话标题 |
| `agent_id` | `str` | Agent ID |
| `created_at` | `datetime` | 创建时间 |
| `updated_at` | `datetime` | 更新时间 |
| `is_deleted` | `bool` | 是否已删除 |
| `input_tokens` / `output_tokens` / `total_tokens` | `int` | 累计 Token 用量 |

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `500` | 查询错误 |

---

### `POST /api/v1/chat/conversations`

创建新会话。

- **查询参数**：`user_id` (`str`, 必填)

**请求体**：`ConversationCreate`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `thread_id` | `UUID` | ✅ | 会话 ID |
| `user_id` | `str` | ✅ | 用户 ID |
| `title` | `str` | ✅ | 标题（1-64 字符） |
| `agent_id` | `str` | ❌ | Agent ID（默认 `"chatbot"`） |

**响应模型**：`ConversationInDB`

---

### `DELETE /api/v1/chat/conversations/{thread_id}`

软删除会话。

- **查询参数**：`user_id` (`str`, 必填)

**成功响应**：`204 No Content`

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `404` | 会话不存在 |
| `500` | 删除错误 |

---

### `GET /api/v1/chat/stats/daily`

获取每日会话数和 Token 用量统计。

- **查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `days` | `int` | ❌ | 统计天数（1-365，默认 `30`） |
| `user_id` | `str \| None` | ❌ | 可选用户过滤 |

**响应模型**：`list[DailyStatsItem]`

```json
[
  {
    "date": "2026-05-25",
    "conversation_count": 15,
    "input_tokens": 45000,
    "cache_read": 2000,
    "output_tokens": 12000,
    "reasoning": 800,
    "total_tokens": 59800
  }
]
```

---

### `GET /api/v1/chat/thinking-mode`

查询 thinking mode 是否可用（基于默认 LLM 模型配置）。

**响应模型**：`ThinkingModeStatus`

```json
{
  "available": true
}
```

---

## 3. Chat Title — 标题管理

### `GET /api/v1/chat/title/{thread_id}`

获取会话标题。

- **查询参数**：`user_id` (`str`, 必填)
- **响应模型**：`ConversationInDB | None`

---

### `POST /api/v1/chat/title`

设置/更新会话标题。

- **查询参数**：`thread_id` (`UUID`, 必填)、`user_id` (`str`, 必填)

**请求体**：`ConversationUpdate`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | `str \| None` | ❌ | 标题 |
| `agent_id` | `str \| None` | ❌ | Agent ID |
| `is_deleted` | `bool \| None` | ❌ | 是否删除 |

**响应模型**：`ConversationInDB | None`

---

### `POST /api/v1/chat/title/generate`

使用 System Default LLM 自动生成会话标题。

**请求体**：`TitleGenerateRequest`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_message` | `str` | ✅ | 用户消息（用于提取主题，截断至 200 字符） |
| `ai_response` | `str \| None` | ❌ | AI 响应（可选，提供更多上下文） |

**响应模型**：`TitleGenerateResponse`

```json
{
  "title": "北京天气查询"
}
```

> 生成失败时回退为用户消息前 30 字符。

---

## 4. Agent — Agent 管理

Agent 发现和生命周期管理。所有读取操作从内存缓存（`RegistrySnapshot`）零 DB 查询。

### `GET /api/v1/agents/`

列出所有活跃 Agent。

**响应模型**：`AgentListResponse`

| 字段 | 类型 | 说明 |
|------|------|------|
| `agents` | `list[AgentResponse]` | Agent 列表 |
| `total` | `int` | 总数 |
| `timestamp` | `datetime` | 响应时间戳 |

**`AgentResponse` 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_id` | `str` | 唯一标识 |
| `description` | `str` | 功能描述 |
| `is_active` | `bool` | 是否活跃 |
| `created_at` | `datetime` | 创建时间 |
| `updated_at` | `datetime` | 更新时间 |

---

### `GET /api/v1/agents/{agent_id}`

获取单个 Agent 元数据。

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `404` | Agent 不存在或未激活 |

---

### `PATCH /api/v1/agents/{agent_id}`

更新 Agent 的 DB 记录，自动重载 Agent 缓存。

**请求体**：`AgentUpdate`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `description` | `str \| None` | ❌ | 描述（1-1024 字符） |
| `is_active` | `bool \| None` | ❌ | `false` 则下线 Agent |

> 设置 `is_active=false` 后，Agent 从内存缓存移除，聊天端点返回 404。

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `404` | Agent 不存在 |

---

## 5. Model — 模型管理

模型 CRUD 和默认模型选择。每次写操作后自动触发 `ModelManager.refresh()` 更新 Router。

### `GET /api/v1/models/`

获取可用模型（仅返回有 Provider API Key 配置的模型），用于前端下拉菜单。

**响应模型**：`ModelsResponse`

| 字段 | 类型 | 说明 |
|------|------|------|
| `models` | `list[ModelInfo]` | 按 provider → model_id 排序 |
| `default_llm` | `str \| None` | 默认 LLM 模型 ID |
| `default_vlm` | `str \| None` | 默认 VLM 模型 ID |
| `default_embedding` | `str \| None` | 默认 Embedding 模型 ID |

**`ModelInfo` 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | UUID 主键 |
| `provider` | `str` | Provider 名 |
| `model_id` | `str` | 模型 ID（含 provider 前缀） |
| `model_type` | `"llm" \| "vlm" \| "embedding"` | 模型类型 |
| `thinking` | `bool` | 是否支持 thinking mode |
| `priority` | `int` | 回退优先级（数值越大优先级越高） |
| `is_default` | `bool` | 是否为类型默认模型 |
| `is_active` | `bool` | 是否激活 |
| `created_at` / `updated_at` | `datetime` | 时间戳 |

---

### `GET /api/v1/models/all`

获取全部模型（含未配置 API Key 的），用于配置页面。默认模型选择逻辑：优先 `is_default=True`，其次同类型首字母排序第一个。

**响应模型**：`ModelsResponse`

---

### `POST /api/v1/models/`

创建新模型。

**请求体**：`ModelCreate`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `provider` | `str` | ✅ | Provider 名 |
| `model_id` | `str` | ✅ | 模型 ID（含 provider 前缀，如 `"zai/glm-5.1"`） |
| `model_type` | `"llm" \| "vlm" \| "embedding"` | ❌ | 默认 `"llm"` |
| `thinking` | `bool` | ❌ | 默认 `false` |
| `priority` | `int` | ❌ | 默认 `0` |
| `is_default` | `bool` | ❌ | 默认 `false`（设为 `true` 时原子清除同类型默认） |
| `is_active` | `bool` | ❌ | 默认 `true` |

**入参校验**：`model_id` 不可重复

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `400` | `model_id` 已存在 |

---

### `POST /api/v1/models/update`

更新模型配置。

**请求体**：`ModelUpdateRequest`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | `str` | ✅ | UUID 主键 |
| `model_id` | `str \| None` | ❌ | 新 model_id |
| `provider` | `str \| None` | ❌ | 新 Provider |
| `model_type` | `"llm" \| "vlm" \| "embedding" \| None` | ❌ | |
| `thinking` | `bool \| None` | ❌ | |
| `priority` | `int \| None` | ❌ | |
| `is_default` | `bool \| None` | ❌ | 设为 `true` 时原子清除同类型默认 |
| `is_active` | `bool \| None` | ❌ | |

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `400` | 无效 UUID 格式 |
| `404` | 模型不存在 |

---

### `POST /api/v1/models/delete`

删除模型。

**请求体**：`DeleteModelRequest`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | `str` | ✅ | UUID 主键 |

**成功响应**：`204 No Content`

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `400` | 无效 UUID 格式 |
| `404` | 模型不存在 |

---

### `POST /api/v1/models/set-default`

设置类型默认模型（原子操作：清除同类型所有其他默认标记）。

**请求体**：`SetDefaultModelRequest`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | `str` | ✅ | UUID 主键 |

**响应模型**：`ModelInfo`

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `400` | 无效 UUID 格式 |
| `404` | 模型不存在 |

---

## 6. Provider — Provider 配置

### `GET /api/v1/providers/`

列出所有 Provider 及其配置状态（API Key 是否已配、base_url、兼容性）。

**响应模型**：`ProvidersResponse`

| 字段 | 类型 | 说明 |
|------|------|------|
| `providers` | `list[ProviderInfo]` | 按名称字母排序 |

**`ProviderInfo` 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `provider` | `str` | Provider 名 |
| `has_api_key` | `bool` | API Key 是否已配置 |
| `base_url` | `str \| None` | 自定义 base URL |
| `is_openai_compatible` | `bool` | 是否兼容 OpenAI 格式 |
| `created_at` / `updated_at` | `datetime` | 时间戳 |

---

### `POST /api/v1/providers/update`

更新 Provider 的 API Key 和/或 base URL（API Key 使用 AES-GCM 加密存储）。

**请求体**：`ProviderUpdateRequest`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `provider` | `str` | ✅ | Provider 名 |
| `api_key` | `str \| None` | ❌ | API Key（明文，加密后存储） |
| `base_url` | `str \| None` | ❌ | 自定义 base URL |

**响应模型**：`ProviderInfo`

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `400` | 没有提供要更新的字段 |
| `404` | Provider 不存在 |
| `500` | 更新失败 |

---

## 7. Trace — 执行追踪

所有 Trace 端点从 `trace_executions` 表读取，不依赖 Agent Graph 编译和活跃性。

### `GET /api/v1/traces`

分页列出执行追踪记录。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | `int` | ❌ | 页码（0-indexed，默认 `0`） |
| `page_size` | `int` | ❌ | 每页数量（1-100，默认 `10`） |
| `hours` | `int` | ❌ | 回溯时效（1-168 小时，默认 `24`） |
| `agent_id` | `str` | ❌ | Agent 过滤（默认 `"all"`） |
| `user_id` | `str` | ✅ | 用户 ID |

**响应模型**：`TraceListResponse`

| 字段 | 类型 | 说明 |
|------|------|------|
| `items` | `list[TraceListItem]` | 追踪列表 |
| `total` | `int` | 总数 |
| `total_pages` | `int` | 总页数 |
| `page` | `int` | 当前页 |
| `page_size` | `int` | 每页数量 |
| `has_more` | `bool` | 是否有更多页 |
| `filter_hours` | `int` | 应用的时间过滤 |

> `TraceListItem.total_steps` 通过批量查询 `trace_executions` 获取，不是 live checkpointer 查询。

---

### `GET /api/v1/traces/{thread_id}/steps`

获取指定会话的完整执行步骤序列。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_id` | `str` | ❌ | 默认 `"all"`（自动从会话表解析） |
| `user_id` | `str` | ✅ | 用于验证会话所有权 |

**响应模型**：`list[StepOutput]`

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `404` | 追踪数据不存在 |

---

### `GET /api/v1/traces/{thread_id}/dag`

获取指定会话的执行 DAG 图（节点和边），用于可视化。

**查询参数**：同 `/traces/{thread_id}/steps`

**响应模型**：`ExecutionDag`

| 字段 | 类型 | 说明 |
|------|------|------|
| `thread_id` | `str` | 会话 ID |
| `nodes` | `list[DagNode]` | DAG 节点列表 |
| `edges` | `list[tuple[str, str]]` | 有向边列表 |
| `total_steps` | `int` | 总步骤数 |
| `steps` | `list[StepOutput]` | 全部步骤详情 |

---

### `GET /api/v1/traces/{thread_id}/steps/{step_number}`

按步骤序号获取单个步骤详情。

**查询参数**：`user_id` (`str`, 必填)

**响应模型**：`StepOutput`

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `404` | 步骤不存在 |

---

### `GET /api/v1/traces/{thread_id}/checkpoints/{checkpoint_id}`

按 checkpoint ID 获取单个步骤详情。

**查询参数**：`agent_id` (`str`, ❌)、`user_id` (`str`, ✅)

**响应模型**：`StepOutput`

---

### `GET /api/v1/traces/{thread_id}/replay`

按步骤范围回放追踪。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `from_step` | `int` | ❌ | 起始步骤号（≥1，默认 `1`） |
| `to_step` | `int \| None` | ❌ | 结束步骤号（≥1） |
| `agent_id` | `str` | ❌ | 默认 `"all"` |
| `user_id` | `str` | ✅ | 用户 ID |

**响应模型**：`list[StepOutput]`

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `404` | 指定范围内无步骤 |

---

## 8. Health — 健康检查

### `GET /health`

Docker/K8s 健康检查端点。

**响应示例**：

```json
{
  "status": "healthy",
  "database": "ok"
}
```

**错误响应**：

| 状态码 | 说明 |
|--------|------|
| `503` | 数据库不可达 |

---

## 附录：SSE 流事件类型参考

```
data: {"type":"token","content":"北京"}\n\n
data: {"type":"token","content":"今天"}\n\n
data: {"type":"reasoning","content":"用户问天气，我需要搜索..."}\n\n
data: {"type":"tool_call","tool_call_id":"call_abc","name":"web_search","args":{"query":"北京 天气"}}\n\n
data: {"type":"tool_result","tool_call_id":"call_abc","result":"晴天 25°C 湿度40%"}\n\n
data: {"type":"usage","input_tokens":150,"cache_read":0,"output_tokens":80,"reasoning":20,"total_tokens":250}\n\n
data: {"type":"message","content":{"type":"ai","content":"北京今天晴天，25°C，湿度40%。","tool_calls":[],"response_metadata":{"token_usage":{...}}}}\n\n
data: [DONE]\n\n