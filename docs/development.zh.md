# 开发指南

## 概述

本文档面向希望参与 AgentHub 开发或进行自定义功能开发的开发者。

---

## 技术栈总览

| 层次 | 技术 | 版本要求 |
|------|------|---------|
| 前端 | React + TypeScript + Vite | Node.js 20+ |
| 样式 | TailwindCSS + shadcn/ui | - |
| 后端 | FastAPI + Python | Python 3.11+ |
| AI 层 | LangChain + LangGraph | - |
| 数据库 | SQLite / PostgreSQL + Qdrant | - |

---

## 本地开发环境搭建

### 前置条件

- Python 3.11+
- Node.js 20+
- pnpm（推荐）或 npm
- Docker（可选，用于 PostgreSQL + Qdrant 模式）

### 后端开发环境

```bash
# 1. 克隆项目
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub/backend

# 2. 创建虚拟环境
python -m venv venv

# 3. 激活虚拟环境
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 4. 安装依赖
pip install -r requirements.txt

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env，填入必要的 API Keys

# 6. 启动开发服务器（热重载）
MODE=dev python run_backend.py
```

**开发模式特性**：
- Uvicorn 自动重载（代码修改自动重启）
- 详细的日志输出
- 数据库连接池自动维护

### 前端开发环境

```bash
# 1. 进入前端目录
cd ../frontend

# 2. 安装依赖
pnpm install
# 或 npm install

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，确保 VITE_API_BASE_URL 指向正确的后端地址

# 4. 启动开发服务器
pnpm dev
# 或 npm run dev
```

**访问地址**：
- 前端：http://localhost:5173
- 后端 API：http://localhost:8080
- API 文档：http://localhost:8080/docs

---

## 项目结构

### 后端结构

```
backend/
├── app/
│   ├── agents/              # Agent 实现
│   │   ├── chatbot.py      # Chatbot Master Agent
│   │   ├── navigator.py    # 导航规划 Agent
│   │   └── __init__.py
│   ├── api/                 # API 路由
│   │   ├── agents.py
│   │   ├── chat.py
│   │   ├── models.py
│   │   ├── providers.py
│   │   ├── sessions.py
│   │   └── __init__.py
│   ├── database/            # 数据库抽象层
│   │   ├── backends/
│   │   │   ├── postgres/
│   │   │   └── sqlite/
│   │   ├── factory.py      # 工厂模式
│   │   └── interfaces/     # 接口定义
│   ├── models/              # Pydantic 模型
│   ├── prompt/              # System Prompts
│   ├── services/            # 业务逻辑层
│   ├── tools/               # 工具函数
│   └── utils/               # 工具函数
├── data/                    # 数据文件（SQLite 数据库等）
├── scripts/                 # 脚本（数据库初始化等）
├── requirements.txt
├── run_backend.py
└── .env
```

### 前端结构

```
frontend/
├── src/
│   ├── components/          # React 组件
│   │   ├── ui/             # shadcn/ui 组件
│   │   ├── chat/           # 聊天相关
│   │   ├── settings/       # 设置相关
│   │   └── ...
│   ├── hooks/               # 自定义 Hooks
│   ├── lib/                 # 工具库
│   ├── services/            # API 服务
│   ├── store/               # 状态管理 (Zustand)
│   ├── types/               # TypeScript 类型
│   ├── App.tsx
│   └── main.tsx
├── public/
├── package.json
├── vite.config.ts
└── .env
```

---

## 核心开发概念

### 1. Agent 开发

所有 Agent 基于 **LangGraph** 构建，支持：
- 状态管理（State）
- 工具调用（Tool Calling）
- 条件分支（Conditional Routing）
- 记忆持久化（Checkpointer）

**开发新 Agent 参考文档**：[添加新 Agent](./add-new-agent.zh.md)

**关键点**：
- 始终使用 `streaming_completion()` 自动获得 Token 统计
- 通过 `AgentState` 传递消息上下文
- 使用 `Checkpointer` 持久化对话状态

### 2. 数据库抽象层开发

新增数据库后端需要实现三个接口：

```python
# 1. 实现 DatabaseInterface
class MyDatabase(DatabaseInterface):
    async def get_session(self): ...
    async def create_tables(self): ...

# 2. 实现 VectorstoreInterface
class MyVectorstore(VectorstoreInterface):
    async def search_with_embedding(self, ...): ...

# 3. 实现 CheckpointInterface
class MyCheckpointer(Saver, CheckpointInterface):
    ...
```

然后在 `factory.py` 中注册：

```python
_DB_BACKENDS["my_db"] = MyDatabase
_VS_BACKENDS["my_vec"] = MyVectorstore
_CP_BACKENDS["my_cp"] = MyCheckpointer
```

### 3. API 开发

新增 API 端点：

```python
# app/api/my_endpoint.py
from fastapi import APIRouter

router = APIRouter(prefix="/my-endpoint", tags=["MyEndpoint"])

@router.get("/")
async def my_endpoint():
    return {"message": "Hello World"}
```

在 `app/main.py` 中注册：

```python
from app.api.my_endpoint import router as my_router
app.include_router(my_router, prefix="/api/v1")
```

### 4. 前端组件开发

使用 shadcn/ui + TailwindCSS 开发组件：

```bash
# 添加新的 shadcn 组件
pnpm dlx shadcn-ui@latest add component-name
```

组件开发原则：
- 使用 TypeScript 类型定义
- 遵循现有组件的代码风格
- 支持响应式布局
- 添加适当的加载状态和错误处理

---

## 开发工作流

### 代码风格

**后端 (Python)**
- 遵循 PEP 8
- 使用类型注解（Type Hints）
- Docstring 风格：Google 风格或 NumPy 风格

**前端 (TypeScript)**
- 使用 ESLint + Prettier（已配置）
- 运行 `pnpm lint` 检查代码

```bash
# 前端代码检查
cd frontend
pnpm lint
pnpm lint:fix  # 自动修复
```

### Git 提交规范

```
feat: 新增功能
fix: 修复 Bug
docs: 文档更新
style: 代码格式调整
refactor: 重构
test: 测试相关
chore: 构建/工具/依赖相关
```

### 提交前检查

```bash
# 后端
cd backend
python -m pytest  # 如有测试

# 前端
cd frontend
pnpm build  # 确保可构建
```

---

## 调试技巧

### 后端调试

#### 1. LangSmith 追踪

启用 `.env` 中的 LangSmith 配置：

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-key
```

在 https://smith.langchain.com/ 查看详细的调用链。

#### 2. 日志调试

```python
import logging
logger = logging.getLogger(__name__)

logger.info("信息")
logger.debug("调试信息")
logger.error("错误信息")
```

#### 3. 直接测试 Agent

```python
# 在 Python REPL 中直接测试
from app.agents.chatbot import create_chatbot_agent
from app.utils.llm import get_llm

llm = get_llm("gpt-4o")
agent = await create_chatbot_agent(llm, checkpointer)

# 调用 Agent
result = await agent.ainvoke({"messages": [("user", "你好")]})
print(result)
```

### 前端调试

#### 1. React DevTools

安装浏览器扩展进行组件树检查和状态调试。

#### 2. 网络请求调试

浏览器 DevTools → Network 面板查看 API 请求。

#### 3. 状态管理调试

Zustand store 已配置 Redux DevTools 支持，可在浏览器中查看状态变化。

---

## 测试

### 后端测试

```bash
cd backend
python -m pytest tests/ -v
```

**测试目录结构**：
```
tests/
├── unit/           # 单元测试
├── integration/    # 集成测试
└── conftest.py     # pytest 配置
```

### 前端测试

```bash
cd frontend
pnpm test           # 运行测试
pnpm test:watch     # 监听模式
pnpm test:coverage  # 覆盖率报告
```

---

## 常见开发问题

### Q: 如何添加新的 LLM Provider？

A: 
1. 在 `app/utils/llm.py` 中添加 Provider 支持
2. 在前端 `src/types/models.ts` 添加类型
3. 在前端 `src/services/models.ts` 添加 API 调用

### Q: 前端热重载不工作？

A: 
1. 检查 Vite 配置 `server.hmr`
2. 确保 `VITE_API_BASE_URL` 正确
3. 清除浏览器缓存和 node_modules 后重新安装

### Q: Agent 响应很慢？

A: 
1. 检查 LLM API 网络连接
2. 检查是否启用了流式输出
3. 使用 LangSmith 分析瓶颈
4. 考虑使用更快的模型（如 GPT-4o mini）

### Q: 数据库迁移如何处理？

A: 
1. SQLite 模式：直接删除 `.db` 文件自动重建（开发环境）
2. PostgreSQL 模式：使用 `alembic` 或手动编写迁移脚本
3. 参考 `scripts/` 目录下的初始化脚本

---

## 性能优化建议

### 后端优化

1. **缓存**：使用 `TTLCache` 缓存频繁访问的数据（模型列表、Provider 状态等）
2. **异步**：所有数据库和网络操作使用 async/await
3. **连接池**：PostgreSQL 使用连接池复用连接
4. **批量操作**：尽量减少数据库查询次数

### 前端优化

1. **React.memo**：避免不必要的重渲染
2. **React Query/SWR**：缓存 API 响应
3. **懒加载**：使用 `React.lazy()` 分割代码
4. **虚拟列表**：长对话列表使用虚拟滚动

---

## 贡献指南

欢迎提交 Pull Request！

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/my-new-feature`
3. 提交更改：`git commit -am 'feat: add some feature'`
4. 推送到分支：`git push origin feature/my-new-feature`
5. 提交 Pull Request

**PR 要求**：
- 描述清晰的功能说明
- 通过所有测试
- 更新相关文档
- 遵循代码风格规范