# 🚀 AgentHub — 生产级 Multi-Agent 运行平台

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

<p align="center">
  <strong>基于 FastAPI + LangGraph 的生产级 Agent 运行时平台</strong><br>
  高并发 · 低延迟 · 多用户隔离 · 长期记忆 · 动态模型切换
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
</p>

<p align="center">
  关注公众号 <strong>AgenticHub</strong> 获得<br>
  AI智能体工程实战 | Agentic思维实现 | AgentHub开源项目作者 | 每周新增实战Agent + 完整代码 + 踩坑记录<br>
  <img src="https://github.com/realyinchen/AgentHub/blob/dev/imgs/qrcode_for_agentichub.jpg" alt="AgenticHub">
</p>

<p align="center">
  简洁的交互页面<br>
  <img src="https://github.com/realyinchen/AgentHub/blob/dev/imgs/webui.gif" alt="webui"><br>
  支持微信渠道<br>
  <img src="https://github.com/realyinchen/AgentHub/blob/dev/imgs/wechat.gif" alt="wechat channel"><br>
</p>

---

## 项目介绍

**AgentHub** 是一个专注于生产环境的 Multi-Agent 运行平台，为 AI 应用提供高性能、稳定可靠的 Agent 执行环境。

它**不是**另一个 Agent 编排框架，而是真正的 **Agent 运行时平台**——解决从原型到生产落地的最后一公里问题。

### 核心架构

AgentHub 采用 **Supervisor 模式**：一个超级 Agent（Supervisor）作为统一入口，自动识别用户意图并调度相应的 SubAgent 完成任务。

```
用户请求 → Supervisor（意图识别 + 任务路由）
                    │
                    ├── 闲聊 SubAgent（当前可用）
                    │
                    ├── ReAct SubAgent（规划中）
                    │
                    ├── RAG SubAgent（规划中）
                    │
                    └── 多 Agent 协作（规划中）
```

**当前状态**：Supervisor 已具备基础对话能力和工具调用（时间查询、网络搜索），SubAgent 调度能力正在开发中。

### 核心特点

| 特点 | 说明 |
|------|------|
| ⚡ **高并发低延迟** | FastAPI async + SSE token 级流式响应 + LiteLLM Router 自动 fallback/retry |
| 🧠 **LangChain v1 官方范式** | `create_agent` + Middleware Chain + `astream_events` v3，符合生产最佳实践 |
| 👥 **多用户隔离** | 独立会话空间 + LangGraph Checkpointer 状态持久化，数据完全隔离 |
| 🔄 **动态模型切换** | 运行时切换 LLM（OpenAI、Anthropic、Groq、Ollama 等），无需重启会话 |
| 💾 **长期记忆** | LangGraph Store + PGVector 语义检索，跨会话持久化用户偏好 |
| 🐳 **一键部署** | Docker Compose 三容器编排，5 分钟启动完整服务 |

### 适用场景

- **个人开发者 / 学习者**：快速实践 LangGraph 生产级开发
- **创业团队**：快速验证 Multi-Agent 产品想法
- **企业用户**：构建内部 AI 助手、知识库、智能工作流

---

## 快速开始

### Docker 一键部署（推荐）

#### 前置条件

- Docker 20.10+
- Docker Compose v2+

#### 部署步骤

```bash
# 1. 克隆项目
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# 2. 创建环境变量文件
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 3. 编辑后端配置（填入必填项）
vim backend/.env
```

#### 必填环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `SYSTEM_DEFAULT_LLM_MODEL` | 默认模型 | `gpt-4o` 或 `openai/gpt-4o` |
| `SYSTEM_DEFAULT_LLM_API_KEY` | 模型 API Key | `sk-xxx` |
| `API_KEY_ENCRYPTION_KEY` | AES-256 加密密钥（32 字符） | `python -c "import secrets; print(secrets.token_urlsafe(24)[:32])"` |
| `JWT_SECRET_KEY` | JWT 签名密钥 | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

```bash
# 4. 构建并启动
docker compose build && docker compose up -d

# 5. 查看日志
docker compose logs -f
```

#### 访问地址

- 本地：http://localhost
- 服务器：http://your-server-ip

> ✅ 默认使用 **PostgreSQL + pgvector**，数据持久化到 Docker 命名卷

---

## 技术架构

### 四层架构

AgentHub 采用清晰的四层架构，依赖方向严格单向：`API → Agent → Service → Infra`。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Layer 4: API Layer (HTTP Interface)                   │
│                                                                              │
│   auth.py · chat/ · models.py · traces.py · weixin.py                       │
│                                                                              │
│   职责：HTTP 接口、参数校验、SSE 流式响应、全局异常处理                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Layer 3: Agent Layer (Business Logic)                    │
│                                                                              │
│   supervisor.py · middleware/ · prompts/ · tools/                           │
│                                                                              │
│   职责：Agent 编译、中间件链、工具执行、状态管理                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Layer 2: Service Layer (Business Services)              │
│                                                                              │
│   streaming.py · chat.py · weixin_listener.py                               │
│                                                                              │
│   职责：会话管理、消息持久化、SSE 流式处理、微信消息监听                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Layer 1: Infrastructure Layer (Foundation)                │
│                                                                              │
│   config.py · database/ · llm/ · security/ · auth.py                        │
│                                                                              │
│   职责：数据库连接池、LLM 网关、向量存储、JWT 认证、配置管理                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 请求处理流程

```
用户请求 → API 校验 → Service 构建上下文 → Agent 中间件链 → LLM 调用 → SSE 流式返回
                                                    ↓
                                            工具执行（时间/搜索）
                                                    ↓
                                        Checkpointer 持久化状态
                                                    ↓
                                        Store 长期记忆语义检索
```

### 目录结构

```
AgentHub/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── api/               # API 层：HTTP 接口
│   │   ├── agents/            # Agent 层：Supervisor + Middleware + Tools
│   │   ├── infra/             # 基础设施层：数据库、LLM、配置
│   │   ├── crud/              # 数据库 CRUD 操作
│   │   ├── models/            # SQLAlchemy ORM 模型
│   │   └── schemas/           # Pydantic 请求/响应模型
│   └── requirements.txt
├── frontend/                   # 前端服务
│   └── src/
│       ├── components/        # 通用组件
│       ├── features/          # 功能模块（chat、settings 等）
│       └── lib/               # 工具库
└── docker-compose.yml         # Docker 编排配置
```

---

## 更新日志

### v0.0.1 (2026-06-05) — 首次上线 🎉

**核心功能**

- ✅ Supervisor Agent 基础对话能力
- ✅ 动态模型切换（运行时切换 LLM）
- ✅ 工具调用（时间查询、网络搜索）
- ✅ SSE 流式响应
- ✅ 多用户会话隔离
- ✅ 长期记忆（LangGraph Store + PGVector）
- ✅ 微信接入（WebSocket 消息推送）
- ✅ Docker 一键部署


---

## 许可证

本项目采用 [Apache 2.0 许可证](LICENSE)。

---

<p align="center">
  <strong>Made with ❤️ for the Agentic Future</strong>
</p>