# 🧠 AgentHub - AI 智能体平台

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

一个提供现代 Web 界面的模块化 AI 智能体平台，用于构建、实验和部署 LangChain 和 LangGraph 智能体。采用 **FastAPI**（后端）和 **React**（前端）构建，具有清晰的关注点分离、数据库/业务层解耦架构，以及通过 SQLite + sqlite-vec 实现的**零依赖启动**。

这是 [AgentLab](https://github.com/realyinchen/AgentLab) 项目的 GUI 版本。

关注我的微信公众号获取最新推送：

![wechat_qrcode](https://github.com/realyinchen/RAG/blob/main/imgs/wechat_qrcode.jpg)

---

## 📑 目录

- [✨ 项目特色](#-项目特色)
- [🧩 适用场景](#-适用场景)
- [🏗️ 技术架构](#️-技术架构)
- [🗄️ 数据库抽象架构](#️-数据库抽象架构)
- [🚀 快速开始](#-快速开始)
- [🤖 可用智能体](#-可用智能体)
- [📡 API 参考](#-api-参考)
- [🐳 Docker 部署](#-docker-部署)
- [💻 开发规范](#-开发规范)
- [⚙️ 配置参考](#️-配置参考)
- [📈 性能优化](#-性能优化)
- [📦 分支说明](#-分支说明)
- [🚧 已知限制与路线图](#-已知限制与路线图)
- [📄 许可证](#-许可证)

---

## ✨ 项目特色

| 特性 | 描述 |
|------|------|
| 零依赖启动 | SQLite + sqlite-vec 嵌入式存储。无需 PostgreSQL、无需 Qdrant、无需 Docker。只需 `pip install` 即可运行。 |
| 数据库/业务层解耦 | 工厂模式 + 接口抽象。在 SQLite 和 PostgreSQL 之间切换**无需修改任何业务代码**。只需更改 `.env` 配置。 |
| LangChain/LangGraph 集成 | 构建、设计和连接多智能体推理工作流并进行可视化。 |
| 流式传输与事件驱动 | 实时 Token 流（SSE）和智能体执行事件可视化。 |
| 思考模式 | 在标准模式和思考模式之间切换，获得更深入的推理能力，思考过程和工具调用分开显示。 |
| 引用消息 | 引用任意历史消息继续对话，引用内容在刷新页面后依然保留。 |
| 多语言支持 | 内置国际化支持，提供中英文翻译。 |
| 深色/浅色主题 | 可自定义的主题支持，提供舒适的阅读体验。 |
| 图片缩放拖拽 | 点击 Markdown 中的任意图片可放大/缩小，支持拖拽查看。所有智能体通用。 |
| Token 用量展示 | 实时 Token 消耗可视化，纵向柱状图显示输入/输出/推理 Token。支持暗色模式和国际化。 |
| 智能体执行可视化 | 实时展示智能体运行的中间步骤：思考/推理过程、工具调用及其参数和结果。时间线侧边栏显示每次对话轮次的执行历史。 |
| 灵活的模型配置 | 在 Web 界面直接配置 LLM、VLM 和 Embedding 模型。在同一会话内自由切换智能体和模型，不会丢失会话历史。 |

![demo](https://github.com/realyinchen/AgentLab/blob/main/imgs/demo.gif)

---

## 🧩 适用场景

希望以交互式、可视化格式高效展示 LangChain 和 LangGraph 学习成果的学生和开发者，以及需要可插拔存储后端的生产级 AI 智能体平台的团队。

---

## 🏗️ 技术架构

### 整体架构

```
┌──────────────────────────────────────────────────────────┐
│                     前端 (React)                          │
│    Vite + React 19 + TypeScript + Tailwind + shadcn/ui   │
│              TanStack Query · SSE 客户端 · i18n           │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / SSE
                         ▼
┌──────────────────────────────────────────────────────────┐
│                   后端 (FastAPI)                           │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────────┐  │
│  │  智能体  │  │   API   │  │  工具   │  │   工具类   │  │
│  │(LangGraph│  │ (REST)  │  │(LangChn)│  │ (LLM,Msg)  │  │
│  └────┬────┘  └────┬────┘  └────┬────┘  └─────┬──────┘  │
│       │            │            │              │          │
│       └────────────┴────────────┴──────────────┘          │
│                         │                                  │
│              ┌──────────▼──────────┐                      │
│              │    工厂层           │                      │
│              │ DatabaseFactory     │                      │
│              │ VectorstoreFactory  │                      │
│              └──────────┬──────────┘                      │
│                         │                                  │
│              ┌──────────▼──────────┐                      │
│              │   接口层            │                      │
│              │ DatabaseInterface   │                      │
│              │ VectorstoreInterface│                      │
│              │ CheckpointInterface │                      │
│              └────┬──────────┬────┘                      │
│                   │          │                             │
│            ┌──────▼──┐  ┌───▼──────┐                     │
│            │SQLite   │  │PostgreSQL│                      │
│            │+sqlite- │  │+Qdrant  │                       │
│            │  vec    │  │         │                       │
│            └─────────┘  └─────────┘                       │
└──────────────────────────────────────────────────────────┘
```

### 后端技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| 运行时 | Python 3.12 | 语言运行时 |
| Web 框架 | FastAPI | 高性能异步 API，支持自动文档生成 |
| 智能体框架 | LangChain + LangGraph | LLM 编排和工作流图 |
| ORM | SQLAlchemy 2.0 (async) | 数据库抽象，异步会话管理 |
| 关系型数据库（默认） | SQLite + aiosqlite | 零依赖嵌入式数据库 |
| 关系型数据库（生产） | PostgreSQL + asyncpg | 生产级数据库，连接池支持 |
| 向量存储（默认） | sqlite-vec | 零依赖嵌入式向量搜索 |
| 向量存储（生产） | Qdrant | 生产级向量数据库，HNSW 索引 |
| 检查点 | LangGraph Savers (SQLite/PostgreSQL) | 智能体状态持久化，对话记忆 |
| ASGI 服务器 | Uvicorn | 生产就绪的异步服务器 |
| 限流 | slowapi | 基于 IP 的请求限流 |
| 缓存 | cachetools TTLCache | 模型、供应商、对话的内存缓存 |

### 前端技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| 构建工具 | Vite | 下一代打包器，即时 HMR |
| UI 框架 | React 19 | 组件化 UI |
| 语言 | TypeScript | 静态类型检查 |
| 样式 | Tailwind CSS | 实用优先的 CSS 框架 |
| UI 组件 | shadcn/ui | 可访问的、可自定义的组件库 |
| 状态管理 | TanStack Query | 服务端状态管理与缓存 |
| 图标 | Lucide React | 精美的图标库 |

### 项目结构

```
AgentHub/
├── frontend/                    # Vite + React + TypeScript + Tailwind CSS + shadcn/ui
│   ├── .env                     # 前端环境变量
│   ├── src/                     # React 组件和逻辑
│   │   ├── components/          # UI 组件（ui/、chat/、settings/ 等）
│   │   ├── hooks/               # 自定义 React Hooks
│   │   ├── lib/                 # 工具函数和 API 客户端
│   │   ├── locales/             # i18n 翻译文件（en、zh）
│   │   └── pages/               # 页面组件
│   ├── public/                  # 静态资源
│   ├── package.json             # 前端依赖
│   └── vite.config.ts           # Vite 构建配置
├── backend/                     # FastAPI + LangGraph 后端
│   ├── app/
│   │   ├── main.py              # FastAPI 应用入口 + 生命周期管理
│   │   ├── agents/              # 智能体实现
│   │   │   ├── chatbot.py       # 对话智能体（网络搜索 + 时间工具）
│   │   │   └── navigator.py     # 导航智能体（高德地图集成）
│   │   ├── api/v1/              # v1 API 端点
│   │   │   ├── agent.py         # 智能体 CRUD
│   │   │   ├── chat.py          # 聊天流、历史记录、对话管理
│   │   │   ├── model.py         # 模型管理
│   │   │   └── provider.py      # 供应商管理
│   │   ├── core/                # 核心配置
│   │   │   ├── config.py        # 配置项（Pydantic BaseSettings）
│   │   │   ├── model_manager.py # LLM/VLM/Embedding 模型管理器
│   │   │   ├── cache.py         # TTL 缓存配置
│   │   │   └── rate_limiter.py  # 限流配置
│   │   ├── crud/                # 数据库 CRUD 操作
│   │   ├── database/            # 数据库抽象层
│   │   │   ├── interfaces.py    # 抽象接口定义
│   │   │   ├── factory.py       # 工厂实现（单例实例）
│   │   │   └── backends/        # 后端实现
│   │   │       ├── postgres/    # PostgreSQL + Qdrant 后端
│   │   │       └── sqlite/      # SQLite + sqlite-vec 后端
│   │   ├── models/              # SQLAlchemy ORM 模型
│   │   ├── schemas/             # Pydantic 请求/响应模型
│   │   ├── tools/               # LangChain 工具集
│   │   ├── prompt/              # 集中管理的提示词模板
│   │   └── utils/               # 工具函数（LLM、消息、加密、智能体辅助）
│   ├── scripts/                 # 数据库初始化脚本
│   ├── data/                    # SQLite 数据库文件（自动创建）
│   ├── .env.example             # 环境变量模板
│   ├── requirements.txt         # Python 依赖
│   └── run_backend.py           # 后端启动脚本
├── docker-compose.yml           # 全栈部署（带 profiles）
└── README.zh.md                 # 本文件
```

---

## 🗄️ 数据库抽象架构

AgentHub 通过清晰的抽象层同时支持 **SQLite**（零依赖，推荐快速开始）和 **PostgreSQL + Qdrant**（生产级）后端。切换后端**无需修改任何业务代码** — 只需更改配置。

### 为什么这很重要

数据库/业务层解耦意味着：
- **开发者**可以使用 SQLite 立即开始编码 — 无需 Docker、无需数据库设置
- **团队**可以通过 PostgreSQL + Qdrant 部署到生产环境 — 只需更改 `.env`
- **贡献者**可以添加新的后端而无需触碰任何业务逻辑

### 核心设计原则

1. **业务逻辑零感知** — Agents、API、Tools 层代码完全不感知底层数据库类型。通过工厂模式和接口抽象，业务层只依赖接口不依赖具体实现。
2. **工厂层一劳永逸** — `factory.py` 只负责根据配置创建实例。添加新后端只需要注册到工厂。表结构变更只影响具体后端实现，不改动工厂。
3. **配置驱动切换** — 通过 `.env` 配置项切换后端：`DATABASE_TYPE` 和 `VECTORSTORE_TYPE` 两个独立配置。同一代码库支持多种部署场景。

### 三层架构

```
业务层 (Business Layer)
  Agent | API | Tools | Utils
         |         |         |
         v         v         v
工厂层 (Factory Layer)
  DatabaseFactory + VectorstoreFactory
  - 根据配置动态创建后端实例
  - 注入嵌入函数到向量存储
         |         |         |
         v         v         v
接口层 (Interface Layer)
  DatabaseInterface + CheckpointInterface
  VectorstoreInterface
         |         |         |
         v         v         v
后端实现层 (Backend Implementations)
  PostgreSQL          |  SQLite
  PostgresDatabase    |  SQLiteDatabase
  PostgresCheckpointer|  SqliteCheckpointer
  QdrantVectorstore   |  SqliteVecVectorstore
```

### 后端对比

| 组件 | SQLite 后端（默认） | PostgreSQL 后端（生产） |
|------|---------------------|------------------------|
| 数据库 | SQLAlchemy + aiosqlite（StaticPool 单连接模式） | SQLAlchemy + asyncpg（连接池，高并发） |
| 检查点 | AsyncSqliteSaver（LangGraph 官方支持） | AsyncPostgresSaver（LangGraph 官方支持） |
| 向量存储 | sqlite-vec 扩展（零依赖，嵌入式） | qdrant-client（生产级向量数据库） |
| 外部依赖 | **无** | PostgreSQL 服务器 + Qdrant 服务器 |
| 并发能力 | 单写入者（适合中小型应用） | 完整并发读写（100+ 用户） |
| 初始化 | 自动创建 `data/` 目录和表 | 需要 `init_database.py` + Docker 服务 |

### 评分语义统一

| 后端 | 原始输出 | 含义 | 统一后输出 | 转换公式 |
|------|----------|------|-----------|----------|
| Qdrant | score (0~1) | 余弦相似度，越大越相似 | score (0~1) | 无需转换 |
| sqlite-vec | distance (0~2) | 余弦距离，越小越相似 | score (0~1) | score = 1.0 - distance |

**约定**: `VectorstoreInterface.search_with_embedding()` 返回的 `score` 字段**必须**是余弦相似度（0~1，越大越相似）。

### ORM 模型兼容性

| PostgreSQL 类型 | SQLAlchemy 通用类型 | SQLite 存储形式 |
|----------------|-------------------|----------------|
| `postgresql.UUID(as_uuid=True)` | `sqlalchemy.Uuid` | TEXT（字符串形式） |
| `postgresql.JSONB` | `sqlalchemy.JSON` | TEXT |

关于 `server_default`，SQLite 不支持 `server_default=func.now()` 在 UPDATE 时自动触发，需依赖 SQLAlchemy 的 Python 侧回调（`default=utc_now`，`onupdate=utc_now`）。

### 添加新后端

1. 实现 `DatabaseInterface` 接口
2. 实现 `CheckpointInterface` 接口
3. 实现 `VectorstoreInterface` 接口
4. 在 `factory.py` 的 `_DB_BACKENDS`、`_CP_BACKENDS`、`_VS_BACKENDS` 中注册
5. 更新 `config.py` 添加新的配置项（如需要）
6. 更新 `.env.example` 和 `README.zh.md` 文档

**无需修改**: 任何业务层代码（agents、api、tools、utils）

### 数据库文件结构

```
backend/app/database/
├── base.py                  # 接口定义（从 interfaces.py 重新导出）
├── interfaces.py            # 抽象接口定义
├── factory.py               # 工厂实现（单例缓存）
├── __init__.py              # 导出工厂函数
└── backends/
    ├── __init__.py
    ├── postgres/
    │   ├── __init__.py
    │   ├── db.py            # PostgresDatabase
    │   ├── checkpointer.py  # PostgresCheckpointer
    │   └── vectorstore.py   # QdrantVectorstore
    └── sqlite/
        ├── __init__.py
        ├── db.py            # SQLiteDatabase
        ├── checkpointer.py  # SqliteCheckpointer
        └── vectorstore.py   # SqliteVecVectorstore
```

### 已知权衡

| 决策 | 收益 | 代价 |
|------|------|------|
| 工厂模式 + 接口抽象 | 业务层零感知，易扩展 | 间接调用开销可忽略不计（<1% 的 API 响应时间；瓶颈始终在后端实现本身） |
| 嵌入函数依赖注入 | Vectorstore 不依赖 ModelManager | 增加一点复杂度 |
| 统一评分语义 | 业务层无需处理两种评分 | sqlite-vec 实现多一步转换 |
| Docker Profiles | 一个 compose 文件支持两种模式 | 学习成本（需要知道 `--profile`） |

### 📊 性能分析

> **核心洞察**：工厂模式 + 接口抽象层仅在启动时运行（创建单例实例）。运行时，业务代码直接调用接口方法 — Python 的鸭子类型 + 依赖注入几乎不增加任何开销（<1% 的 API 总响应时间）。真正的性能差异来自**后端实现本身**，而非抽象层。

#### 关系型数据库：SQLite vs PostgreSQL

| 方面 | SQLite | PostgreSQL |
|------|--------|------------|
| **低并发读** | ✅ 更快 — 无网络开销，直接文件 I/O。小数据集上的简单点查询可比 PG 快 2-10 倍。 | ❌ 较慢 — 网络往返 + 进程开销增加延迟。 |
| **高并发写** | ❌ 较差 — 单写入者（即使开启 WAL 模式）。并发的检查点写入会串行化并拖慢吞吐。 | ✅ 优秀 — MVCC 允许并发读写互不阻塞。可处理数百个同时连接。 |
| **复杂查询** | ❌ 有限 — 无高级查询优化器，JSON 查询能力有限。 | ✅ 强大 — 高级查询优化器、JSONB 索引、部分索引、CTE。 |
| **扩展性** | 仅限单机。适合 <200 QPS 且写入适中的场景。 | 通过连接池、只读副本、分区实现水平扩展。 |
| **最佳场景** | 开发、测试、低流量单实例部署。 | 生产环境、多用户、高并发、强一致性需求。 |

#### 向量存储：sqlite-vec vs Qdrant

| 方面 | sqlite-vec | Qdrant |
|------|-----------|--------|
| **小规模向量（<100万）** | ✅ 足够 — 低延迟，零部署开销。适合原型开发。 | 可用但需要额外部署服务。 |
| **中大规模向量（>100万）** | ❌ 有限 — 无 HNSW 优化，大规模时性能显著下降。 | ✅ 专用构建（Rust 实现）— HNSW 索引即使在大规模下也能实现 20-50ms 搜索。 |
| **过滤向量搜索** | ❌ 基础 — 元数据过滤 + 相似度搜索能力有限。 | ✅ 优秀 — 丰富的 payload 过滤 + 向量搜索，量化压缩节省内存。 |
| **部署** | 嵌入式 — 与应用共享进程，零配置。 | 独立服务 — 需要 Docker/部署，但提供 API 和仪表盘。 |
| **最佳场景** | 开发、小型 RAG 原型、低流量场景。 | 生产 RAG、中大规模向量集合、带过滤的实时检索。 |

#### 场景推荐

| 场景 | 推荐方案 | 原因 |
|------|----------|------|
| 本地开发 / 测试 | **SQLite + sqlite-vec** | 零配置，最快迭代速度。 |
| 演示 / 个人项目 | **SQLite + sqlite-vec** | 低流量，资源需求少，部署简单。 |
| 生产环境（<100 并发用户） | **SQLite + sqlite-vec**（写密集可换 PG） | SQLite 能很好地处理中等负载；如果检查点写入成为瓶颈再切换 PG。 |
| 生产环境（100+ 并发用户） | **PostgreSQL + Qdrant** | MVCC 支持并发写入，HNSW 支持大规模向量搜索。 |
| 重度 RAG 生产环境 | **PostgreSQL + Qdrant** | Qdrant 的 payload 过滤和量化压缩对生产 RAG 至关重要。 |

---

## 🚀 快速开始

### 推荐方式：SQLite 模式（零依赖）

最快速的入门方式 — 无需 PostgreSQL、无需 Qdrant、无需 Docker。

**前置要求**
1. 安装 [VS Code](https://code.visualstudio.com/Download) 和 [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/)
2. 安装 [Node.js 18+](https://nodejs.org/) 用于前端开发

**安装步骤**

1. **创建并激活虚拟环境**
   ```bash
   conda create -n agenthub python=3.12
   conda activate agenthub
   ```

2. **克隆并进入项目目录**
   ```bash
   git clone https://github.com/realyinchen/AgentHub.git
   cd AgentHub
   ```

3. **配置环境变量**
   ```bash
   cd backend
   cp .env.example .env
   ```
   编辑 `.env` 文件 — 默认配置已设置为 SQLite 模式。只需填入你需要的三方 API 密钥（Tavily、高德地图等）。

4. **安装后端依赖**
   ```bash
   pip install -r requirements.txt
   ```

5. **初始化数据库**
   ```bash
   python scripts/init_database.py
   ```

6. **启动后端服务器**
   ```bash
   python run_backend.py
   ```

7. **在新终端中，启动前端开发服务器**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

8. **配置供应商和模型（重要！）**
   - 打开 `http://localhost:5173`
   - 点击右上角设置图标
   - 先配置供应商（输入 API 密钥）
   - 然后为每个已配置的供应商添加模型

9. **访问应用**
   - 前端：`http://localhost:5173`
   - 后端 API 文档：`http://localhost:8080/docs`

> SQLite 模式会自动在 `backend/data/` 目录下创建数据库文件。无需任何外部服务！

### 生产环境：PostgreSQL + Qdrant 模式

适用于需要高并发和完整向量搜索功能的生产部署。

**额外前置要求**：Docker（用于运行 PostgreSQL 和 Qdrant）

**额外步骤**

1. **启动 PostgreSQL 和 Qdrant**
   ```bash
   # 启动 PostgreSQL
   docker run -d --name agenthub-postgres \
     -e POSTGRES_USER=langchain \
     -e POSTGRES_PASSWORD=langgraph \
     -e POSTGRES_DB=agentdb \
     -p 5432:5432 \
     postgres:latest

   # 启动 Qdrant
   docker run -d --name agenthub-qdrant \
     -p 6333:6333 \
     -p 6334:6334 \
     qdrant/qdrant:latest
   ```

2. **编辑 `backend/.env` 切换后端**
   ```env
   DATABASE_TYPE=postgres
   VECTORSTORE_TYPE=qdrant
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_USER=langchain
   POSTGRES_PASSWORD=langgraph
   POSTGRES_DB=agentdb
   QDRANT_HOST=localhost
   QDRANT_PORT=6333
   ```

3. **初始化数据库**
   ```bash
   python scripts/init_database.py
   ```

然后按照 SQLite 模式的步骤 6-9 继续操作。

---

## 🤖 可用智能体

### chatbot — 对话智能体

具有工具调用能力的通用对话智能体。

| 工具 | 描述 |
|------|------|
| `get_current_time` | 获取任意时区的当前时间 |
| `web_search` | 搜索网络获取实时信息（通过 Tavily） |

**特性**：实时查询（天气、新闻、当前时间等）、流式响应、思考模式支持。

### navigator — 导航智能体

集成高德地图 API 的导航和位置感知智能体。

| 工具 | 描述 |
|------|------|
| `get_current_time` | 获取任意时区的当前时间 |
| `amap_geocode` | 地址转经纬度坐标（地理编码） |
| `amap_place_search` | 关键词搜索 POI（餐厅、酒店等） |
| `amap_place_around` | 周边搜索 POI |
| `amap_driving_route` | 驾车路线规划，包含距离、时间和导航链接 |
| `amap_route_preview` | 生成包含途经点的完整路线预览链接 |
| `amap_weather` | 查询城市天气信息 |

**特性**：时间冲突检测、行程规划、天气感知建议、**并行工具执行** — 多个工具同时执行，规划速度更快。

---

## 📡 API 参考

所有 API 端点以 `/api/v1` 为前缀。启动后端后，可在 `http://localhost:8080/docs`（Swagger UI）查看交互式文档。

### 智能体 API

| 方法 | 端点 | 描述 |
|------|------|------|
| `POST` | `/agents/` | 创建新智能体 |
| `GET` | `/agents/` | 列出智能体（支持分页和仅活跃筛选） |
| `GET` | `/agents/{agent_id}` | 获取智能体详情 |
| `PATCH` | `/agents/{agent_id}` | 更新智能体（部分更新） |
| `DELETE` | `/agents/{agent_id}` | 软删除智能体（设置 `is_active = False`） |

**查询参数（列出智能体）**：

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `active_only` | bool | `true` | 仅显示活跃的智能体 |
| `limit` | int | 20 | 最大返回数量（1-100） |
| `offset` | int | 0 | 跳过的结果数量 |

### 聊天 API

| 方法 | 端点 | 描述 |
|------|------|------|
| `POST` | `/chat/stream` | 通过 SSE 流式返回智能体响应 |
| `POST` | `/chat/invoke` | 调用智能体并获取完整响应（非流式） |
| `GET` | `/chat/history/{agent_id}/{thread_id}` | 获取聊天历史和消息序列 |
| `GET` | `/chat/conversations` | 列出对话（分页） |
| `POST` | `/chat/conversations` | 创建新对话 |
| `DELETE` | `/chat/conversations/{thread_id}` | 软删除对话 |
| `GET` | `/chat/title/{thread_id}` | 获取对话标题 |
| `POST` | `/chat/title` | 更新对话标题 |
| `POST` | `/chat/title/generate` | 使用 LLM 自动生成标题 |
| `GET` | `/chat/thinking-mode` | 检查思考模式是否可用 |
| `GET` | `/chat/models` | 获取配置中的可用模型 |

**SSE 流请求体**（`UserInput`）：
```json
{
  "agent_id": "chatbot",
  "thread_id": "对话-uuid",
  "message": "今天天气怎么样？",
  "model_id": "可选-模型-id",
  "thinking_mode": false,
  "quote_message_id": "可选-引用消息-id"
}
```

**SSE 流格式**（`/chat/stream`）：
```
data: {"type": "token", "content": "你好"}
data: {"type": "token", "content": " 世界"}
data: [DONE]
```

**对话列表**：响应包含 `X-Total-Count` 头用于分页。

### 模型 API

| 方法 | 端点 | 描述 |
|------|------|------|
| `GET` | `/models/` | 获取可用模型（已配置供应商 API 密钥的） |
| `GET` | `/models/all` | 获取所有模型（配置页面使用） |
| `GET` | `/models/providers` | 获取可用的模型供应商 |
| `POST` | `/models/` | 创建新模型 |
| `POST` | `/models/update` | 更新模型配置 |
| `POST` | `/models/delete` | 删除模型 |
| `POST` | `/models/set-default` | 设置某类型的默认模型（llm/vlm/embedding） |
| `POST` | `/models/refresh` | 手动刷新模型缓存 |

**模型响应**包含：
- `models` — 模型信息对象列表
- `default_llm` — 默认 LLM 模型 ID
- `default_vlm` — 默认 VLM 模型 ID
- `default_embedding` — 默认 Embedding 模型 ID

> **注意**：模型更新/删除/设置默认使用 `POST` 并在请求体中传递模型 ID（而非 URL 路径），以避免模型 ID 中 `/` 字符的 URL 编码问题（如 `zai/glm-5`）。

### 供应商 API

| 方法 | 端点 | 描述 |
|------|------|------|
| `GET` | `/providers/` | 列出所有供应商 |
| `POST` | `/providers/` | 创建新供应商 |
| `POST` | `/providers/update` | 更新供应商配置 |
| `POST` | `/providers/delete` | 删除供应商 |
| `POST` | `/providers/validate` | 验证供应商 API 密钥 |

> **注意**：供应商更新/删除使用 `POST` 并在请求体中传递供应商 ID，原因同模型 API。

### 通用模式

- **分页**：`limit`（1-100）和 `offset` 参数；响应中 `X-Total-Count` 头
- **软删除**：实体被标记为非活跃而非从数据库中移除
- **错误格式**：`{"detail": "错误信息"}`，附带相应的 HTTP 状态码

---

## 🐳 Docker 部署

同一个 Docker 镜像同时支持 SQLite 和 PostgreSQL 后端。所有配置通过 `.env` 文件管理。

### 快速开始 — SQLite 模式（推荐）

零外部依赖，使用嵌入式 SQLite 数据库：

```bash
# 1. 复制配置模板
cd backend && cp .env.example .env
cd ../frontend && cp .env.example .env
cd ..

# 2. 编辑 backend/.env 添加三方 API 密钥（Tavily、高德地图等）
#    SQLite 模式下默认配置即可 - 只需填入你需要的 API 密钥

# 3. 启动
docker-compose up -d
```

打开 `http://localhost:5173`，在设置中配置你的 LLM API 密钥。

> SQLite 数据库存储在 Docker 卷（`agenthub-backend-data`）中。无需 PostgreSQL 或 Qdrant。

### 生产环境 — PostgreSQL 模式

使用 PostgreSQL + Qdrant 的生产部署：

1. 编辑 `backend/.env`：
   - 设置 `DATABASE_TYPE=postgres` 和 `VECTORSTORE_TYPE=qdrant`
   - 设置 `POSTGRES_HOST=postgres`（Docker 服务名，不是 localhost）
   - 设置 `QDRANT_HOST=qdrant`（Docker 服务名，不是 localhost）

2. 使用 postgres profile 启动：
   ```bash
   docker-compose --profile postgres up -d
   ```

### 访问地址

| 服务 | URL |
|------|-----|
| 前端 | `http://localhost:5173` |
| 后端 API 文档 | `http://localhost:8080/docs` |

### 数据持久化

| 模式 | 卷 | 内容 |
|------|-----|------|
| SQLite | `agenthub-backend-data` | `data/` 中的数据库文件 |
| PostgreSQL | `agenthub-postgres-data` | PostgreSQL 数据 |
| Qdrant | `agenthub-qdrant-data` | 向量存储数据 |

### 常用命令

```bash
# 查看日志
docker-compose logs -f

# 停止服务（SQLite 模式）
docker-compose down

# 停止服务（PostgreSQL 模式）
docker-compose --profile postgres down

# 代码变更后重新构建镜像
docker-compose build --no-cache
```

### 独立部署

各模块也可以单独部署：

- **仅后端**：参见 `backend/docker-compose.yml`
- **仅前端**：参见 `frontend/docker-compose.yml`

### Docker 文件结构

```
AgentHub/
├── docker-compose.yml       # 全栈部署（带 profiles）
├── backend/
│   ├── docker-compose.yml   # 后端独立部署
│   ├── Dockerfile           # 后端容器（支持 SQLite 和 PG）
│   └── .env.example         # 环境变量模板
└── frontend/
    ├── docker-compose.yml   # 前端独立部署
    ├── Dockerfile           # 前端容器（多阶段构建）
    ├── nginx.conf           # Nginx 配置，含 API 代理
    └── .env.example         # 环境变量模板
```

---

## 💻 开发规范

### API 设计约定

- **仅使用 GET、POST、DELETE 端点**（大部分情况不使用 PATCH/PUT）
- 模型和供应商的更新/删除操作使用 `POST` 并在请求体中传递 ID，以避免模型 ID 中 `/` 字符的 URL 编码问题（如 `zai/glm-5`）
- 例外：智能体更新使用 `PATCH /agents/{agent_id}`（智能体 ID 不包含 `/`）

### LLM API 使用

**推荐使用（异步 API）**：
- 在 FastAPI 异步端点中使用 `aget_llm()`、`aembedding_model()`
- 使用 `streaming_completion()` 进行 LLM 调用，自动追踪 Token

**仅用于兼容（同步包装器）**：
- `get_llm()`、`embedding_model()` — 仅用于旧代码或非异步上下文
- 在异步上下文中调用会产生额外开销（会触发警告日志）

### 数据库操作

- **成功时自动提交**：所有业务代码（API、Services、CRUD）**不得**手动调用 `session.commit()` 或 `session.rollback()`
- **统一处理**：`db.session()` 上下文管理器自动处理提交/回滚/关闭
- **标准模式**：
  ```python
  async with db.session() as session:
      # 业务逻辑：仅 add/update/delete，零事务操作
      await crud.do_something(session, ...)
  # 上下文退出时自动提交，异常时自动回滚，始终关闭
  ```

### Token 追踪

通过 `backend/app/utils/llm.py` 中的 `streaming_completion()` 自动追踪 Token 使用量。新增智能体只需使用此函数并返回 `result.raw_response` 即可自动获得 Token 追踪功能，无需额外代码。参考 `chatbot.py` 或 `navigator.py` 示例。

### 添加新智能体

1. 在 `backend/app/agents/` 中创建智能体文件（如 `my_agent.py`）
2. 定义带工具的 LangGraph 工作流
3. 在 `backend/app/agents/__init__.py` 中注册
4. 在 `backend/app/prompt/` 中添加提示词模板
5. 在 `backend/app/tools/` 中添加新工具（如有）
6. 通过 `init_database.py` 或 API 初始化智能体数据

### 添加新数据库后端

1. 在 `backends/<name>/db.py` 中实现 `DatabaseInterface`
2. 在 `backends/<name>/checkpointer.py` 中实现 `CheckpointInterface`
3. 在 `backends/<name>/vectorstore.py` 中实现 `VectorstoreInterface`
4. 在 `factory.py` 中注册（`_DB_BACKENDS`、`_CP_BACKENDS`、`_VS_BACKENDS`）
5. 更新 `config.py` 添加新的配置项（如需要）
6. 更新 `.env.example` 和 `README.zh.md`

**任何业务层代码均无需修改**（agents、api、tools、utils）。

### 生产环境单例规则

| 组件 | 是否单例？ | 原因 |
|------|-----------|------|
| 数据库引擎 | 是 | 全局连接池复用 |
| 数据库会话 | **否** | 请求级隔离，有事务状态，非线程安全 |
| Qdrant 客户端 | 是 | 无事务，线程安全，连接复用 |

---

## ⚙️ 配置参考

### 后端环境变量（`backend/.env`）

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `DATABASE_TYPE` | `sqlite` | 数据库后端：`sqlite` 或 `postgres` |
| `VECTORSTORE_TYPE` | `sqlite_vec` | 向量存储后端：`sqlite_vec` 或 `qdrant` |
| `API_V1_STR` | `/api/v1` | API 路由前缀 |
| `POSTGRES_HOST` | `localhost` | PostgreSQL 主机（仅 postgres 模式） |
| `POSTGRES_PORT` | `5432` | PostgreSQL 端口 |
| `POSTGRES_USER` | `langchain` | PostgreSQL 用户名 |
| `POSTGRES_PASSWORD` | `langgraph` | PostgreSQL 密码 |
| `POSTGRES_DB` | `agentdb` | PostgreSQL 数据库名 |
| `QDRANT_HOST` | `localhost` | Qdrant 主机（仅 qdrant 模式） |
| `QDRANT_PORT` | `6333` | Qdrant 端口 |
| `QDRANT_COLLECTION` | `agenthub` | Qdrant 集合名 |
| `SQLITE_DB_PATH` | `data/agenthub.db` | SQLite 数据库文件路径 |
| `SQLITE_VEC_PATH` | `data/agenthub_vec.db` | sqlite-vec 数据库文件路径 |
| `TAVILY_API_KEY` | — | Tavily API 密钥（用于网络搜索工具） |
| `AMAP_API_KEY` | — | 高德地图 API 密钥（用于导航智能体） |
| `LANGSMITH_API_KEY` | — | LangSmith API 密钥（用于追踪，可选） |
| `LANGSMITH_PROJECT` | — | LangSmith 项目名（可选） |
| `LLM_DEFAULT_MODEL` | — | 默认 LLM 模型标识符 |

### 前端环境变量（`frontend/.env`）

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `VITE_API_BASE_URL` | `http://localhost:8080` | 后端 API 基础 URL |

### Docker 专用变量

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `NGINX_BACKEND_HOST` | `localhost` | Nginx 代理后端主机（前端 Docker） |
| `NGINX_BACKEND_PORT` | `8080` | Nginx 代理后端端口 |
| `FRONTEND_PORT` | `5173` | 前端暴露端口 |

---

## 📈 性能优化

### 数据库优化
- **连接池**：20 个基础连接加 30 个溢出连接（支持 100+ 并发用户）
- **索引优化**：复合索引、部分索引和覆盖索引
- **查询性能**：对话列表查询速度提升 5-10 倍

### API 优化
- **限流**：默认每 IP 100 请求/分钟（防止滥用）
- **缓存**：内存 TTL 缓存 - 模型（5分钟）、供应商（5分钟）、对话（1分钟）、向量搜索（10分钟）— 80%+ 命中率
- **敏感数据**：日志中 API Key 脱敏处理

### 前端优化
- **错误边界**：防止白屏崩溃
- **React 性能**：useMemo 优化和防抖状态更新

### 向量存储优化
- **Qdrant**：HNSW 索引配置（m=16, ef=200）实现 20-50ms 搜索
- **批量搜索**：支持一次请求多个向量查询

---

## 📦 分支说明

| 分支 | 描述 |
|------|------|
| `main`（默认） | 稳定版本分支，包含经过测试的成熟功能 |
| `dev` | 开发版本分支，包含最新的功能和改进 |

```bash
# 克隆 main 分支（稳定版）
git clone -b main https://github.com/realyinchen/AgentHub.git

# 克隆 dev 分支（最新版）
git clone -b dev https://github.com/realyinchen/AgentHub.git
```

---

## 🚧 已知限制与路线图

### 已知限制
1. **测试**：目前未实现单元/集成测试
2. **向量数据库**：向量存储功能（Qdrant 和 sqlite-vec 后端）尚未进行充分测试。`vectorstore_search` 工具和文档入库功能需要进一步验证

### 路线图
- 额外的智能体类型（SQL 智能体、代码智能体、多智能体工作流）
- 后端和前端的全面测试套件
- React UI 中的智能体图可视化
- 对话搜索和过滤
- 向量存储文档上传 UI
- 智能体性能指标仪表板

---

## 📄 许可证

本项目采用 [LICENSE](LICENSE) 文件中规定的条款进行许可。