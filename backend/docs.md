# 阶段 1: 项目整体架构分析（更新版 — 基于最新代码状态 + LangChain 官方文档）

> **说明**：经过 P0-P3 四轮重构，项目架构已完全符合 LangChain 官方范式。以下分析基于最新扫描结果。

---

## 1. 技术栈与关键依赖

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **Web 框架** | FastAPI | 0.121.2 | API 层、路由、依赖注入 |
| **Agent 框架** | LangChain | 1.3.1 | `create_agent` + middleware（v1 新范式 ✅） |
| **Agent 运行时** | LangGraph | 1.2.0 | 图执行引擎、状态机 |
| **LLM 集成** | langchain-litellm | 0.6.5 | 多模型统一接入（含 Router 内建 fallback） |
| **向量存储** | langchain-postgres | latest | RAG 向量检索（PGVector） |
| **搜索工具** | langchain-tavily | 0.2.18 | Web 搜索 |
| **短期记忆** | langgraph-checkpoint-postgres/sqlite | 3.1.0 | 对话状态持久化 |
| **长期记忆** | LangGraph Store (AsyncPostgresStore/InMemoryStore) | - | 跨会话用户记忆，通过 `@dynamic_prompt` 注入 system prompt |
| **数据库** | PostgreSQL (prod) / SQLite (dev) | - | 关系数据 + 向量 |
| **ORM** | SQLAlchemy (async) | - | 数据模型、CRUD |
| **数据校验** | Pydantic v2 | - | Schema、Settings |
| **可观测性** | LangSmith | 0.8.5 | Tracing |

---

## 2. 整体技术架构（三层架构）

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client (Frontend)                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼──────────────────────────────────────┐
│              API 层 (FastAPI Routes + Depends)                   │
│  ┌──────────┐ ┌──────┐ ┌───────┐ ┌──────────┐ ┌─────────────┐ │
│  │ /agents  │ │/chat │ │/models│ │/providers│ │ /traces     │ │
│  └──────────┘ └──┬───┘ └───┬───┘ └──────────┘ └──────┬──────┘ │
│     dependencies.py (get_db, RequestContext)                     │
│     stream.py (SSE 流式处理 v3 typed-projection)                │
└──────────────────┼──────────┼──────────────────┬────────────────┘
                   │          │                  │
┌──────────────────▼──────────▼──────────────────▼────────────────┐
│                   Agent 层 (LangChain v1)                        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  AgentRegistry (@register_agent) → create_agent + middleware││
│  │  ┌────────────────┐                                         ││
│  │  │ chatbot / ...  │  @dynamic_prompt + @wrap_model_call    ││
│  │  ├────────────────┤  LiteLLM Router 内建 fallback           ││
│  │  │ prompts/*.md   │  ← 每个 Agent 一个 MD 提示词文件       ││
│  │  └────────────────┘                                         ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
            │
┌───────────▼─────────────────────────────────────────────────────┐
│              Infrastructure 层                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ LLM Manager  │  │ Database     │  │ VectorStore           │ │
│  │ (litellm多模型│  │ Factory      │  │ Factory               │ │
│  │  + Router)   │  │ (单例工厂)   │  │ (PGVector/SQLite-vec) │ │
│  └──────────────┘  └──────┬───────┘  └───────────────────────┘ │
│  ┌──────────────┐  ┌──────▼───────┐  ┌───────────────────────┐ │
│  │ Model Manager│  │ Checkpointer │  │ Store                 │ │
│  │ (模型CRUD+缓存)│ │ Factory      │  │ Factory               │ │
│  │  缓存→Router  │  │ (PG/SQLite)  │  │ (AsyncPostgres/InMem) │ │
│  └──────────────┘  └──────────────┘  └───────────────────────┘ │
│  ┌──────────────┐  ┌──────────────┐                            │
│  │ Memory       │  │ Middleware   │                            │
│  │ (Manager +   │  │ (Prompt +    │                            │
│  │  Extractor + │  │  Model)      │                            │
│  │  Tools)      │  │              │                            │
│  └──────────────┘  └──────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心模块与依赖关系（当前状态）

### 3.1 请求处理主链路（Chat 流程）

```
Client POST /v1/chat/stream
    │
    ▼
app/api/v1/chat.py::stream()
    │
    ├── get_agent(agent_id)  ←── AgentRegistry
    │
    └── streaming_message_generator(user_input, agent)  ←── stream.py
              │
              ├── LiteLLM Router 内建 fallback（透明处理 429/403）
              ├── agent.astream_events(version="v3")   ←── typed projections
              │        ├── handle_input() ←── message_utils.py
              │        ├── stream.messages    → token deltas + usage + final
              │        ├── stream.tool_calls  → tool lifecycle
              │        ├── stream.values      → final state snapshot
              │        ├── AsyncWriteQueue (非阻塞 DB 写入)
              │        └── MemoryExtractor (后台记忆提取)
              │
              └── 返回 SSE StreamingResponse
```

**关键变化**：没有任何自定义 fallback 中间件。模型降级由 LiteLLM Router 内建 `fallbacks` 配置透明处理。

### 3.2 关键文件职责

| 文件 | 职责 |
|------|------|
| `api/v1/chat.py` | Chat 路由（stream/invoke/history） |
| `api/v1/stream.py` | SSE 流式处理 v3 typed-projection |
| `api/v1/model.py` | 模型 CRUD + 自动 `ModelManager.refresh()` |
| `api/v1/provider.py` | Provider CRUD + 自动 `ModelManager.refresh()` |
| `infra/llm/__init__.py` | LLM 包 re-export |
| `infra/llm/model_manager.py` | ModelManager（DB→缓存→LiteLLM Router） |
| `infra/llm/factory.py` | `get_llm()` / `get_chat_litellm()` 实例工厂 |
| `infra/llm/extra_body.py` | provider-specific thinking mode 控制 |
| `middleware/model/dynamic.py` | `@wrap_model_call` 运行时模型切换（通过 Router） |
| `middleware/prompt/dynamic.py` | `make_dynamic_prompt(agent_id)` 工厂 |
| `middleware/prompt/service.py` | PromptService（MD 加载 + 记忆缓存 + 拼接） |
| `agents/base.py` | AgentRegistry + @register_agent 注册基础设施 |
| `agents/__init__.py` | Agent 集中导出（每新增 agent 加一行 import） |
| `agents/chatbot.py` | Chatbot agent（create_agent + middleware） |
| `agents/types.py` | ChatbotContext @dataclass（Runtime context schema） |
| `prompts/chatbot.md` | Chatbot Agent 的系统提示词模板（MD 格式） |
| `observability/` | Checkpoint/Trace/DAG 读取 |

---

## 4. LangChain 官方文档对照分析

基于 LangChain 官方文档，项目当前实践与最佳实践的对照：

| 方面 | 官方推荐 | 项目现状 | 评估 |
|------|----------|----------|------|
| Agent 创建 | `create_agent` + middleware | ✅ 已使用 `create_agent` + middleware | **正确** |
| 流式输出 | `stream_events(version="v3")` | ✅ 已升级到 v3 typed-projection | **正确** |
| 运行时上下文 | `context` 参数 | ✅ `context` 传递 `ChatbotContext` dataclass | **正确** |
| 模型降级/回退 | ModelFallbackMiddleware + Router fallbacks | ✅ 使用 LiteLLM Router 内建 fallbacks + num_retries | **正确** |
| 动态模型切换 | `@wrap_model_call` + `context.model_name` | ✅ 通过 `dynamic_model` middleware + `factory.get_llm()` | **正确** |
| 动态 Prompt | `@dynamic_prompt` + Store 注入 | ✅ `make_dynamic_prompt(agent_id)` 工厂 | **正确** |
| 记忆（短期） | Checkpointer | ✅ 已使用 | **正确** |
| 记忆（长期） | Store + MemoryTools + `@dynamic_prompt` 注入 | ✅ Store 记忆通过 `@dynamic_prompt` 自动注入 system prompt，MemoryTools 提供显式读写 | **正确** |
| 可观测性 | LangSmith tracing | ✅ 已集成 | **正确** |
| Agent 注册/发现 | 无内置方案（开源侧） | ✅ 自行实现 AgentRegistry + @register_agent + Discovery API | **正确** |
| 提示词管理 | MD 外部文件 + `@dynamic_prompt` | ✅ PromptService 加载 `app/prompts/<agent_id>.md` | **正确** |

**现状**：项目已完全对齐 LangChain 官方推荐范式。

> **关于 Agent 注册机制**：LangChain 开源侧没有内置的 Agent Registry 或 Discovery API。
> LangSmith 的 Assistants API（CRUD + 版本管理 + 热切换）是付费部署特性。
> 项目自行实现的 `AgentRegistry` + `@register_agent` 是正确且必要的做法。


---

## 3.5. 新增 Agent 开发指南（Developer Onboarding）

> **面向**：需要在项目中新增 Agent 的开发者。项目采用 **"代码即配置"**
> 哲学：Agent 的工具、LLM、中间件在 Python 代码中写死，用户无法通过 API 修改。
> 提示词模板从 `app/prompts/<agent_id>.md` 外部加载。

### 前置条件

新增一个 Agent 需要准备三样东西：

| 步骤 | 对应位置 | 说明 |
|------|---------|------|
| 1. 写 Agent 代码 | `app/agents/<my_agent>.py` | 用 `create_agent()` + `@register_agent` 装饰器 |
| 2. 写提示词模板 | `app/prompts/<my_agent>.md` | Markdown 格式，支持 `{variable}` 时间变量占位符 |
| 3. 注册导出 | `app/agents/__init__.py` | 加一行 `from app.agents.<my_agent> import <my_agent>` |

### Step 1: 写 Agent 代码

以 `chatbot.py` 为模板，核心四步：

```
① 定义工具（硬编码）       →  静态列表或 lazy factory
② 定义 Runtime Context     →  @dataclass（LangChain v1 官方模式）
③ 编写 _create_*_agent()   →  调用 create_agent(model, tools, middleware, context_schema)
④ 编译 + 注册              →  @register_agent(...)(_create_*_agent())
```

**完整模板**（参考 `chatbot.py`）：

```python
# app/agents/my_agent.py

from dataclasses import dataclass
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware

from app.agents.base import register_agent
from app.infra.llm import get_chat_litellm, ModelManager
from app.middleware.prompt.dynamic import make_dynamic_prompt
from app.middleware.model.dynamic import dynamic_model
from app.middleware.memory.tools import memory_tools

# ── 1. 定义工具（硬编码，不可通过 API 修改） ──
MY_TOOLS = [*memory_tools]  # 长期记忆读写 + 你的自定义工具

# ── 2. Runtime Context ──
@dataclass
class MyAgentContext:
    """Runtime context — 通过 agent.invoke(context=ctx) 传入。"""
    user_id: str = ""
    request_id: str = ""
    model_name: str = ""
    thinking_mode: bool = False

# ── 3. Agent 创建 ──
def _create_my_agent():
    default_model = get_chat_litellm(ModelManager.get_default_llm_id())

    agent = create_agent(
        model=default_model,
        tools=MY_TOOLS,
        middleware=[
            make_dynamic_prompt("my_agent"),      # ← 自动加载 my_agent.md
            dynamic_model,                         # ← 运行时模型切换
            SummarizationMiddleware(
                model=default_model,
                trigger=("messages", 20),
                keep=("messages", 10),
            ),
        ],
        context_schema=MyAgentContext,
    )
    return agent

# ── 4. 编译 + 注册 ──
my_agent = register_agent(
    "my_agent",
    name="My Custom Agent",
    description="一句话描述这个 Agent 的功能",
    version="1.0.0",
    capabilities=["long_term_memory"],  # 前端 Discovery API 展示用
    tags=["custom"],
    factory=_create_my_agent,           # 供 POST /admin/reload 热重载
)(_create_my_agent())
```

### Step 2: 写提示词模板

在 `app/prompts/my_agent.md` 创建系统提示词文件。

**支持的时间变量**（由 `PromptService._build_time_context()` 在每次请求时注入）：

| 变量 | 示例值 | 说明 |
|------|--------|------|
| `{current_datetime}` | `2026-05-20 18:30:00` | 会话开始时的时间 |
| `{current_date}` | `2026-05-20` | 日期 |
| `{current_weekday}` | `Tuesday` | 星期 |
| `{iso_time}` | `2026-05-20T18:30:00` | ISO 8601 格式 |
| `{timestamp}` | `1747735800` | Unix 时间戳 |
| `{timezone}` | `Asia/Shanghai` | 服务器时区 |

**长期记忆注入**：如果 Store 可用且请求带有 `user_id`，
`PromptService` 会自动在 prompt 末尾追加用户的长期记忆块，
MD 文件中无需显式处理。

**文件命名约定**：`<agent_id>.md`，与 `register_agent` 的第一个参数保持一致。

### Step 3: 注册导出

在 `app/agents/__init__.py` 中加一行 import（此行触发 `@register_agent` 装饰器执行）：

```python
from app.agents.my_agent import my_agent   # ← 新增这一行
```

Agent 注册后自动获得：
- `GET /api/v1/agents/` — Discovery API 返回列表中自动出现
- `POST /api/v1/chat/stream` — 传 `"agent_id": "my_agent"` 即可调用
- `POST /api/v1/agents/admin/my_agent/reload` — 支持热重载

### 记忆机制说明

| 记忆类型 | 实现 | 注入方式 | 注入时机 |
|---------|------|---------|---------|
| **短期记忆**（对话历史） | `checkpointer` (PG/SQLite) | `agent.checkpointer = saver` | `main.py` lifespan 统一注入到所有 agent |
| **长期记忆**（跨会话） | `store` (AsyncPostgresStore/InMemoryStore) | ① `@dynamic_prompt` 自动注入 system prompt<br>② `memory_tools` 供 Agent 显式调用 | ① 每次模型调用前<br>② Agent 执行工具时 |

### Agent 间共用的中间件

| 中间件 | 装饰器 | 作用 | 是否每个 Agent 独立配置 |
|--------|--------|------|------------------------|
| 动态 Prompt | `@dynamic_prompt` | MD 模板 + 时间变量 + 长期记忆 | ✅ 是（需传 `agent_id` 以匹配 MD 文件） |
| 动态模型 | `@wrap_model_call` | 运行时按 `context.model_name` 切换 LLM | ❌ 否（共用 `dynamic_model` 实例） |
| 摘要裁剪 | `SummarizationMiddleware` | 对话过长时自动裁剪历史 | 共用，但可独立配置 `trigger`/`keep` |


---

## 5. 主要复杂点分析

### 🟡 中优先级

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 1 | **stream.py 仍偏大（~360 行）** | `api/v1/stream.py` | SSE 格式化、token 统计、DB 写入、记忆提取仍集中在同一文件 |
| 2 | **Schema 冗余** | `ChatMessage` vs `StepOutput` vs `MessageStep` | 消息模型重叠，维护成本高 |
| 3 | **chat.py 端点过多** | `/chat` 路由下有 12 个端点 | 部分 CRUD 端点（conversations CRUD）可拆分到独立路由 |

### 🟢 低优先级

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 4 | **provider.py 使用同步加密** | `utils/crypto.py` | API Key 加密可能是同步操作，在高并发下可能阻塞 |

---

## 6. 架构亮点（值得保留的设计）

| # | 设计 | 说明 |
|---|------|------|
| ✅ | **LangChain v1 `create_agent` + middleware** | 完全符合官方推荐范式 |
| ✅ | **三层架构** | Agent 是核心；PromptService / MemoryManager 作为轻量 Service 组件辅助 |
| ✅ | **FastAPI Depends 依赖注入** | `dependencies.py` 提供标准化的 DB session 和请求上下文 |
| ✅ | **LiteLLM Router 内建 fallback** | 无需自定义中间件，Router 自动处理 429/403/rate-limit + 同类型互备 |
| ✅ | **@wrap_model_call 动态模型切换** | 生产级运行时模型选择，通过 `factory.get_llm()` 使用 Router |
| ✅ | **@dynamic_prompt 动态提示词** | 每次模型调用前生成 system prompt（MD 模板 + 时间变量 + 长期记忆） |
| ✅ | **AsyncWriteQueue 非阻塞写入** | 流式处理中不阻塞主线程进行 DB 写入 |
| ✅ | **Checkpointer + Store 分离** | 短期/长期记忆分离，符合 LangGraph 最佳实践 |
| ✅ | **AgentRegistry + @register_agent** | 代码驱动的 agent 注册，CI/CD 友好，支持热重载 |
| ✅ | **LiteLLM 多模型统一接入** | 一套代码支持多模型，切换零成本 |
| ✅ | **LangSmith 集成** | 全链路 tracing |
| ✅ | **DB→内存缓存→Router** | 启动时/变更时自动从 DB 加载到内存缓存，构建 LiteLLM Router |

---

# 阶段 2: API 接口文档

> 基础路径：`/api/v1`（来自 `settings.API_V1_STR`）

---

## 全局路由总览

| 模块 | 前缀 | 端点数 | 核心度 |
|------|------|--------|--------|
| Health | `/` | 1 | 基础设施 |
| Chat | `/chat` | 12 | ⭐⭐⭐ 最核心 |
| Agent | `/agents` | 5 | ⭐⭐ 核心 |
| Model | `/models` | 7 | ⭐ 配置管理 |
| Provider | `/providers` | 2 | ⭐ 配置管理 |
| Trace | `/traces` | 6 | 可观测性 |

**总计：33 个端点**

---

## 1. Health Check

### `GET /health`
- **功能**：Docker 健康检查
- **标签**：`Health`
- **请求参数**：无
- **响应模型**：`{"status": "ok"}`
- **核心度**：基础设施（必须保留）

---

## 2. Chat 路由 (`/api/v1/chat`)

### `POST /chat/stream` ⭐⭐⭐ 核心
- **功能**：流式调用 Agent，返回 SSE 事件流
- **请求体**：`UserInput`
  ```json
  {
    "content": "你好",
    "agent_id": "chatbot",
    "thread_id": "uuid-string",
    "model_name": "qwen-plus",
    "thinking_mode": false,
    "user_id": "user-123"
  }
  ```
- **响应**：`text/event-stream` (SSE)
  - `token` 事件：`{"type": "token", "content": "你"}`
  - `reasoning` 事件：`{"type": "reasoning", "content": "思考过程..."}`
  - `step` 事件：`{"type": "step", "step": 1, "action": "tool_call", "name": "search", "status": "calling"}`
  - `usage` 事件：`{"type": "usage", "content": {"node": "model", "usage": {...}}}`
  - `message` 事件：`{"type": "message", "content": {...}}`
  - 结束标记：`data: [DONE]`
- **注**：模型回退由 LiteLLM Router 透明处理，无 `model_fallback` SSE 事件
- **涉及 Agent**：所有已注册 Agent
- **核心度**：⭐⭐⭐ 最核心的对话接口

### `POST /chat/invoke` ⭐⭐⭐ 核心
- **功能**：同步调用 Agent，返回完整响应
- **请求体**：同 `UserInput`
- **响应模型**：`ChatMessage`
  ```json
  {
    "type": "ai",
    "content": "你好！有什么可以帮你的？",
    "name": null,
    "id": "msg-xxx",
    "custom_data": {}
  }
  ```
- **涉及 Agent**：所有已注册 Agent
- **核心度**：⭐⭐⭐ 非流式调用接口

### `GET /chat/history/{agent_id}/{thread_id}` ⭐⭐ 核心
- **功能**：获取对话历史（含消息序列和侧边栏步骤）
- **路径参数**：`agent_id: str`, `thread_id: UUID`
- **响应模型**：`ChatHistory`
  ```json
  {
    "messages": [{"type": "human", "content": "...", ...}, {"type": "ai", "content": "...", ...}],
    "message_sequence": [{"step_number": 1, "checkpoint_id": "...", ...}]
  }
  ```
- **核心度**：⭐⭐ 前端主界面依赖

### `POST /chat/title/generate` ⭐
- **功能**：使用 LLM 生成对话标题
- **请求体**：`TitleGenerateRequest`
  ```json
  {"user_message": "帮我写个Python脚本", "ai_response": "好的，我来帮你..."}
  ```
- **响应模型**

----
