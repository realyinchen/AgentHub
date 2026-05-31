# Active Context

## Current Focus

**架构重构完成** (May 31, 2026)

完成 AgentHub 后端项目架构重构，精简代码并优化目录结构。

## Recent Changes (2026-05-31 重构)

### 已完成的重构步骤：

1. **Step 1 [P0]**: 移动 `_streaming.py` → `utils/streaming.py`
   - 统一 SSE streaming 逻辑到 utils 层

2. **Step 2 [P1]**: 移动 `infra/tools/` → `agents/tools/`
   - 工具属于 Agent 层，放入 `app/agents/tools/`
   - 包含：time.py, web.py, execute_sql_query.py, vectorstore_retriever.py

3. **Step 3 [P2]**: 移动 `prompts/` → `agents/prompts/`
   - Prompt 模板属于 Agent 层，放入 `app/agents/prompts/`
   - 包含：agent.md, chatbot.md, supervisor.md

4. **Step 4 [P3]**: 删除 `services/` 目录，功能分散到 `utils/`
   - checkpoint.py → utils/checkpoint.py
   - trace.py → utils/trace.py  
   - dag.py → utils/dag.py
   - parsers.py → utils/parsers.py
   - agent_execution.py → utils/agent_execution.py

5. **Step 5 [P4]**: 清理 API 层残留业务逻辑
   - 更新所有 import 路径
   - 移除废弃的 `log_routing_decision` 调用

### 新的目录结构：

```
backend/app/
├── api/              # API层 - 纯路由
│   └── v1/chat/      # Chat endpoints
├── agents/           # Agent层 - 业务核心
│   ├── supervisor.py # 主 Agent 入口
│   ├── context.py    # Runtime context
│   ├── middleware/   # Agent middleware
│   ├── prompts/      # Prompt 模板 (MD)
│   └── tools/        # Agent tools
├── infra/            # 基础设施层
│   ├── config.py     # 配置
│   ├── database/     # 数据库抽象
│   └── llm/          # LLM 管理
├── utils/            # 工具层 - 无业务逻辑
│   ├── streaming.py  # SSE streaming
│   ├── checkpoint.py # Checkpoint reader
│   ├── trace.py      # Trace builder
│   ├── dag.py        # DAG builder
│   └── parsers.py    # Message parsers
├── schemas/          # Pydantic 模型
├── models/           # SQLAlchemy ORM
├── crud/             # CRUD 操作
└── core/             # 应用核心
```

### 重构收益

- **更清晰的分层**: API → Agent → Infra/Utils
- **更少的抽象层**: services/ 删除，功能下沉到 utils
- **更好的内聚性**: tools 和 prompts 归属 Agent 层
- **所有 API 接口和 Agent 功能完全保留**

## Active Branches

- Main development on `main` branch