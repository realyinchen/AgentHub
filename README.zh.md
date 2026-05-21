# 🚀 AgentHub - AI 智能体编排平台

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

<p align="center">
  <strong>编排、切换、协作 AI 智能体的终极平台。一个会话，无限可能。</strong>
</p>

<p align="center">
  <a href="https://github.com/realyinchen/AgentHub/stargazers">
    <img src="https://img.shields.io/github/stars/realyinchen/agenthub?style=social" alt="GitHub stars">
  </a>
  <a href="https://github.com/realyinchen/AgentHub/network/members">
    <img src="https://img.shields.io/github/forks/realyinchen/agenthub?style=social" alt="GitHub forks">
  </a>
  <a href="https://github.com/realyinchen/AgentHub/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License">
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi" alt="FastAPI">
  </a>
  <a href="https://react.dev/">
    <img src="https://img.shields.io/badge/React_19-61dafb?logo=react" alt="React">
  </a>
  <a href="https://www.langchain.com/langgraph">
    <img src="https://img.shields.io/badge/LangGraph-FF5E0E?logo=langchain" alt="LangChain">
  </a>
</p>

<p align="center">
  <img src="https://github.com/realyinchen/AgentLab/blob/main/imgs/demo.gif?raw=true" alt="AgentHub Demo">
</p>

---

## ✨ 核心特性

| 特性 | 描述 |
|------|------|
| 🎛️ **动态智能体 & 模型切换** | 在**同一会话中**实时切换任意智能体和底层 LLM（OpenAI、Anthropic、Groq、Ollama、本地模型）— 历史不丢失 |
| 🧠 **Chatbot 主控智能体** | 智能路由与任务规划。自动理解用户意图、分解任务、选择最优子智能体执行 |
| ⚡ **多智能体协作编排** | 支持并行、顺序、条件路由工作流。复杂决策支持人类介入（Human-in-the-loop） |
| 🔌 **插件化智能体生态** | 轻松注册新智能体，完整支持 LangChain 组件：工具、记忆、RAG、图工作流 |
| 💬 **现代对话界面** | React 前端支持 Markdown、语法高亮、实时流式输出、会话管理、智能体卡片切换 |
| 📊 **Token 可视化** | 实时 Token 消耗柱状图（输入/输出/推理），支持暗模式和国际化 |
| 🔍 **智能体执行时间线** | 实时展示中间步骤：推理过程、带参数和结果的工具调用 |
| 📋 **Kanban 仪表盘** | 全链路追踪可视化：会话/轮次追踪、每日 Token 统计（会话数/总Token/输入/输出/推理）、执行 DAG 图、并行工具检测、子智能体运行监控 |
| 🗄️ **零依赖存储** | SQLite + sqlite-vec 嵌入式数据库。30 秒启动，无需任何外部服务 |
| 🏭 **生产级架构** | 完整 PostgreSQL + Qdrant 支持，应对高并发部署。一键配置切换，**零代码改动** |

---

## 🎯 为什么选择 AgentHub？

| 传统聊天机器人 | AgentHub |
|---------------|----------|
| ❌ **单一、固定的智能体** | ✅ **智能体超市 + 智能大脑** |
| ❌ 一个会话只能用一个模型 | ✅ 对话中途随意切换模型 |
| ❌ 硬编码的工具集成 | ✅ 每个智能体动态绑定工具 |
| ❌ 无任务分解能力 | ✅ 主控智能体自动规划与路由 |
| ❌ 生产环境需要重写 | ✅ 同一代码库支持开发和生产 |

**AgentHub 面向的开发者群体**：
- 希望使用完整开发者工具栈，更快交付 AI 应用
- 想在零基础设施开销下实验多智能体编排
- 构建可从 SQLite 扩展到 PostgreSQL 的生产级系统

---

## 🖼️ 产品截图

| 智能体切换 | 主控智能体规划 |
|-----------|--------------|
| ![Agent 切换](https://via.placeholder.com/600x350?text=Agent+Market+UI) | ![规划](https://via.placeholder.com/600x350?text=Master+Agent+Planning) |

| 多智能体执行 | 模型供应商配置 |
|------------|-------------|
| ![执行](https://via.placeholder.com/600x350?text=Multi+Agent+Execution) | ![配置](https://via.placeholder.com/600x350?text=LLM+Configuration) |

| Kanban 仪表盘 | 执行 DAG 图 |
|--------------|-------------|
| ![Kanban](https://via.placeholder.com/600x350?text=Kanban+Dashboard) | ![DAG](https://via.placeholder.com/600x350?text=Execution+DAG) |

---

## 🚀 快速开始

### ⚠️ 重要提醒（必读！）

`docker-compose.yml` 使用 **绝对路径** 映射宿主机目录和 `.env` 文件，启动前必须手动创建目录，否则 Docker 会启动失败。

---

### 方式一：Docker Compose 一键启动（推荐）

#### 前置条件
- Docker + Docker Compose

```bash
# 1. 克隆项目
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# 2. 创建宿主机目录（⭐ 最重要的一步）
mkdir -p /app/agenthub/backend/data
mkdir -p /app/agenthub/frontend

# 3. 拷贝环境变量文件到指定位置
cp backend/.env.example /app/agenthub/backend/.env
cp frontend/.env.example /app/agenthub/frontend/.env

# 4. 编辑后端配置（填入你的 API Keys）
vim /app/agenthub/backend/.env
# TAVILY_API_KEY=your-key
# AMAP_API_KEY=your-key

# 5. 构建并启动
docker compose build
docker compose up -d

# 6. 查看运行状态
docker compose ps
docker compose logs -f
```

**访问地址**：
- 本地：http://localhost
- 服务器：http://你的服务器IP

> ✅ 默认为 **SQLite + sqlite-vec** 模式（零外部依赖）

---

### 方式二：手动开发环境搭建

#### 前置条件
- Python 3.11+
- Node.js 20+

#### 后端

```bash
cd backend
cp .env.example .env
# 编辑 .env，填入 API 密钥

pip install -r requirements.txt
python scripts/init_database.py
python run_backend.py
```

#### 前端

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

**访问地址**：http://localhost:5173

---

### 更多部署方式（PostgreSQL + Qdrant、前后端分离部署）请查看 [部署指南](docs/deployment.zh.md)。

---

## 📚 文档中心

- [🏗️ 数据库抽象架构](docs/database-abstraction.zh.md) - 两层架构，零依赖到生产级
- [➕ 添加新智能体指南](docs/add-new-agent.zh.md) - 构建和注册自定义智能体
- [📡 API 参考](docs/api-reference.zh.md) - 完整 API 文档
- [🐳 部署指南](docs/deployment.zh.md) - Docker、Kubernetes 及生产部署
- [⚙️ 配置参考](docs/configuration.zh.md) - 所有环境变量详解
- [💻 开发指南](docs/development.zh.md) - 贡献者指南和最佳实践

---

## 🏗️ 架构设计

### 分层架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            请求层 (REQUEST)                              │
│                                                                          │
│   uvicorn + FastAPI — lifespan 初始化所有服务                            │
│                                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                           接口层 (API)                                   │
│                                                                          │
│   提供 HTTP/SSE 接口，参数校验，全局异常处理                               │
│                                                                          │
│   chat      — 对话流式/非流式、历史、会话管理                             │
│   agent     — Agent 发现与配置                                           │
│   model     — 模型 CRUD 与动态选择                                       │
│   provider  — API Key 配置管理                                           │
│   trace     — 执行追踪、DAG 可视化、步骤回放                              │
│                                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                       Agent 运行时层 (AGENT RUNTIME)                      │
│                                                                          │
│   Agent 的编译、缓存和运行时调度                                          │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │  注册表 — 中央注册表（DB 驱动 + 原子快照，零锁读，自动发现）       │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │  中间件 — 共享中间件（所有 Agent 复用）                            │   │
│   │  · 动态模型选择  · 动态提示词注入                                  │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │  Agent 实例 — 独立子包，自动发现                                   │   │
│   │  · Chatbot  · RAG Agent  · Multi-Agent Supervisor  · ...        │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
├───────────────┬─────────────────────────────────────────────────────────┤
│               │                                                          │
│  基础设施层    │  可观测性层 (OBSERVABILITY)                              │
│  (INFRA)      │                                                          │
│               │  只读分析，不参与运行时路径                                │
│  基础能力      │                                                          │
│               │  · TraceBuilder                                          │
│  · Config     │    从 checkpoint 重建执行步骤                             │
│    全局配置    │                                                          │
│               │  · Parsers                                               │
│  · LLM        │    消息内容 / thinking 解析                               │
│    Litellm    │                                                          │
│    多Provider │                                                          │
│    + 自动回退  │                                                          │
│               │                                                          │
│  · Database   │                                                          │
│    PG/SQLite  │                                                          │
│    + 向量存储  │                                                          │
│    + 检查点    │                                                          │
│               │                                                          │
│  · Tools      │                                                          │
│    time · web │                                                          │
│    sql · vec  │                                                          │
│               │                                                          │
├───────────────┴─────────────────────────────────────────────────────────┤
│                        数据 & 工具层 (DATA & UTILS)                       │
│                                                                          │
│   Models (SQLAlchemy ORM)  — 数据库表定义                                 │
│   Schemas (Pydantic v2)    — 请求/响应校验                                │
│   CRUD                     — 异步数据操作                                 │
│   Utils                    — 消息转换、加密、异步写入                      │
│   Prompts                  — 系统提示词 MD 模板                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**依赖关系（严格单向，无循环）:**

```
REQUEST → API → AGENT RUNTIME → INFRA
                   │
                   └──→ OBSERVABILITY (只读)
                              │
                              ▼
                    DATA · UTILS · PROMPTS
```

**各层职责:**

| 层 | 职责 |
|----|------|
| **REQUEST** | 进程入口，启动 FastAPI，初始化所有服务 |
| **API** | HTTP 接口暴露、参数校验、SSE 流式推送 |
| **AGENT RUNTIME** | Agent 编译/缓存/调度，中间件注入，运行时上下文传递 |
| **INFRA** | LLM 网关、数据库、向量存储、工具执行 — 纯能力提供，不感知业务 |
| **OBSERVABILITY** | 从 checkpoint 重建执行轨迹，供 Trace UI 消费 — 只读，可独立替换 |
| **DATA & UTILS** | 数据建模、校验、持久化、共享工具函数 |

### 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 19 + TypeScript + Tailwind CSS + shadcn/ui + TanStack Query |
| **后端** | FastAPI + Uvicorn + SQLAlchemy 2.0 (异步) |
| **AI 编排** | LangChain v1 + LangGraph (create_agent, middleware, astream_events v3) |
| **存储（开发）** | SQLite + sqlite-vec（零依赖，嵌入式） |
| **存储（生产）** | PostgreSQL + pgvector + asyncpg |
| **可观测性** | 内置 TraceBuilder + LangSmith |

### 目录结构

```
backend/app/
├── main.py                    # FastAPI 入口 + lifespan
├── api/                       # HTTP 接口层
│   ├── errors.py              # 全局异常处理
│   └── v1/
│       ├── router.py          # 路由聚合
│       ├── dependencies.py    # 依赖注入 (get_db)
│       ├── chat.py            # 流式/非流式对话、历史
│       ├── chat_title.py      # 标题 CRUD + 自动生成
│       ├── chat_session.py    # 会话管理、统计、thinking 模式
│       ├── agent.py           # Agent 发现与配置
│       ├── model.py           # 模型 CRUD 与选择
│       ├── provider.py        # API Key 配置管理
│       ├── stream.py          # SSE 流式引擎
│       └── trace.py           # Trace Kanban 路由
├── agents/                    # Agent 运行时层
│   ├── __init__.py            # 自动发现 (pkgutil)
│   ├── registry.py            # 中央注册表 (DB + 原子快照)
│   ├── middleware/             # 共享中间件 (所有 Agent 复用)
│   │   ├── model/dynamic.py   # @wrap_model_call 动态模型选择
│   │   └── prompt/
│   │       ├── dynamic.py     # make_dynamic_prompt(agent_id)
│   │       └── service.py     # PromptService (可配置路径)
│   ├── chatbot/               # Agent: 通用对话机器人
│   │   ├── agent.py           # create_agent + register_factory
│   │   └── types.py           # ChatbotContext
│   ├── rag_agent/             # (未来) RAG 检索增强 Agent
│   ├── research/              # (未来) 深度研究 Agent
│   └── multi_agent/           # (未来) 多 Agent 协作 Supervisor
├── infra/                     # 基础设施层
│   ├── config.py              # pydantic-settings (单一配置源)
│   ├── database/              # 工厂模式，PG/SQLite 双后端
│   ├── llm/                   # Litellm 网关、模型缓存、extra_body
│   └── tools/                 # 基础工具 (time, web, sql, vectorstore)
├── models/                    # SQLAlchemy ORM 模型
├── schemas/                   # Pydantic v2 请求/响应 Schema
├── crud/                      # 异步数据库操作
├── observability/             # 只读追踪重建
│   ├── trace.py               # TraceBuilder
│   └── parsers.py             # 消息内容解析
├── utils/                     # 共享工具
│   ├── message_converters.py  # 统一消息转换 (单一来源)
│   ├── request_handler.py     # 请求→Agent 参数转换
│   ├── crypto.py              # AES-GCM 加密
│   └── async_writer.py        # 异步写入队列
└── prompts/                   # 系统提示词 MD 模板
    ├── chatbot.md
    ├── rag_agent.md
    └── research.md
```

### 添加新 Agent

```python
# 1. 创建 app/agents/my_agent/agent.py
from langchain.agents import create_agent
from app.agents.registry import register_factory
from app.agents.middleware.prompt.dynamic import make_dynamic_prompt
from app.agents.middleware.model.dynamic import dynamic_model

def _create_my_agent(checkpointer=None, store=None):
    prompt = make_dynamic_prompt("my_agent")  # 自动加载 prompts/my_agent.md
    return create_agent(
        model=default_llm,
        tools=[...],
        middleware=[prompt, dynamic_model],  # 复用共享中间件！
        checkpointer=checkpointer,
    )

register_factory("my_agent", _create_my_agent)

# 2. 创建 app/prompts/my_agent.md — 系统提示词
# 3. 完成！自动发现机制会识别 — 无需修改任何其他代码。
```

---

## 🔌 如何扩展

### 添加新智能体

```python
# 1. 在 backend/app/agents/ 中实现你的 LangGraph 智能体
from langgraph.graph import StateGraph, END

def create_my_agent(llm, checkpointer):
    workflow = StateGraph(AgentState)
    # ... 构建你的工作流
    return workflow.compile(checkpointer=checkpointer)

# 2. 在 backend/app/agents/__init__.py 中注册
# 3. 在 backend/app/prompt/ 中添加提示词模板
# 4. 如有需要，在 backend/app/tools/ 中添加工具
```

**完整指南** → [添加新智能体](docs/add-new-agent.zh.md)

### 添加新数据库后端

实现三个接口并在工厂中注册：
- `DatabaseInterface`
- `CheckpointInterface`
- `VectorstoreInterface`

**无需修改任何业务代码。**

---

## 📊 路线图

- [ ] **多模态支持** - 图像、语音、文件附件
- [ ] **智能体市场** - 发现、安装、分享社区智能体
- [ ] **团队协作** - 多用户支持，权限管理
- [ ] **高级评估** - 智能体基准测试和性能指标
- [ ] **自托管模型集成** - 深度集成 Ollama、Llama.cpp
- [ ] **智能体图可视化** - LangGraph 工作流可视化调试
- [ ] **完整测试套件** - 单元测试、集成测试、端到端测试

---

## 🤝 贡献指南

欢迎贡献！

1. Fork 本仓库
2. 创建功能分支（`git checkout -b feature/amazing-feature`）
3. 提交更改（`git commit -m 'feat: add amazing feature'`）
4. 推送到分支（`git push origin feature/amazing-feature`）
5. 提交 Pull Request

提交前请阅读 [开发指南](docs/development.zh.md)。

---

## 📄 许可证

本项目采用 [Apache 2.0 许可证](LICENSE)。

---

<p align="center">
  <strong>Made with ❤️ for the Agentic Future</strong>
</p>

<p align="center">
  <a href="https://github.com/realyinchen">GitHub</a> •
  <a href="https://github.com/realyinchen/AgentLab">AgentLab</a> •
  <a href="https://github.com/realyinchen/RAG">RAG 教程</a>
</p>

<p align="center">
  <img src="https://github.com/realyinchen/RAG/blob/main/imgs/wechat_qrcode.jpg?raw=true" alt="微信公众号二维码" width="150">
  <br>
  <em>关注我的微信公众号获取最新更新</em>
</p>