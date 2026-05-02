# API Reference

## Overview

All API endpoints are prefixed with `/api/v1`. After starting the backend, you can access `http://localhost:8080/docs` to view the interactive Swagger UI documentation.

## General Conventions

### Authentication

The current version is in open mode, no authentication token required. It is recommended to add authentication middleware for production environments.

### Pagination

List interfaces support pagination parameters:
- `limit`: int, 1-100, default 20
- `offset`: int, default 0
- Response header includes `X-Total-Count`: Total record count

### Error Format

```json
{
  "detail": "Error description message"
}
```

HTTP status codes:
- `200`: Success
- `400`: Request parameter error
- `404`: Resource not found
- `429`: Request limit exceeded (rate limiting)
- `500`: Server error

### Rate Limiting

| Interface | Limit |
|-----------|-------|
| Agent CRUD | 30/min |
| Chat Stream | 10/min |
| Chat History | 60/min |
| Model/Provider | 30/min |

---

## Agent API

### Get Agent List

```
GET /api/v1/agents?active_only=true&limit=20&offset=0
```

**Query Parameters**:
- `active_only`: bool (default true) - Only return active Agents
- `limit`: int (1-100)
- `offset`: int

**Response**:
```json
[
  {
    "id": "chatbot",
    "name": "General Conversation Assistant",
    "description": "General conversation Agent supporting web search",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
]
```

### Get Agent Details

```
GET /api/v1/agents/{agent_id}
```

### Create Agent

```
POST /api/v1/agents
```

**Request Body**:
```json
{
  "id": "my_agent",
  "name": "My Agent",
  "description": "Agent description",
  "is_active": true
}
```

### Update Agent

```
PATCH /api/v1/agents/{agent_id}
```

**Request Body** (partial update):
```json
{
  "name": "New name",
  "description": "New description"
}
```

### Delete Agent (soft delete)

```
DELETE /api/v1/agents/{agent_id}
```

Sets `is_active` to `false`, does not physically delete from the database.

---

## Chat API

### Streaming Conversation (Recommended)

```
POST /api/v1/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

**Request Body**:
```json
{
  "agent_id": "chatbot",
  "thread_id": "uuid-or-custom-string",
  "message": "Hello, how's the weather today?",
  "model_id": "gpt-4o",
  "thinking_mode": false,
  "quote_message_id": "optional-quoted-message-uuid"
}
```

**Parameter Description**:
- `agent_id`: Agent ID to use (required)
- `thread_id`: Session ID (required, used for history association)
- `message`: User message content (required)
- `model_id`: Override default model (optional)
- `thinking_mode`: Whether to enable deep thinking mode (optional, default false)
- `quote_message_id`: Quoted historical message ID (optional)

**SSE Response Format**:

```
data: {"type": "token", "content": "Today's"}
data: {"type": "token", "content": "weather"}
data: {"type": "token", "content": "is"}
data: {"type": "tool_call_start", "tool": "web_search", "args": {"query": "Beijing weather"}}
data: {"type": "tool_call_end", "tool": "web_search", "result": "{\"temperature\": 25}"}
data: {"type": "token", "content": "nice"}
data: {"type": "done", "message_id": "msg-uuid", "token_stats": {"input": 150, "output": 50, "reasoning": 0}}
```

**Event Types**:
- `token`: Single Token output by LLM
- `tool_call_start`: Tool call started
- `tool_call_end`: Tool call completed
- `thinking`: Deep thinking mode thinking content
- `done`: Conversation completed, includes Token statistics

### Non-Streaming Conversation

```
POST /api/v1/chat/invoke
```

**Request Body** Same as above

**Response**:
```json
{
  "content": "Today the weather in Beijing is sunny with a temperature of 25°C.",
  "message_id": "msg-uuid",
  "token_stats": {
    "input": 150,
    "output": 50,
    "reasoning": 0,
    "total": 200
  }
}
```

### Get Conversation History

```
GET /api/v1/chat/history/{agent_id}/{thread_id}
```

**Response**:
```json
[
  {
    "id": "msg-uuid-1",
    "role": "user",
    "content": "Hello",
    "created_at": "2024-01-01T00:00:00Z",
    "token_stats": null
  },
  {
    "id": "msg-uuid-2",
    "role": "assistant",
    "content": "Hello! How can I help you?",
    "created_at": "2024-01-01T00:00:01Z",
    "token_stats": {
      "input": 10,
      "output": 15,
      "reasoning": 0
    }
  }
]
```

### Session List

```
GET /api/v1/chat/sessions?limit=20&offset=0
```

**Response**:
```json
[
  {
    "agent_id": "chatbot",
    "thread_id": "thread-uuid",
    "title": "Weather Query",
    "message_count": 5,
    "last_message_at": "2024-01-01T00:00:00Z",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### Create Session

```
POST /api/v1/chat/sessions
```

**Request Body**:
```json
{
  "agent_id": "chatbot",
  "thread_id": "optional-custom-id",
  "title": "New Session"
}
```

### Delete Session

```
DELETE /api/v1/chat/sessions/{thread_id}
```

Soft delete, does not physically delete data.

### Get Session Title

```
GET /api/v1/chat/title/{thread_id}
```

**Response**:
```json
{
  "title": "Session Title"
}
```

### Update Session Title

```
POST /api/v1/chat/title
```

**Request Body**:
```json
{
  "thread_id": "thread-uuid",
  "title": "New Title"
}
```

### Auto-Generate Title

```
POST /api/v1/chat/title/generate
```

**Request Body**:
```json
{
  "thread_id": "thread-uuid"
}
```

Automatically generates title using LLM based on session content.

### Check Thinking Mode Support

```
GET /api/v1/chat/thinking-mode
```

**Response**:
```json
{
  "supported": true
}
```

---

## Model API

### Get Available Models

```
GET /api/v1/models?provider_id=openai
```

Only returns models from Providers with configured API Keys.

**Response**:
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

### Get All Models (including unconfigured)

```
GET /api/v1/models/all
```

Used for configuration pages, showing all supported models.

### Get All Providers

```
GET /api/v1/models/providers
```

**Response**:
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

### Create Model Configuration

```
POST /api/v1/models
```

**Request Body**:
```json
{
  "id": "custom-model",
  "name": "Custom Model",
  "provider_id": "openai",
  "model_type": "llm",
  "max_tokens": 8192,
  "supports_streaming": true,
  "supports_tools": true
}
```

### Update Model Configuration

```
POST /api/v1/models/update
```

**Request Body**:
```json
{
  "id": "gpt-4o",
  "name": "New Name",
  "max_tokens": 128000
}
```

### Delete Model Configuration

```
POST /api/v1/models/delete
```

**Request Body**:
```json
{
  "id": "model-to-delete"
}
```

### Set Default Model

```
POST /api/v1/models/set-default
```

**Request Body**:
```json
{
  "model_type": "llm",
  "model_id": "gpt-4o"
}
```

`model_type` optional values: `llm`, `vlm`, `embedding`

### Refresh Model Cache

```
POST /api/v1/models/refresh
```

Manually trigger model list cache refresh (cache TTL 5 minutes).

---

## Provider API

### Get All Providers

```
GET /api/v1/providers
```

**Response**:
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

### Create Provider

```
POST /api/v1/providers
```

**Request Body**:
```json
{
  "id": "anthropic",
  "name": "Anthropic",
  "base_url": "https://api.anthropic.com/v1",
  "api_key": "sk-xxx"
}
```

### Update Provider

```
POST /api/v1/providers/update
```

**Request Body**:
```json
{
  "id": "openai",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-new-key"
}
```

### Delete Provider

```
POST /api/v1/providers/delete
```

**Request Body**:
```json
{
  "id": "provider-to-delete"
}
```

### Validate API Key

```
POST /api/v1/providers/validate
```

**Request Body**:
```json
{
  "id": "openai",
  "api_key": "sk-test-key"
}
```

**Response**:
```json
{
  "valid": true,
  "message": "API Key validation successful"
}
```

---

## Usage Examples

### Python Example: Streaming Conversation

```python
import requests
import json

url = "http://localhost:8080/api/v1/chat/stream"
data = {
    "agent_id": "chatbot",
    "thread_id": "test-001",
    "message": "How's the weather in Beijing today?",
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
                print(f"\n\nToken statistics: {event['token_stats']}")
```

### JavaScript Example: Streaming Conversation

```javascript
const response = await fetch('http://localhost:8080/api/v1/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    agent_id: 'chatbot',
    thread_id: 'test-001',
    message: 'Hello',
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
      const dataStr = line.slice(6);
      if (dataStr === '[DONE]') continue;
      
      const event = JSON.parse(dataStr);
      if (event.type === 'token') {
        process.stdout.write(event.content);
      }
    }
  }
}
```

### curl Example

```bash
# Streaming conversation
curl -N -X POST http://localhost:8080/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "chatbot",
    "thread_id": "test-001",
    "message": "Hello",
    "model_id": "gpt-4o"
  }'

# Get Agent list
curl http://localhost:8080/api/v1/agents

# Validate Provider API Key
curl -X POST http://localhost:8080/api/v1/providers/validate \
  -H "Content-Type: application/json" \
  -d '{"id": "openai", "api_key": "sk-test"}'