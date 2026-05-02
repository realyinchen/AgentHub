# API 参考文档

## 概述

所有 API 端点前缀为 `/api/v1`。启动后端后，可访问 `http://localhost:8080/docs` 查看交互式 Swagger UI 文档。

## 通用约定

### 认证

当前版本为开放模式，无需认证 Token。生产环境建议添加认证中间件。

### 分页

列表接口支持分页参数：
- `limit`: int, 1-100, 默认 20
- `offset`: int, 默认 0
- 响应头包含 `X-Total-Count`: 总记录数

### 错误格式

```json
{
  "detail": "错误描述信息"
}
```

HTTP 状态码：
- `200`: 成功
- `400`: 请求参数错误
- `404`: 资源不存在
- `429`: 请求超限（速率限制）
- `500`: 服务器错误

### 速率限制

| 接口 | 限制 |
|------|------|
| Agent CRUD | 30/min |
| Chat Stream | 10/min |
| Chat History | 60/min |
| Model/Provider | 30/min |

---

## Agent API

### 获取 Agent 列表

```
GET /api/v1/agents?active_only=true&limit=20&offset=0
```

**Query 参数**：
- `active_only`: bool (默认 true) - 仅返回活跃 Agent
- `limit`: int (1-100)
- `offset`: int

**响应**：
```json
[
  {
    "id": "chatbot",
    "name": "通用对话助手",
    "description": "支持联网搜索的通用对话 Agent",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
]
```

### 获取 Agent 详情

```
GET /api/v1/agents/{agent_id}
```

### 创建 Agent

```
POST /api/v1/agents
```

**请求体**：
```json
{
  "id": "my_agent",
  "name": "我的 Agent",
  "description": "Agent 描述",
  "is_active": true
}
```

### 更新 Agent

```
PATCH /api/v1/agents/{agent_id}
```

**请求体**（部分更新）：
```json
{
  "name": "新名称",
  "description": "新描述"
}
```

### 删除 Agent（软删除）

```
DELETE /api/v1/agents/{agent_id}
```

将 `is_active` 设置为 `false`，不从数据库物理删除。

---

## Chat API

### 流式对话（推荐）

```
POST /api/v1/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

**请求体**：
```json
{
  "agent_id": "chatbot",
  "thread_id": "uuid-or-custom-string",
  "message": "你好，今天天气怎么样？",
  "model_id": "gpt-4o",
  "thinking_mode": false,
  "quote_message_id": "optional-quoted-message-uuid"
}
```

**参数说明**：
- `agent_id`: 要使用的 Agent ID（必填）
- `thread_id`: 会话 ID（必填，用于历史记录关联）
- `message`: 用户消息内容（必填）
- `model_id`: 覆盖默认模型（可选）
- `thinking_mode`: 是否启用深度思考模式（可选，默认 false）
- `quote_message_id`: 引用的历史消息 ID（可选）

**SSE 响应格式**：

```
data: {"type": "token", "content": "今天"}
data: {"type": "token", "content": "的"}
data: {"type": "token", "content": "天气"}
data: {"type": "tool_call_start", "tool": "web_search", "args": {"query": "北京天气"}}
data: {"type": "tool_call_end", "tool": "web_search", "result": "{\"temperature\": 25}"}
data: {"type": "token", "content": "很好"}
data: {"type": "done", "message_id": "msg-uuid", "token_stats": {"input": 150, "output": 50, "reasoning": 0}}
```

**事件类型**：
- `token`: LLM 输出的单个 Token
- `tool_call_start`: 工具调用开始
- `tool_call_end`: 工具调用完成
- `thinking`: 深度思考模式的思考内容
- `done`: 对话完成，包含 Token 统计

### 非流式对话

```
POST /api/v1/chat/invoke
```

**请求体** 同上

**响应**：
```json
{
  "content": "今天北京的天气是晴天，气温 25°C。",
  "message_id": "msg-uuid",
  "token_stats": {
    "input": 150,
    "output": 50,
    "reasoning": 0,
    "total": 200
  }
}
```

### 获取对话历史

```
GET /api/v1/chat/history/{agent_id}/{thread_id}
```

**响应**：
```json
[
  {
    "id": "msg-uuid-1",
    "role": "user",
    "content": "你好",
    "created_at": "2024-01-01T00:00:00Z",
    "token_stats": null
  },
  {
    "id": "msg-uuid-2",
    "role": "assistant",
    "content": "你好！有什么可以帮助你的？",
    "created_at": "2024-01-01T00:00:01Z",
    "token_stats": {
      "input": 10,
      "output": 15,
      "reasoning": 0
    }
  }
]
```

### 会话列表

```
GET /api/v1/chat/conversations?limit=20&offset=0
```

**响应**：
```json
[
  {
    "agent_id": "chatbot",
    "thread_id": "thread-uuid",
    "title": "天气查询",
    "message_count": 5,
    "last_message_at": "2024-01-01T00:00:00Z",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### 创建会话

```
POST /api/v1/chat/conversations
```

**请求体**：
```json
{
  "agent_id": "chatbot",
  "thread_id": "optional-custom-id",
  "title": "新会话"
}
```

### 删除会话

```
DELETE /api/v1/chat/conversations/{thread_id}
```

软删除，不物理删除数据。

### 获取会话标题

```
GET /api/v1/chat/title/{thread_id}
```

**响应**：
```json
{
  "title": "会话标题"
}
```

### 更新会话标题

```
POST /api/v1/chat/title
```

**请求体**：
```json
{
  "thread_id": "thread-uuid",
  "title": "新标题"
}
```

### 自动生成标题

```
POST /api/v1/chat/title/generate
```

**请求体**：
```json
{
  "thread_id": "thread-uuid"
}
```

使用 LLM 根据会话内容自动生成标题。

### 检查思考模式支持

```
GET /api/v1/chat/thinking-mode
```

**响应**：
```json
{
  "supported": true
}
```

---

## Model API

### 获取可用模型

```
GET /api/v1/models?provider_id=openai
```

只返回已配置 API Key 的 Provider 的模型。

**响应**：
```json
{
  "models": [
    {
      "id": "gpt-4o",
      "name": "GPT-4o",
      "provider_id": "openai",
      "model_type": "llm",
      "max_tokens": 128000,
      "supports_streaming": true,
      "supports_tools": true
    }
  ],
  "default_llm": "gpt-4o",
  "default_vlm": "gpt-4o",
  "default_embedding": "text-embedding-3-small"
}
```

### 获取所有模型（含未配置）

```
GET /api/v1/models/all
```

用于配置页面，展示所有支持的模型。

### 获取所有 Providers

```
GET /api/v1/models/providers
```

**响应**：
```json
[
  {
    "id": "openai",
    "name": "OpenAI",
    "base_url": "https://api.openai.com/v1",
    "api_key_configured": true
  }
]
```

### 创建模型配置

```
POST /api/v1/models
```

**请求体**：
```json
{
  "id": "custom-model",
  "name": "自定义模型",
  "provider_id": "openai",
  "model_type": "llm",
  "max_tokens": 8192,
  "supports_streaming": true,
  "supports_tools": true
}
```

### 更新模型配置

```
POST /api/v1/models/update
```

**请求体**：
```json
{
  "id": "gpt-4o",
  "name": "新名称",
  "max_tokens": 128000
}
```

### 删除模型配置

```
POST /api/v1/models/delete
```

**请求体**：
```json
{
  "id": "model-to-delete"
}
```

### 设置默认模型

```
POST /api/v1/models/set-default
```

**请求体**：
```json
{
  "model_type": "llm",
  "model_id": "gpt-4o"
}
```

`model_type` 可选值：`llm`, `vlm`, `embedding`

### 刷新模型缓存

```
POST /api/v1/models/refresh
```

手动触发模型列表缓存刷新（缓存 TTL 5 分钟）。

---

## Provider API

### 获取所有 Provider

```
GET /api/v1/providers
```

**响应**：
```json
[
  {
    "id": "openai",
    "name": "OpenAI",
    "base_url": "https://api.openai.com/v1",
    "api_key_configured": true,
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### 创建 Provider

```
POST /api/v1/providers
```

**请求体**：
```json
{
  "id": "anthropic",
  "name": "Anthropic",
  "base_url": "https://api.anthropic.com/v1",
  "api_key": "sk-xxx"
}
```

### 更新 Provider

```
POST /api/v1/providers/update
```

**请求体**：
```json
{
  "id": "openai",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-new-key"
}
```

### 删除 Provider

```
POST /api/v1/providers/delete
```

**请求体**：
```json
{
  "id": "provider-to-delete"
}
```

### 验证 API Key

```
POST /api/v1/providers/validate
```

**请求体**：
```json
{
  "id": "openai",
  "api_key": "sk-test-key"
}
```

**响应**：
```json
{
  "valid": true,
  "message": "API Key 验证成功"
}
```

---

## 使用示例

### Python 示例：流式对话

```python
import requests
import json

url = "http://localhost:8080/api/v1/chat/stream"
data = {
    "agent_id": "chatbot",
    "thread_id": "test-001",
    "message": "北京今天天气怎么样？",
    "model_id": "gpt-4o"
}

response = requests.post(url, json=data, stream=True)

for line in response.iter_lines():
    if line:
        line = line.decode('utf-8')
        if line.startswith('data: '):
            data_str = line[6:]
            if data_str == '[DONE]':
                break
            event = json.loads(data_str)
            if event['type'] == 'token':
                print(event['content'], end='', flush=True)
            elif event['type'] == 'done':
                print(f"\n\nToken 统计: {event['token_stats']}")
```

### JavaScript 示例：流式对话

```javascript
const response = await fetch('http://localhost:8080/api/v1/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    agent_id: 'chatbot',
    thread_id: 'test-001',
    message: '你好',
    model_id: 'gpt-4o'
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  const lines = chunk.split('\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data_str = line.slice(6);
      if (data_str === '[DONE]') continue;
      
      const event = JSON.parse(data_str);
      if (event.type === 'token') {
        process.stdout.write(event.content);
      }
    }
  }
}
```

### curl 示例

```bash
# 流式对话
curl -N -X POST http://localhost:8080/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "chatbot",
    "thread_id": "test-001",
    "message": "你好",
    "model_id": "gpt-4o"
  }'

# 获取 Agent 列表
curl http://localhost:8080/api/v1/agents

# 验证 Provider API Key
curl -X POST http://localhost:8080/api/v1/providers/validate \
  -H "Content-Type: application/json" \
  -d '{"id": "openai", "api_key": "sk-test"}'