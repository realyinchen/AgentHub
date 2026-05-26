# 🚀 AgentHub — AI 智能体编排平台

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

<p align="center">
  <strong>基于 FastAPI + LangGraph v1 的生产级多 Agent 后端服务平台。一个会话，动态切换模型与智能体，零样板代码扩展。</strong>
</p>

<p align="center">
  <a href="https://github.com/realyinchen/AgentHub/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License">
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi" alt="FastAPI">
  </a>
  <a href="https://www.langchain.com/langgraph">
    <img src="https://img.shields.io/badge/LangGraph_v1-FF5E0E?logo=langchain" alt="LangChain">
  </a>
  <a href="https://react.dev/">
    <img src="https://img.shields.io/badge/React_19-61dafb?logo=react" alt="React">
  </a>
  <a href="https://docs.pydantic.dev/latest/">
    <img src="https://img.shields.io/badge/Pydantic_v2-E92063?logo=pydantic" alt="Pydantic v2">
  </a>
</p>

<p align="center">
  <!-- 📸 主界面截图占位 -->
  <img src="https://via.placeholder.com/800x450?text=AgentHub+Demo+Screenshot" alt="AgentHub Demo" width="800">
</p>

---

## 快速开始

### Docker Compose（推荐）

```bash
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# 创建宿主机目录
mkdir -p /app/agenthub/backend/data /app/agenthub/frontend

# 拷贝并编辑环境变量
cp backend/.env.example /app/agenthub/backend/.env
cp frontend/.env.example /app/agenthub/frontend/.env
# vim /app/agenthub/backend/.env   ← 填入 API Keys

# 构建并启动
docker compose build
docker compose up -d
```

访问 `http://localhost` 即可使用。默认为 **SQLite + sqlite-vec** 模式（零外部依赖）。

### 手动开发环境

**后端**

```bash
cd backend
cp .env.example .env    # 编辑 .env，填入 API 密钥
pip install -r requirements.txt
python scripts/init_database.py
python run_backend.py
```

**前端**

```bash
cd frontend
cp .env.example .env
npm install
npm run dev              # 访问 http://localhost:5173
```

### 最小环境变量

`.env` 中必须配置：

| 变量 | 说明 |
|------|------|
| `SYSTEM_DEFAULT_LLM_MODEL` | 格式 `provider/model-id`（如 `zai/glm-5.1`） |
| `SYSTEM_DEFAULT_LLM_API_KEY` | 对应 Provider 的 API Key |
| `API_KEY_ENCRYPTION_KEY` | 32 字符 AES-256 密钥（用于加密存储 API Key） |

---

## 并发执行机制

AgentHub 采用 **单进程 asyncio 事件循环 + 协程 (coroutine)** 模型。每个 HTTP 请求由 Uvicorn 接收后，作为一个独立协程在同一个事件循环中被调度执行。

### 协程调度

```
uvicorn 事件循环
    │
    ├── 请求 A 到达 → 创建协程 → 当 await I/O 时挂起
    ├── 请求 B 到达 → 创建协程 → 当 await I/O 时挂起
    └── 请求 C 到达 → 创建协程 → 事件循环调度到 A 恢复执行
```

每个请求协程在以下 I/O 点主动让出控制权（`await`）：
- **LLM 调用**：`astream_events()` 等待流式响应（通常是耗时最长的阶段）
- **DB 查询**：`asyncpg` 等待 PostgreSQL 返回结果
- **工具调用**：Tavily 搜索、矢量检索等外部 API
- **Prompt 缓存**：缓存命中零 I/O，miss 时异步加载 MD 文件

**当一个请求正在等待 LLM 流式返回时，事件循环可以处理成百上千个其他请求的协程。**

### 无全局锁设计

| 共享资源 | 并发访问方式 |
|----------|-------------|
| **RegistrySnapshot** | frozen dataclass，CPython 原子引用赋值，所有请求零锁读取 |
| **LiteLLM Router** | 全局单例。每个请求通过 `get_llm()` 创建轻量 wrapper，底层 Router 线程安全 |
| **PromptService TTLCache** | `asyncio.Lock` 仅缓存 miss 时获取，命中时零锁 |
| **DB 连接池** | SQLAlchemy AsyncEngine 池化管理（默认 min=2, max=10） |

### SSE 流内部的并发

`streaming_message_generator()` 使用 `asyncio.gather()` 并发运行三个投影消费者：
- `consume_messages` — 监听 LLM token / reasoning / usage 事件
- `consume_tool_calls` — 监听工具调用生命周期
- `consume_values` — 捕获最终 state.messages 快照

三者通过 `asyncio.Queue` + sentinel 信号汇聚，事件到达即刻推送（零轮询延迟）。持久化（Token 累计 / DAG 快照）通过 `AsyncWriteQueue` 后台写入，**不阻塞 SSE 流**。

### 扩容

单进程默认配置可支撑数千并发请求。扩展方式：
- **垂直扩展**：增加 Uvicorn `workers` 参数（每 worker 独立进程 + GIL）
- **水平扩展**：K8s Horizontal Pod Autoscaler

---

## 系统架构

<!-- 📸 架构分层图占位 -->
```
                    ┌──────────────────────────────┐
                    │       HTTP 接入层 (API)        │
                    │  Pydantic 校验 → 路由 → SSE    │
                    └──────────────┬───────────────┘
                                   │ get_graph(agent_id)
                    ┌──────────────▼───────────────┐
                    │      Agent 编排层 (Agent)      │
                    │  RegistrySnapshot · 中间件链   │
                    │  @dynamic_prompt → @wrap_model│
                    │   _call → Summarization       │
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
    ┌─────────▼─────────┐ ┌───────▼───────┐ ┌─────────▼─────────┐
    │  基础设施层 (Infra) │ │  数据层 (Data) │ │  可观测性 (Obsrv)  │
    │  LLM · DB · Tools  │ │  ORM · CRUD   │ │  TraceBuilder     │
    └───────────────────┘ └───────────────┘ └───────────────────┘
```

**依赖方向严格单向**：`API → Agent → Infra → Data`，无循环依赖。

### 核心设计：AgentSpec 工厂模式

AgentHub 的 Agent 创建采用 **「Spec → Factory → Auto-Registration」** 三段式：

```
  定义规范               编译生成              自动发现
┌──────────────┐    ┌─────────────────┐    ┌──────────────────┐
│ AgentSpec    │───▶│ create_standard  │───▶│ register_factory │
│  · agent_id  │    │ _agent()        │    │   ↓              │
│  · tools     │    │                 │    │ reload_agents()  │
│  · context   │    │ middleware chain │    │   ↓              │
│  · prompt    │    │ [prompt→model   │    │ RegistrySnapshot │
│  · summary   │    │  →summary]      │    └──────────────────┘
└──────────────┘    └─────────────────┘
```

- **`AgentSpec`**：frozen dataclass，包含 Agent 的全部编译期配置。配置错误在启动时立即暴露。
- **`create_standard_agent()`**：薄封装（~50 行），从 `AgentSpec` 取值，组装中间件链，调用 `langchain.agents.create_agent()`。95% 的 Agent 直接使用它，零样板代码。
- **自动发现**：`agents/__init__.py` 通过 `pkgutil.iter_modules` 遍历子目录，触发模块导入。每个 Agent 模块在导入时调用 `register_factory()` 自我注册。

### 中间件链

每个 Agent 的每次模型调用都会经过统一的中间件链：

| 顺序 | 中间件 | Hook | 功能 |
|------|--------|------|------|
| ① | `@dynamic_prompt` | `@dynamic_prompt` | 从 `app/prompts/<agent_id>.md` 加载模板，注入当前时间等动态上下文 |
| ② | `@wrap_model_call` | `@wrap_model_call` | 从 `context.model_name` 读取用户选择的模型，通过 `request.override(model=llm)` 动态切换 |
| ③ | `SummarizationMiddleware` | 内置 | 当会话 tokens > 4,000 时自动压缩历史消息（保留最近 20 条） |

### 如何添加新 Agent（3 步）

假设要添加一个 RAG 检索增强 Agent：

```python
# 1. 创建 agents/rag_agent/ 目录
# agents/rag_agent/__init__.py  — 模块导入时自动触发注册
# agents/rag_agent/types.py

from dataclasses import dataclass
from app.agents.types import AgentRuntimeContext

@dataclass
class RAGContext(AgentRuntimeContext):
    collection_id: str = ""
    top_k: int = 5

# agents/rag_agent/agent.py
from app.agents.registry import register_factory
from app.agents.factory import AgentSpec, create_standard_agent
from app.agents.rag_agent.types import RAGContext

def _get_rag_tools():
    return [vectorstore_search, web_search]

def _create_rag_agent(checkpointer=None, store=None):
    return create_standard_agent(
        AgentSpec(
            agent_id="rag_agent",
            tools_factory=_get_rag_tools,
            context_schema=RAGContext,
            prompt_agent_id="rag_agent",
        ),
        checkpointer=checkpointer,
        store=store,
    )

register_factory("rag_agent", _create_rag_agent)

# 2. 创建 app/prompts/rag_agent.md
# "你是一个基于文档检索的知识问答助手..."

# 3. 数据库激活
# INSERT INTO agents (agent_id, description, is_active) VALUES ('rag_agent', 'RAG 知识检索', true);
```

**无需修改** `factory.py`、`registry.py`、`main.py`、任何 API 路由。Agent 添加是纯增量操作。

### 这种模式的优势

| 维度 | 说明 |
|------|------|
| **零样板代码** | `create_standard_agent()` 自动注入中间件链，Agent 开发者只需提供 tools 和 context |
| **公共中间件全局升级** | 所有 Agent 共享同一套 prompt / model / summary 中间件。增加新的全局中间件（如审计日志）只需改 `factory.py` 一处，所有 Agent 自动受益 |
| **DB 驱动生命周期** | Agent 上下线由数据库 `is_active` 字段控制。`PATCH /api/v1/agents/{id}` 即可热切换，无需重启 |
| **原子热加载** | `RegistrySnapshot` 是 frozen dataclass，`relogin_agents()` 原子替换引用。请求始终看到一致的快照，无分裂脑风险 |
| **类型安全** | `context_schema` 使用 `@dataclass`（非 TypedDict），中间件通过属性访问 `ctx.model_name`，IDE 完整补全和类型检查 |
| **两层 LLM 隔离** | System LLM（摘要/标题）与 User LLM（对话）完全解耦，各自独立的 fallback 和配置 |

### 技术栈

| 层级 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn（异步） |
| AI 编排 | LangChain v1 + LangGraph（`create_agent`, middleware, `astream_events v3`） |
| LLM 网关 | LiteLLM Router（多 Provider 自动 fallback + retry） |
| 数据校验 | Pydantic v2 + ConfigDict |
| ORM | SQLAlchemy 2.0（async + Mapped 声明式） |
| 开发存储 | SQLite + sqlite-vec |
| 生产存储 | PostgreSQL + pgvector + asyncpg |
| 前端 | React 19 + TypeScript + Tailwind CSS + shadcn/ui |

---

## 后端目录结构

```
backend/app/
├── main.py                      # FastAPI 入口 + lifespan 初始化
├── api/                         # HTTP 接入层
│   ├── errors.py                # 全局异常处理
│   └── v1/
│       ├── router.py            # 路由聚合
│       ├── dependencies.py      # 依赖注入 (get_db)
│       ├── chat.py              # 流式/非流式对话、历史查询
│       ├── chat_session.py      # 会话 CRUD、统计、thinking 模式
│       ├── chat_title.py        # 标题 CRUD + LLM 自动生成
│       ├── agent.py             # Agent 发现与上下线管理
│       ├── model.py             # 模型 CRUD 与动态选择
│       ├── provider.py          # Provider API Key 配置
│       ├── stream.py            # SSE 流式引擎 (astream_events v3)
│       └── trace.py             # Trace Kanban 路由
├── agents/                      # Agent 编排层
│   ├── __init__.py              # pkgutil 自动发现子模块
│   ├── registry.py              # DB 驱动注册表 + RegistrySnapshot
│   ├── factory.py               # AgentSpec + create_standard_agent()
│   ├── types.py                 # AgentRuntimeContext (@dataclass 基类)
│   ├── middleware/
│   │   ├── prompt.py            # @dynamic_prompt (MD 模板 + 时间注入)
│   │   └── model.py             # @wrap_model_call (运行时模型切换)
│   └── chatbot/                 # Agent: 通用对话机器人
│       ├── chatbot.py           # 工厂 + 工具定义 + 注册
│       └── types.py             # ChatbotContext
├── infra/                       # 基础设施层
│   ├── config.py                # pydantic-settings (MODE 驱动配置)
│   ├── database/                # DB / VectorStore / Checkpointer / Store
│   ├── llm/
│   │   ├── model_manager.py     # Router 缓存、模型回退、热加载
│   │   ├── factory.py           # get_llm() — 每请求 Router 绑定
│   │   ├── system.py            # get_system_default_llm() — .env 驱动单例
│   │   └── extra_body.py        # Provider 特定参数构建
│   └── tools/                   # @tool 定义 (time, web, sql, vectorstore)
├── models/                      # SQLAlchemy 2.0 Mapped ORM 模型
├── schemas/                     # Pydantic v2 请求/响应 Schema
├── crud/                        # 异步数据库操作封装
├── observability/               # 只读追踪重建
│   ├── trace.py                 # TraceBuilder (从 checkpoint 重建执行步骤)
│   ├── dag.py                   # 执行 DAG 构建
│   ├── parsers.py               # 消息内容/thinking 解析
│   └── checkpoint.py            # Checkpoint 工具
├── utils/                       # 共享工具
│   ├── async_writer.py          # 异步写入队列 (非阻塞持久化)
│   ├── cache.py                 # TTL 缓存
│   ├── crypto.py                # AES-GCM API Key 加解密
│   ├── message_utils.py         # 统一消息转换
│   ├── request_handler.py       # 请求 → Agent 参数转换
│   └── stream_events.py         # SSE 事件类型定义
└── prompts/                     # System Prompt MD 模板
    └── chatbot.md               # "通用助手, 当前时间{current_datetime}..."
```

---

## 已有 Agent

| Agent ID | 描述 | 工具 | 上下文类型 |
|----------|------|------|-----------|
| `chatbot` | 通用对话助手，支持实时时间查询和网络搜索 | `get_current_time`（时区感知）、`web_search`（Tavily） | `ChatbotContext` — 继承 `AgentRuntimeContext`，新增 `file` 字段 |

### Chatbot 说明

- **时间工具**：支持任意 IANA 时区（如 `Asia/Shanghai`、`America/New_York`），默认为 `Asia/Singapore`
- **网络搜索**：基于 Tavily Search API。API Key 缺失时自动降级为纯时间模式（不崩溃）
- **Prompt**：`app/prompts/chatbot.md`，动态注入当前时间上下文
- **中间件**：完整的 prompt → model → summary 链，支持每请求动态模型切换和 thinking mode
- **会话摘要**：超过 4,000 tokens 时自动触发，压缩为最近 20 条消息摘要

---

## 许可证

本项目采用 [Apache 2.0 许可证](LICENSE)。