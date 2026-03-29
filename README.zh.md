# 🧠 AgentHub - AI 智能体平台

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

一个提供现代 Web 界面的模块化 AI 智能体集合框架，用于实验 LangChain 和 LangGraph 智能体。采用 FastAPI（后端）和 React（前端）构建，具有清晰的关注点分离和现代化开发实践。

这是 [AgentLab](https://github.com/realyinchen/AgentLab) 项目的 GUI 版本。

灵感来源：[agent-service-toolkit](https://github.com/JoshuaC215/agent-service-toolkit)

关注我的微信公众号获取最新推送：

![wechat_qrcode](https://github.com/realyinchen/RAG/blob/main/imgs/wechat_qrcode.jpg)

## 🚀 项目特性

✅ **FastAPI 后端** — 稳健的 RESTful API 层，用于智能体编排和异步任务管理。  
✅ **现代 React 前端** — 交互式 Web 界面，使用 Vite + React + TypeScript + Tailwind CSS + shadcn/ui 构建，提供卓越的用户体验。  
✅ **LangChain/LangGraph 集成** — 轻松构建、设计和连接多智能体推理工作流并进行可视化。  
✅ **流式传输和事件驱动** — 实时 token 流和智能体执行事件可视化。  
✅ **思考模式** — 在标准模式和思考模式之间切换，获得更深入的推理能力，思考过程和工具调用分开显示。  
✅ **引用消息** — 引用任意历史消息继续对话，引用内容在刷新页面后依然保留。  
✅ **多语言支持** — 内置国际化支持，提供中英文翻译。  
✅ **深色/浅色主题** — 可自定义的主题支持，提供舒适的阅读体验。  
✅ **图片缩放拖拽** — 点击 Markdown 中的任意图片可放大/缩小，支持拖拽查看。通用功能，所有智能体可用。  
✅ **聊天缩略图** — VSCode 风格的缩略图显示迷你对话文本，支持悬浮预览、点击跳转和拖拽滚动导航。已修复透明块点击跳转、预览块关闭行为和底部位置预览显示问题。  

## 🧩 适用场景：

希望以交互式、可视化格式高效展示 LangChain 和 LangGraph 学习成果的学生和开发者。

## 🏗️ 架构

```
AgentHub/
├── frontend/               # Vite + React + TypeScript + Tailwind CSS + shadcn/ui
│   ├── .env                # 前端环境变量
│   ├── src/                # React 组件和逻辑
│   ├── public/             # 静态资源
│   ├── package.json        # 前端依赖
│   └── vite.config.ts      # Vite 构建配置
├── backend/                # FastAPI + LangGraph 后端
│   ├── app/                # 主应用程序代码
│   │   ├── main.py         # FastAPI 应用入口点
│   │   ├── agents/         # 智能体实现（chatbot, rag-agent）
│   │   ├── api/            # API 路由
│   │   ├── core/           # 核心配置
│   │   ├── database/       # 数据库管理器和检查点
│   │   ├── tools/          # LangChain 工具集合
│   │   ├── prompt/         # 集中管理的提示词模板
│   │   └── ...             # 其他模块
│   ├── scripts/            # 数据库初始化脚本
│   │   └── init_database.py # 初始化 PostgreSQL 和 Qdrant
│   ├── .env                # 环境变量
│   ├── .env.example        # 环境变量示例
│   ├── requirements.txt    # Python 依赖
│   └── run_backend.py      # 后端启动脚本
└── README.md               # 此文件
```

## 🛠️ 技术栈

### 后端
- **Python 3.12** - 运行时环境
- **FastAPI** - 高性能 Web 框架，支持自动 API 文档生成
- **LangChain** - LLM 编排框架
- **LangGraph** - 复杂推理的智能体工作流图
- **PostgreSQL** - 主数据库，支持异步/同步操作
- **Qdrant** - 用于 RAG 功能的向量存储
- **Uvicorn** - 用于生产部署的 ASGI 服务器

### 前端
- **Vite** - 下一代构建工具，支持即时服务器启动
- **React 19** - 基于组件的 UI 库
- **TypeScript** - 代码安全的静态类型检查
- **Tailwind CSS** - 实用优先的 CSS 框架
- **shadcn/ui** - 可访问的、可自定义的 UI 组件
- **TanStack Query** - 数据获取和状态管理
- **Lucide React** - 精美的图标库

## 📦 分支说明

本项目有两个分支：

- **main**（默认）：稳定版本分支，包含经过测试的成熟功能。如果你想体验稳定的功能，请克隆此分支。
- **dev**：开发版本分支，包含最新的功能和改进。如果你想体验最新的特性，请克隆此分支。

```bash
# 克隆 main 分支（稳定版）
git clone -b main https://github.com/realyinchen/AgentHub.git

# 克隆 dev 分支（最新版）
git clone -b dev https://github.com/realyinchen/AgentHub.git
```

## 🚀 快速开始

### 前置要求
1. 安装 [VS Code](https://code.visualstudio.com/Download) 和 [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/)
2. 安装 [Node.js 18+](https://nodejs.org/) 用于前端开发
3. **启动 PostgreSQL 和 Qdrant**（本地开发和 Docker 部署都需要）：
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

### 设置说明

1. **创建虚拟环境**
   ```bash
   conda create -n agenthub python=3.12
   ```

2. **激活虚拟环境**
   ```bash
   conda activate agenthub
   ```

3. **克隆并进入项目目录**
   ```bash
   git clone https://github.com/realyinchen/AgentHub.git
   cd AgentHub
   ```

4. **配置环境变量**
   ```bash
   cd backend
   cp .env.example .env
   ```
   使用您的 API 密钥和配置设置编辑 `.env` 文件。

5. **安装后端依赖**
   ```bash
   pip install -r requirements.txt
   ```

6. **初始化数据库**
   ```bash
   python scripts/init_database.py
   ```

7. **启动后端服务器**
   ```bash
   python run_backend.py
   ```

8. **在新终端中，导航到前端并启动开发服务器**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

9. **访问应用程序**
   - 前端：在浏览器中打开 `http://localhost:5173`
   - 后端 API：访问 `http://localhost:8080/docs` 查看 Swagger UI

## 🤖 可用智能体

- **chatbot** — 带工具的对话智能体：
  - `get_current_time` — 获取任意时区的当前时间
  - `web_search` — 搜索网络获取实时信息（通过 Tavily）
  - 支持实时查询（天气、新闻、当前时间等）
- **rag-agent** — 高级 RAG 智能体，包含：
  - 问题路由（向量存储 / 网络搜索 / 直接回答）
  - Qdrant 向量存储检索
  - 文档相关性评分
  - 幻觉检测评分
  - 回答质量评分
  - Tavily 网络搜索回退
  - 最终答案格式化的报告节点
- **navigator** — 导航智能体，集成高德地图 API：
  - `get_current_time` — 获取任意时区的当前时间（必须首先调用）
  - `amap_geocode` — 地址转经纬度坐标（地理编码）
  - `amap_place_search` — 关键词搜索 POI（餐厅、酒店等）
  - `amap_place_around` — 周边搜索 POI
  - `amap_driving_route` — 驾车路线规划，包含距离、时间和导航链接
  - `amap_route_preview` — 生成包含途经点的完整路线预览链接
  - `amap_weather` — 查询城市天气信息
  - 特性：时间冲突检测、行程规划、天气感知建议
  - 支持位置查询、路线规划和周边地点搜索

## 📋 环境变量

### 后端（backend/.env）
```env
# 应用程序模式。"dev" 启用 uvicorn 自动重载
MODE=dev

# Web 服务器配置
HOST=0.0.0.0
PORT=8080

# =============================================================================
# LLM 配置 - 通过 LLM_MODELS 支持多模型（推荐）
# =============================================================================
# 模型命名约定：
#   - 普通模型：名称不含 "thinking" 后缀（如 "default"、"gpt-4"、"glm-4"）
#   - 思考模型：名称必须以 "thinking" 结尾（如 "deepseek-thinking"、"qwen-thinking"）
#   - "thinking" 后缀决定模型是否出现在思考模式选择器中
#
# 支持的提供商：dashscope（阿里云）、zai（智谱）等
# 完整提供商列表请参阅 LiteLLM 文档：https://docs.litellm.ai/docs/providers

LLM_MODELS=[{"model_name":"qwen3.5-27b","litellm_params":{"model":"dashscope/qwen3.5-27b","api_key":"sk-xxx","extra_body":{"enable_thinking":false}}},{"model_name":"qwen3.5-flash-thinking","litellm_params":{"model":"dashscope/qwen3.5-flash-2026-02-23","api_key":"sk-xxx","extra_body":{"enable_thinking":true}}},{"model_name":"glm5","litellm_params":{"model":"zai/glm-5","api_key":"xxx.xxx","extra_body":{"thinking":{"type":"disabled"}}}},{"model_name":"glm5-thinking","litellm_params":{"model":"zai/glm-5","api_key":"xxx.xxx","extra_body":{"thinking":{"type":"enabled"}}}}]

# 普通聊天的默认模型（必须与 LLM_MODELS 中的 model_name 匹配）
LLM_DEFAULT_MODEL=qwen3.5-27b
# 默认思考模型（必须与以 "thinking" 结尾的 model_name 匹配）
LLM_THINKING_MODEL=qwen3.5-flash-thinking

# 嵌入模型
EMBEDDING_MODEL_NAME=text-embedding-v4

# =============================================================================
# LangSmith 配置
# =============================================================================
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT="AgentHub"
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=lsv2_pt_xxx...

# =============================================================================
# PostgreSQL 配置
# =============================================================================
POSTGRES_USER=langchain
POSTGRES_PASSWORD=langgraph
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agentdb

# =============================================================================
# Qdrant 配置
# =============================================================================
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=agentic_rag_survey

# =============================================================================
# Tavily 搜索 API
# =============================================================================
TAVILY_API_KEY=tvly-dev-xxx...

# =============================================================================
# 高德地图配置
# =============================================================================
# 获取 API 密钥：https://lbs.amap.com/api/webservice/guide/create-project/get-key
AMAP_KEY=your_amap_api_key_here
```

### 前端（frontend/.env）
```env
VITE_API_URL=http://localhost:8080
```

## 🔄 开发说明

- **后端**：位于 `backend/` 目录，使用 FastAPI 和异步生命周期管理
- **前端**：位于 `frontend/` 目录，使用 Vite + React + TypeScript + Tailwind CSS 构建
- **数据库脚本**：位于 `backend/scripts/` 用于初始化和维护
- **智能体注册**：智能体在 `backend/app/agents/__init__.py` 中注册并通过 PostgreSQL 控制
- **流式传输**：使用服务器发送事件（SSE）实现实时智能体响应

**开发前，请先使用 Docker 启动 PostgreSQL 和 Qdrant：**

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

# 初始化数据库（首次运行）
cd backend
python scripts/init_database.py
```

## 🐳 Docker 部署

AgentHub 提供独立的后端和前端 Docker 部署方式。

### 部署后端

仅启动后端服务。你需要提供自己的 PostgreSQL 和 Qdrant 实例。

> **⚠️ 重要：网络配置说明**
>
> 当后端在 Docker 中运行，但连接宿主机上的 PostgreSQL/Qdrant 时，你**必须**使用 `host.docker.internal` 而不是 `localhost`：
> - `POSTGRES_HOST=host.docker.internal`（不是 `localhost`）
> - `QDRANT_HOST=host.docker.internal`（不是 `localhost`）
>
> 这是因为 Docker 容器内的 `localhost` 指向容器自身，而不是宿主机。`host.docker.internal` 是一个特殊的 DNS 名称，会解析到宿主机的 IP 地址。

```bash
# 1. 复制环境变量文件
cp backend/.env.example backend/.env

# 2. 编辑 backend/.env 文件，填入你的配置
# 必填：
#   - LLM_MODELS（你的 LLM API 密钥）
#   - POSTGRES_HOST=host.docker.internal（本地 PostgreSQL）
#   - POSTGRES_USER、POSTGRES_PASSWORD、POSTGRES_DB
#   - QDRANT_HOST=host.docker.internal（本地 Qdrant）
#   - QDRANT_PORT
# 可选：TAVILY_API_KEY、AMAP_KEY、LANGCHAIN_API_KEY

# 3. 启动后端服务
docker-compose -f docker-compose.backend.yml up -d

# 4. 查看日志
docker-compose -f docker-compose.backend.yml logs -f

# 5. 停止服务
docker-compose -f docker-compose.backend.yml down
```

访问应用：
- 后端 API：`http://localhost:8080/docs`

### 部署前端

仅启动前端服务。需要后端已运行。

> **工作原理：**
> - 浏览器访问前端 `http://localhost:5173`
> - 浏览器向 `/api/v1` 发送 API 请求（相对路径，同源）
> - Nginx 将 `/api/` 请求代理到后端
> - 这避免了 CORS 问题，因为浏览器看到的是同源请求

```bash
# 1. 启动前端服务（使用默认配置）
docker-compose -f docker-compose.frontend.yml up -d

# 或使用自定义后端：
# NGINX_BACKEND_HOST=your-backend \
# NGINX_BACKEND_PORT=8080 \
# docker-compose -f docker-compose.frontend.yml up -d

# 2. 查看日志
docker-compose -f docker-compose.frontend.yml logs -f

# 3. 停止服务
docker-compose -f docker-compose.frontend.yml down
```

**环境变量说明：**

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `NGINX_BACKEND_HOST` | nginx 代理的后端主机名 | `host.docker.internal` |
| `NGINX_BACKEND_PORT` | 后端端口 | `8080` |
| `FRONTEND_PORT` | 前端暴露端口 | `5173` |

访问应用：
- 前端：`http://localhost:5173`

### Docker 文件结构

```
AgentHub/
├── docker-compose.backend.yml   # 后端部署（需外部数据库）
├── docker-compose.frontend.yml  # 前端部署（需外部后端）
├── backend/
│   ├── Dockerfile               # 后端容器
│   └── .env.example             # 环境变量模板
└── frontend/
    ├── Dockerfile               # 前端容器（多阶段构建）
    ├── nginx.conf               # Nginx 配置，含 API 代理
    └── .env.example             # 环境变量模板
```

### Docker 常用命令

```bash
# 构建镜像
docker-compose -f docker-compose.backend.yml build
docker-compose -f docker-compose.frontend.yml build

# 后台启动服务
docker-compose -f docker-compose.backend.yml up -d
docker-compose -f docker-compose.frontend.yml up -d

# 查看服务日志
docker-compose -f docker-compose.backend.yml logs -f
docker-compose -f docker-compose.frontend.yml logs -f

# 停止并删除容器
docker-compose -f docker-compose.backend.yml down
docker-compose -f docker-compose.frontend.yml down
```

## 🚧 已知限制

1. **RAG 集合**：`rag-agent` 需要预填充的 Qdrant 集合；目前没有内置的文档上传 UI
2. **测试**：目前未实现单元/集成测试

## 🚀 未来增强

- 额外的智能体类型（SQL 智能体、代码智能体、多智能体工作流）
- 后端和前端的全面测试套件
- React UI 中的智能体图可视化
- 对话搜索和过滤
- 用于 Qdrant 填充的文档上传 UI
- 智能体性能指标仪表板