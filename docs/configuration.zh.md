# 配置指南

## 概述

AgentHub 的配置主要通过环境变量文件进行管理。本文档详细说明所有配置项。

---

## 快速配置

### 后端配置

```bash
cd backend
cp .env.example .env
# 编辑 .env 文件，填入你的 API Keys
```

### 前端配置

```bash
cd frontend
cp .env.example .env
# 编辑 .env 文件，设置后端地址
```

---

## 后端完整配置说明

### 应用模式

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MODE` | `prod` | 应用模式：`prod`（生产）或 `dev`（开发，启用热重载） |
| `HOST` | `0.0.0.0` | Web 服务器监听地址 |
| `PORT` | `8080` | Web 服务器端口 |

### 数据库配置（第一层抽象）

AgentHub 采用两层数据库抽象架构。第一层通过 `DATABASE_TYPE` 在 SQLite 和 PostgreSQL 之间切换，业务代码零改动。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DATABASE_TYPE` | `sqlite` | 数据库类型：`sqlite`（零依赖）或 `postgres`（生产级） |

#### SQLite 配置（DATABASE_TYPE=sqlite）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SQLITE_DATABASE_PATH` | `./data/agenthub.db` | SQLite 数据库文件路径 |

**注意**：Docker 环境下会覆盖为 `/app/data/agenthub.db`（通过 volume 挂载）。

#### PostgreSQL 配置（DATABASE_TYPE=postgres）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `POSTGRES_USER` | `langchain` | PostgreSQL 用户名 |
| `POSTGRES_PASSWORD` | `langgraph` | PostgreSQL 密码 |
| `POSTGRES_HOST` | `localhost` | PostgreSQL 主机地址 |
| `POSTGRES_PORT` | `5432` | PostgreSQL 端口 |
| `POSTGRES_DB` | `agentdb` | PostgreSQL 数据库名 |

**注意**：Docker Compose 环境下 `POSTGRES_HOST` 应设置为服务名 `postgres`，而非 `localhost`。

### 向量数据库配置（第二层抽象）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `VECTORSTORE_TYPE` | `sqlite_vec` | 向量存储类型：`sqlite_vec`（嵌入式）或 `qdrant`（独立服务） |

#### SQLite Vec 配置（VECTORSTORE_TYPE=sqlite_vec）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SQLITE_VEC_DATABASE_PATH` | `./data/agenthub_vec.db` | SQLite 向量数据库文件路径 |

#### Qdrant 配置（VECTORSTORE_TYPE=qdrant）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `QDRANT_HOST` | `localhost` | Qdrant 服务主机地址 |
| `QDRANT_PORT` | `6333` | Qdrant 服务端口 |
| `QDRANT_COLLECTION` | `agentic_rag_survey` | Qdrant 集合名称 |

### 模型 Provider 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MODEL_PROVIDERS` | `["dashscope", "zai"]` | 前端下拉列表中显示的模型提供商 |

**支持的 Provider**：
- `openai`: OpenAI (GPT-4o, GPT-4 Turbo, etc.)
- `anthropic`: Anthropic (Claude 3, Claude 3.5 Sonnet, Opus)
- `groq`: Groq (快速推理 LLM)
- `openrouter`: OpenRouter (支持 100+ 模型)
- `dashscope`: 阿里云通义千问
- `zhipuai`: 智谱 AI (GLM 系列)
- `zai`: 字节跳动豆包

**注意**：LLM Provider 的 API Keys 在前端 Web UI 中配置（Settings → Model Providers），无需在此文件中配置。

### LangSmith 追踪配置（可选）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `LANGCHAIN_TRACING_V2` | `false` | 是否启用 LangSmith 追踪 |
| `LANGCHAIN_PROJECT` | `"AgentHub"` | LangSmith 项目名称 |
| `LANGCHAIN_ENDPOINT` | `https://api.smith.langchain.com` | LangSmith API 端点 |
| `LANGCHAIN_API_KEY` | 空 | LangSmith API Key |

启用后可在 LangSmith 平台查看所有 LLM 调用、工具调用、Agent 执行链，便于调试和性能分析。

### 工具 API Keys（必需）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `TAVILY_API_KEY` | 空 | **必需** Tavily 搜索 API Key（联网搜索功能） |
| `AMAP_KEY` | 空 | **必需** 高德地图 API Key（导航规划 Agent） |

**获取方式**：
- Tavily API Key: https://tavily.com/
- 高德地图 API Key: https://lbs.amap.com/api/webservice/guide/create-project/get-key

### API Key 加密配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `API_KEY_ENCRYPTION_KEY` | `AgentHub2026SecureKey!@#$%` | 数据库中存储的 API Keys 加密密钥 |

**重要**：
- 必须与前端的 `VITE_API_KEY_ENCRYPTION_KEY` 保持一致
- 默认密钥长度为 32 字符（256-bit AES 密钥）
- **生产环境务必修改此密钥**！
- 更改密钥会导致之前存储的所有 API Keys 无法解密

---

## 前端完整配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `VITE_API_BASE_URL` | `http://localhost:8080` | 后端 API 基础地址 |
| `VITE_APP_TITLE` | `AgentHub` | 应用显示名称 |
| `VITE_API_KEY_ENCRYPTION_KEY` | `AgentHub2026SecureKey!@#$%` | 与后端一致的加密密钥 |

**注意**：Docker 环境下可通过环境变量覆盖 `VITE_API_BASE_URL`：

```yaml
frontend:
  environment:
    - VITE_API_BASE_URL=http://backend:8080
```

---

## 配置模式切换

### 从 SQLite 模式切换到 PostgreSQL 模式

1. 修改 `backend/.env`:

```bash
# 数据库
DATABASE_TYPE=postgres
POSTGRES_HOST=postgres  # Docker 环境用服务名
POSTGRES_PORT=5432
POSTGRES_USER=langchain
POSTGRES_PASSWORD=your-password
POSTGRES_DB=agentdb

# 向量存储
VECTORSTORE_TYPE=qdrant
QDRANT_HOST=qdrant
QDRANT_PORT=6333
```

2. 重新启动容器:

```bash
docker compose up -d
```

### 数据迁移注意事项

切换数据库类型时:
- SQLite → PostgreSQL: **数据不会自动迁移**，需要手动导出导入
- PostgreSQL → SQLite: **数据不会自动迁移**，需要手动导出导入

**推荐**：切换前先导出对话历史，切换后重新创建会话。

---

## 生产环境配置清单

部署到生产环境前，请确保配置以下项：

| 检查项 | 要求 |
|--------|------|
| `DATABASE_TYPE` | 设置为 `postgres` |
| `VECTORSTORE_TYPE` | 设置为 `qdrant` |
| `POSTGRES_PASSWORD` | 使用强密码 |
| `API_KEY_ENCRYPTION_KEY` | 修改为自定义密钥（32 字符） |
| `LANGCHAIN_TRACING_V2` | 按需启用 |
| `TAVILY_API_KEY` | 已配置 |
| `AMAP_KEY` | 已配置 |
| 前端 `VITE_API_BASE_URL` | 指向正确的后端地址 |

---

## 常见问题

### Q: 修改配置后如何生效？

A: Docker 环境需要重启容器：

```bash
docker compose restart backend
```

本地开发环境自动热重载（`MODE=dev`）。

### Q: SQLite 数据库文件存在哪里？

A: 
- 本地开发: `backend/data/agenthub.db`
- Docker: 容器内 `/app/data/agenthub.db`，通过 volume 挂载到宿主机 `./backend/data/`

### Q: 如何备份配置？

A: 将 `.env` 文件纳入版本控制（但**不要提交包含真实 API Keys 的文件**）。建议维护 `.env.production` 模板。

### Q: Docker 中后端无法连接数据库？

A: 检查 `POSTGRES_HOST` 是否为 Docker Compose 服务名 `postgres`，而非 `localhost`。Docker 容器内 `localhost` 指向容器自身。