# 🚀 AgentHub — Multi-Agent 系统运行平台

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">简体中文</a>
</p>

<p align="center">
  <strong>生产级 Multi-Agent 运行平台</strong><br>
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
  <img src="https://via.placeholder.com/800x450?text=AgentHub+Demo+Screenshot" alt="AgentHub Demo" width="800">
</p>

---

## 项目介绍

**AgentHub** 是一个专注于生产环境的 Multi-Agent 运行平台，为 AI 应用提供高性能、稳定可靠的 Agent 执行环境。

它**不是**另一个 Agent 编排框架，而是真正的 **Agent 运行时平台**，解决从原型到生产落地的最后一公里问题。

### 核心优势

| 维度 | 亮点 |
|------|------|
| ⚡ **高并发低延迟** | 单进程轻松支持数千并发，token 级实时流式响应 |
| 👥 **多用户隔离** | 独立会话空间，数据完全隔离 |
| 🧠 **长期记忆** | 跨会话持久化记忆，支持语义检索 |
| 🔄 **动态模型切换** | 会话中随时切换 LLM，无需重新开始 |

### 适用场景

- **个人开发者 / 学习者**：快速实践 LangGraph 生产级开发
- **创业团队**：快速验证 Multi-Agent 产品想法
- **企业用户**：构建内部 AI 助手、知识库、智能工作流

### 核心功能

- 🤖 多模型智能对话 + 实时工具调用（搜索、时间等）
- ⚡ 流式响应 + 思考过程可视化
- 📊 Agent 执行路径追踪
- 🧠 长期记忆与用户偏好记忆
- 🌐 接入微信，随时随地 Ask Agent

---

## 快速开始

### Docker 一键部署（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# 2. 创建数据目录
mkdir -p /app/agenthub/backend/data /app/agenthub/frontend

# 3. 配置环境变量
cp backend/.env.example /app/agenthub/backend/.env
cp frontend/.env.example /app/agenthub/frontend/.env
# 编辑 /app/agenthub/backend/.env，填入 API Keys

# 4. 启动服务
docker compose build && docker compose up -d
```

访问 `http://localhost` 即可使用。

### 必填环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `SYSTEM_DEFAULT_LLM_MODEL` | 默认模型（provider/model-id 格式） | `openai/gpt-4o` |
| `SYSTEM_DEFAULT_LLM_API_KEY` | 对应 Provider 的 API Key | `sk-xxx` |
| `API_KEY_ENCRYPTION_KEY` | 32 字符 AES-256 密钥 | `python -c "import secrets; print(secrets.token_urlsafe(24)[:32])"` |

---

## 技术架构

### 四层架构

AgentHub 采用清晰的四层架构，依赖方向严格单向：`API → Agent → Service → Infra`。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Layer 4: API Layer (HTTP Interface)                    │
│   auth.py · chat/ · models.py · weixin.py                                   │
│                              ↓ 参数校验 + 路由                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Layer 3: Agent Layer (Business Logic)                    │
│   supervisor.py · middleware/ · prompts/ · tools/                            │
│                              ↓ 中间件链 + 工具调用                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Layer 2: Service Layer (Business Services)              │
│   streaming.py · chat.py · weixin_listener.py                                │
│                              ↓ SSE 流式 + 会话管理                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Layer 1: Infrastructure Layer (Foundation)                 │
│   config.py · database/ · llm/ · security/                                    │
│                              ↓ PostgreSQL + LiteLLM + JWT                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 层级职责

| 层级 | 职责 |
|------|------|
| **API Layer** | HTTP 接口、参数校验、SSE 流式响应 |
| **Agent Layer** | Agent 编译、中间件链、工具执行、状态管理 |
| **Service Layer** | 会话管理、消息持久化、Token 统计 |
| **Infrastructure Layer** | 数据库连接池、LLM 网关、向量存储、认证 |

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

### 技术栈

| 层级 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn（异步） |
| AI 编排 | LangChain v1 + LangGraph（create_agent + middleware + astream_events v3） |
| LLM 网关 | LiteLLM Router（多 Provider 自动 fallback + retry） |
| 数据库 | PostgreSQL + pgvector + asyncpg |
| 前端 | React 19 + TypeScript + Tailwind CSS + shadcn/ui |

---

## 迭代日志

### v0.0.1 (2026-06-04) — 首个版本 🎉

---

## 许可证

本项目采用 [Apache 2.0 许可证](LICENSE)。