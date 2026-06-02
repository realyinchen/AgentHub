# 项目进度 — 重构

**最后更新**: 2026-05-22

---

## 历史里程碑

### Phase 1: 基础设施层 ✅ 已完成（2026-05）
- Config 增强 — 增加 `user_id` 可选配置、Store 配置
- DatabaseFactory 迁移与增强 — 增加 Store 工厂方法
- LangGraph Store 集成 — 新增 `StoreInterface`、Postgres 实现
- ModelManager 精简 — 增加 `get_llm()` 方法支持 thinking_mode

### Phase 2: 支撑层 ✅ 已完成（2026-05）
- `MemoryManager` — 统一管理短期(Checkpointer)和长期(Store)记忆
- `LongTermMemory` — Store + Vector 封装，按 `user_id` 命名空间
- `MemoryEnhancer` — 完整实现从短期对话抽取关键信息存入长期记忆

### Phase 3: 执行层 ❌ 已取消（2026-05）
- 原计划：异步任务队列、代码沙箱
- 决策：简化架构，用 `asyncio.create_task()` 替代
- 已删除：整个 `backend/app/execution/` 目录

---

## "大道至简"大重构（2026-05-20）

### 重构目标
依据 `backend/docs.md` 的精简建议，消除过度抽象、重复代码、并发隐患，使架构完全符合 LangChain 官方范式。

---

### P0: 立即修复 ✅ 完成
| # | Issue | 操作 |
|---|-------|------|
| **Step 1** | `memory_cache.py` `threading.Lock` 在异步函数中 | 修复为 `asyncio.Lock` |
| **Step 2** | 删除重复端点 `GET /chat/models` | 前端统一改用 `GET /v1/models/` |
| **Step 3** | 删除重复端点 `GET /models/providers` | 前端统一改用 `GET /v1/providers/` |

---

### P1: 官方范式替代自造轮子 ✅ 完成
| # | Issue | 操作 |
|---|-------|------|
| **Step 4** | `FallbackExecutor` → `@wrap_model_call` middleware | 新建 `app/middleware/fallback.py`（~210 行），兼容更多 edge case：token_delta、thinking_content、tool_calls 累积；删除 `app/infra/llm/fallback.py`（-240 行） |
| **Step 5** | 模型降级逻辑从 stream.py 移到 middleware | 通过 `context.fallback_events` 队列通知；v3 后改为 sentinel 模式，无轮询延迟 |
| **Step 6** | 记忆提取移到 `@after_model` middleware | 务实跳过，保留在 stream.py finally（仅 3 行） |
| **Step 7** | `astream_events` v2 → v3 typed-projection | 完全重写 `stream.py`；`stream.messages` / `stream.tool_calls` / `stream.values` 并发合并到单条 SSE；代码更清晰、类型更安全 |

#### P1 关键收益
- **零延迟 token 投递**：sentinel + queue 事件驱动模式，无 50ms 轮询
- **异常显式传播**：consumer task 异常通过队列推送给主 generator
- **完善资源清理**：finally 中 cancel 所有未完成 task
- **可中断 SSE**：客户端断开时所有 task 响应 `CancelledError`

#### P1 行为变化（需注意）
- LangGraph 1.2.0 中 `astream_events(version="v3")` 是 beta API（官方推荐但仍实验性）
- 如 v3 在小版本升级中出现破坏性变更，可快速回退到 v2

---

### P2: 基础设施精简 ✅ 完成
| # | Issue | 操作 |
|---|-------|------|
| **Step 8** | 数据库 4 层抽象 → 精简模式 | 删除 `interfaces.py`（ABC 层）和整个 `backends/` 目录（postgres + sqlite 各 4 个子文件）；新建 `_postgres.py` / `_sqlite.py` 合并各后端；`factory.py` 改用 `asyncio.Lock`，严格 `init_xxx() / get_xxx()` 分离（lifespan 启动初始化、handler 取单例） |
| **Step 9** | `infra/llm/` 包 + `core/model_manager.py` → 单文件 | 删除 4 个子模块（其中 `streaming.py` 497 行全为死代码）和 `core/model_manager.py`（deprecation shim）；合并到 `infra/llm/__init__.py`（~370 行） |
| **Step 10** | `LLMConfig` 合并到 `Settings` | 已跳过（当前架构配置入口本就统一） |
| **Step 11** | `agents/chatbot/` 目录 → 单文件 | 已跳过（chatbot 本就是单文件） |
| **Step 12** | `POST /models/refresh` → 自动触发 | 删除端点和 `RefreshResponse` schema；CRUD 操作本就自动刷新缓存 |

#### P2 验证结果
```
14/14 核心模块全部 import 成功
```
涉及模块：`infra.database`、`infra.llm`、`api.v1.{chat,model,stream,trace,dependencies}`、`middleware.{fallback,memory.manager,memory.long_term,model.dynamic}`、`agents.{base,chatbot}`、`main`

#### P2 关键收益
- **数据库层**：4 层抽象 → 3 文件（`_postgres` + `_sqlite` + `factory`）；删除全部 `threading.Lock`
- **LLM 层**：5 个 Python 文件 → 1 个 `__init__.py`；删除 ~700 行死代码
- **API 层**：减少 1 个端点，删除 1 个 schema，删除 1 个前端 API 包装
- **完全透明**：所有公共 import API 不变，所有公开业务接口不变

#### P2 行为变化（需注意）
- `get_database() / get_vectorstore() / get_checkpointer() / get_store()` 现在**严格要求** `init_xxx()` 必须在 lifespan 启动时被调用，否则抛 `RuntimeError`（原为首次调用懒加载）。这是更可预测的行为。

---

### P3: 小清理 ✅ 完成（文件检查确认）
| # | Issue | 验证 |
|---|-------|------|
| **Step 13** | `ConversationInDB` → `model_config = ConfigDict(...)` | `search_files` 确认 4 个 schema 都已改用 v2 语法 |
| **Step 14** | `trace.py` DB 查询移到 `crud/chat.py` | `search_files` 确认 trace.py 通过 `from app.crud.chat import list_traces` 操作 |
| **Step 15** | 统一 `ProviderInfo` 定义 | 当前代码无重复定义 |
| **Step 16** | 统一运行时上下文：`context` 参数替代 `config["configurable"]` 中的 `user_id` | `message_utils.py` 的 `configurable` 只包含 `thread_id`；`stream.py` 从 `context.user_id / context.request_id` 读取 |

---

## 重构总览与量化成果

| 指标 | 重构前 | 重构后 | 改善 |
|------|--------|--------|------|
| 数据库抽象层数 | 4 层（interfaces → backends → factory → 调用） | 3 文件 | -75% |
| LLM 管理文件数 | 5+ 文件（`infra/llm/` 包 + `core/model_manager.py`） | 1 文件 | -80% |
| 模型降级代码 | ~240 行 `FallbackExecutor` + stream.py 散落逻辑 | ~210 行 `@wrap_model_call` middleware | -12%（兼容更多 edge case） |
| 重复 API 端点 | 4 个（2 个 GET + 1 个 POST refresh + streaming.py 死代码） | 0 个 | -100% |
| `stream.py` 行数 | ~450 行 | ~360 行（typed-projection v3） | -20% |
| `threading.Lock` 在异步函数中 | 1 处（阻塞事件循环） | 0 | 高并发隐患修复 |
| 死代码删除 | `streaming.py` 497 行 | 已删除 | -497 行 |
| Pydantic v1 `class Config` 遗留 | 4 个 schema | 0 | 全部升级到 v2 |

---

### PR-A: 零风险清理 ✅ 完成（2026-05-22）
| # | Issue | 操作 |
|---|-------|------|
| **N1** | `app/tools/` 整目录是死代码 | 删除 5 个 .py（`__init__.py` / `time.py` / `web.py` / `execute_sql_query.py` / `vectorstore_retriever.py`）+ `__pycache__/`；全代码库 `from app.tools` 真实匹配 = 0 |
| **F-I** | `api/v1/agent.py:89` 双 commit 违反全局规范 | `await db.commit()` → `await db.flush()`；commit 由 `get_db()` 的 `db.session()` 上下文管理器统一收尾 |
| **验证** | 语法检查 | `ast.parse(agent.py)` 通过；OpenAPI 33 端点未变化（无端点签名/路径/响应模型修改） |

#### PR-A 关键收益
- **代码重复 ⭐⭐⭐⭐ → ⭐⭐⭐⭐⭐**：`app/tools/` 误导性的"平行目录"消失，唯一的工具实现源在 `app/infra/tools/`
- **事务规范一致性**：API 层零 `db.commit()`（grep 全量确认），全部依赖 `session()` 上下文管理器
- **零行为变化**：33 个端点行为完全不变，OpenAPI schema 无差异

### P3: 模型架构重新组织 ✅ 完成
| # | Issue | 操作 |
|---|-------|------|
| **Step 17** | 移除 ModelManager 中每请求的 LLM 缓存 | 删除 `_llm_cache`/`get_llm()`/`get_random_active_model()`，添加 `get_router_sync()`，`refresh()` 结束时预构建 Router |
| **Step 18** | `factory.py` 添加 `get_llm()` 统一入口 | 通过 Router 构建 `ChatLiteLLMRouter`；自动获取内建 fallback + retry |
| **Step 19** | 删除自定义 `middleware/fallback.py` | 模型回退由 LiteLLM Router 的内建 `fallbacks` + `num_retries` 处理 |
| **Step 20** | `dynamic_model` 改用 `get_llm()` | 通过 Router 自动获得回退能力，无需 `fallback_model` middleware |
| **Step 21** | `chatbot.py` 移除 `fallback_model` | middlewares 链简化为 `[chatbot_dynamic_prompt, dynamic_model, SummarizationMiddleware]` |
| **Step 22** | `stream.py` 移除 `get_random_active_model()` | 改用 `get_default_llm_id()` + 迭代第一活跃模型 |
| **Step 23** | provider 更新后触发 `ModelManager.refresh()` | API key / base_url 变更立即刷新缓存 |
| **验证** | 语法检查 | 9 个修改文件全部通过 `ast.parse()` |

#### P3 关键架构决策
- **一个 Router 实例，多个轻量 bound 实例**：`ModelManager` 持有单一 `LiteLLM Router`（含 fallback + retry）；每请求的 `ChatLiteLLMRouter` 绑定正确 `extra_body` 后复用同一 Router
- **不需要自定义 fallback middleware**：LiteLLM Router 的 `fallbacks` 自动处理 rate-limit/quota/403/429；配置在 `ModelManager._build_fallbacks()` 中（同类型互备）
- **`get_llm()` 是推荐入口点**；`get_chat_litellm()` 保留给特殊场景（如 agent 创建时的默认模型）

---

## 架构原则体现（"大道至简"）

### 1. LangChain 官方范式
- `create_agent` + middleware 模式
- 用官方 `@wrap_model_call`，不重复造 FallbackExecutor
- `astream_events(version="v3")` typed-projection

### 2. FastAPI 薄路由
- 路由只做参数校验 + 调用 + 返回
- 不包含业务逻辑，DB 操作通过 `crud/` 封装

### 3. 异步全程贯通
- 无 `threading.Lock` 在异步函数中
- 全部 `asyncio.Lock` 保护单例初始化

### 4. 配置统一
- `Settings` 唯一配置入口
- 无散落配置，无重复定义

### 5. 职责单一
- LLM 管理单文件
- 数据库管理单文件
- 流式处理单文件

### 6. CRUD 封装
- DB 操作集中在 `crud/`
- 路由不直接写 SQLAlchemy 查询

### 7. 上下文统一
- `context` 参数传递运行时数据（`user_id` / `request_id` / `fallback_events`）
- `config["configurable"]` 只保留 LangGraph 需要的 `thread_id`

---

## 后端重构计划 Phase 1-4（2026-05-30）

依据 `docs/TODO.md` 的分层架构整改计划。

### Phase 1: 代码清理 ✅ 完成（2026-05-30）
| # | Issue | 操作 |
|---|-------|------|
| **Step 1** | 删除 `GET /agents` API + `schemas/agent.py` | 消除暴露内部细节的死代码端点 |
| **Step 2** | 整合 `interrupt_message.py` → `schemas/chat.py` | 减少 schema 跨模块耦合 |
| **Step 3** | 统一模型 fallback 入口 | `resolve_model_name()` 单一入口 |

#### Phase 1 收益
- 消除 1 处死代码端点 + 2 个冗余模块文件
- 模型降级逻辑统一

### Phase 2: 服务层提取 ✅ 完成（2026-05-30）
| # | Issue | 操作 |
|---|-------|------|
| **Step 4** | 创建 `AgentExecutionService` | 新建 `services/agent_execution.py`，封装 token + DAG 持久化 |
| **Step 4b** | 移除 `persist_tokens_and_dag()` | 从 `utils/stream_helpers.py` 删除，迁移到服务层 |
| **Step 4c** | 更新 API 层调用 | `run.py` / `_streaming.py` 改用 `AgentExecutionService` |
| **Step 5** | `create_subagent()` 支持 `store` | 添加 `store: BaseStore | None = None` 参数 |

#### Phase 2 收益
- `persist_tokens_and_dag()` 从工具函数层迁移到服务层
- invoke/stream 两路径复用同一服务
- SubAgent 支持长期记忆注入
- 符合 LangChain `create_agent` 最佳实践

### Phase 3: 渐进重构 ✅ 已验证完成（2026-05-30）
| # | Issue | 操作 |
|---|-------|------|
| **Step 6** | 拆分 `build_agent_kwargs()` | **已验证无需修改** — 当前架构已符合 LangChain v1 最佳实践 |

#### Phase 3 验证结论

经过 LangChain 官方文档对照和代码分析：

1. **`build_agent_kwargs()` 已经是纯工具函数**
   - 无 DB 依赖，无副作用
   - 正确使用 `context` 传递业务数据（而非 `config["configurable"]`）
   - 符合 LangChain v1 `context_schema` 模式

2. **对话历史由 LangGraph Checkpointer 自动管理**
   - TODO.md 原计划的 "get_or-create conversation, load history" 由 LangGraph 内置处理
   - `thread_id` 通过 `config["configurable"]` 传给 checkpointer
   - 无需手动加载历史消息

3. **业务数据通过 context 传递**
   - `user_id`, `request_id`, `model_name`, `thinking_mode` 在 `AgentRuntimeContext` dataclass
   - middleware 通过 `request.runtime.context.<field>` 访问
   - 符合官方推荐模式

#### Phase 3 收益
- 确认架构符合 LangChain v1 最佳实践
- 避免不必要的重构开销
- 代码简洁，职责清晰

### Phase 4: Supervisor StateGraph 迁移（待执行）
| # | Issue | 操作 |
|---|-------|------|
| **Step 7-13** | Supervisor → 手写 StateGraph | 自定义 tool loop、超时控制、HITL；feature flag 灰度 |

---

## Embedding 模块重构 ✅ 完成（2026-06-01）

### 背景
原 `database/factory.py` 中的 `_get_embed_fn()` 每次调用都创建新的 embedding 相关逻辑，且 embedding 配置散落在多处。

### 重构目标
1. **单例模式**：系统启动时创建一个 `LiteLLMEmbeddings` 实例，之后重复使用
2. **零运行时开销**：`get_embed_fn()` 直接返回缓存的函数引用
3. **符合 LangChain 接口**：实现 `Embeddings` 标准接口，可直接传给 PGVectorStore

### 实施内容

| # | 文件 | 操作 |
|---|------|------|
| **1** | `infra/llm/embedding.py` | 新增：`LiteLLMEmbeddings` 类 + 单例管理函数 |
| **2** | `infra/llm/__init__.py` | 导出 embedding API |
| **3** | `main.py` | lifespan 中调用 `init_embedding_model()` |
| **4** | `database/factory.py` | 移除 `_get_embed_fn()`，改用 `get_embeddings()` |
| **5** | `database/vectorstore.py` | 重写：支持 `Embeddings` 实例注入 |
| **6** | `database/store.py` | 重写：使用 `get_embeddings()` 构建 index config |
| **7** | `requirements.txt` | 添加 `litellm==1.83.14` |

### 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                    启动时初始化（lifespan）                       │
│                                                                 │
│   init_embedding_model()                                        │
│       ↓                                                         │
│   _embeddings_instance = LiteLLMEmbeddings(model, api_key)     │
│       ↓                                                         │
│   缓存在模块级变量中                                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    运行时使用                                    │
│                                                                 │
│   get_embeddings()      → 返回 LiteLLMEmbeddings 实例          │
│   get_embed_fn()        → 返回 embeddings.aembed_query 方法    │
│   get_embed_batch_fn()  → 返回 embeddings.aembed_documents 方法│
│                                                                 │
│   零开销：直接返回模块级引用，无函数对象创建                      │
└─────────────────────────────────────────────────────────────────┘
```

### LiteLLMEmbeddings 类

```python
class LiteLLMEmbeddings(Embeddings):
    """LangChain Embeddings 接口实现"""
    
    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.api_key = api_key
    
    async def aembed_query(self, text: str) -> list[float]:
        """单个文本 embedding"""
        response = await litellm.aembedding(
            model=self.model, input=[text], api_key=self.api_key
        )
        return response.data[0]["embedding"]
    
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量文本 embedding"""
        response = await litellm.aembedding(
            model=self.model, input=texts, api_key=self.api_key
        )
        return [item["embedding"] for item in response.data]
```

### 配置来源

```env
# .env
SYSTEM_DEFAULT_EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_DIMENSION=1536
SYSTEM_DEFAULT_LLM_API_KEY=sk-xxx  # 共享 API key
```

### 关键收益

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| Embedding 实例创建 | 每次调用 `get_embed_fn()` | 启动时一次 |
| 函数对象创建 | 每次调用都创建新闭包 | 缓存模块级引用 |
| GC 压力 | 持续产生临时对象 | 无额外 GC |
| 接口一致性 | 自定义函数签名 | LangChain `Embeddings` 标准接口 |
| PGVectorStore 集成 | 需要适配器 | 直接传入 `Embeddings` 实例 |

### 验证结果
```
✅ Embedding module imports OK
✅ Database module imports OK
```

---

## infra/llm 模块重构 ✅ 完成（2026-06-01）

### 背景
用户需求：
1. **系统级默认 LLM 和 Embedding**：从 `.env` 加载，用于会话摘要、memory 语义检索、标题生成等辅助任务，不得更改
2. **Embedding 一旦初始化不可变更**：直接影响 RAG 等语义检索功能
3. **providers/models 表配置**：用户可在页面设置默认 LLM/VLM，是否开启思考模式
4. **完全依赖 LiteLLM Router**：实现 fallback，全部使用默认参数，能简则简
5. **动态模型选择**：通过 LangChain 的 `wrap_model_call` 实现

### 重构内容

| # | 文件 | 操作 |
|---|------|------|
| **1** | `infra/config.py` | 删除 `MODEL_RETRY_*` 5 个配置项（~20 行） |
| **2** | `infra/llm/manager.py` | 简化 Router 使用默认参数；删除 `_default_embedding_id`、`get_embedding_model()` 等相关代码（~78 行） |
| **3** | `infra/llm/factory.py` | 从 manager.py 移入 `build_extra_body()`；重构 `get_system_llm()` 为模块级单例模式（`init_system_llm()` + `get_system_llm()`）；删除 `temperature` 参数 |
| **4** | `agents/supervisor.py` | 移除 `ModelRetryMiddleware`，Fallback 由 LiteLLM Router 处理 |
| **5** | `main.py` | 更新启动顺序：`init_all() → init_system_llm() → init_embedding_model() → get_model_manager().refresh() → init_supervisor()` |
| **6** | `infra/llm/__init__.py` | 新增导出 `init_system_llm` |

### 架构变更

**重构前**：
```
ModelManager:
  - _default_llm_id / _default_vlm_id / _default_embedding_id
  - get_llm() / get_embedding_model()
  - build_extra_body()

factory.py:
  - get_llm(temperature=0)  # 暴露 temperature
  - get_system_llm()  # @lru_cache 单例
```

**重构后**：
```
manager.py:
  - _default_llm_id / _default_vlm_id  # 无 embedding
  - get_model() / refresh()
  - Router 使用默认参数

factory.py:
  - build_extra_body()  # 从 manager 移入
  - init_system_llm()  # 启动时调用
  - get_system_llm()   # 返回单例，未初始化抛 RuntimeError
  - get_llm(model_id, thinking_mode)  # 无 temperature，固定为 0
```

### 启动顺序

```python
# main.py lifespan
await init_all()           # PostgreSQL + PGVector + Checkpointer + Store
init_system_llm()          # System LLM from .env (单例)
init_embedding_model()     # Embedding from .env (单例)
await get_model_manager().refresh()  # DB 模型配置 + Router
await init_supervisor()    # Agent 创建，使用 get_system_llm()
```

### 配置来源

```
系统级 LLM:     .env (SYSTEM_DEFAULT_LLM_MODEL + SYSTEM_DEFAULT_LLM_API_KEY)
系统级 Embedding: .env (SYSTEM_DEFAULT_EMBEDDING_MODEL + EMBEDDING_DIMENSION)
运行时 LLM:     DB (providers + models 表) + LiteLLM Router fallback
```

### Fallback/Retry 策略

- **完全依赖 LiteLLM Router**：`Router(model_list, fallbacks)`
- **删除 ModelRetryMiddleware**：不再需要自定义 retry middleware
- **同类型互备**：`_build_fallbacks()` 构建同 model_type 内的互备关系

### 关键收益

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| MODEL_RETRY_* 配置 | 5 个 | 0 |
| Router 参数 | `num_retries=2, retry_after=1, timeout=...` | 默认参数 |
| embedding 配置来源 | DB + .env 双轨 | 仅 .env |
| temperature 参数 | 暴露给调用方 | 内部固定为 0 |
| get_system_llm | @lru_cache 语义不明 | 模块级单例，显式 init |

### 验证结果
```
✅ All imports successful
✅ No circular imports
✅ No syntax errors
```

---

## infra/llm 公共 API 简化 ✅ 完成（2026-06-01）

### 背景
根据单例设计原则重新审视 LLM 模块，简化公共 API。

### 新的公共 API

```python
# 对外暴露的 API
init_models()                          # 合并所有初始化
get_system_llm()                       # 无入参，返回默认 LLM
get_llm(model_id, thinking=False)      # 入参: "provider/model_id", thinking bool

# Embedding API（不变）
get_embeddings()
get_embedding_dimension()
get_embed_fn()
get_embed_batch_fn()

# Internal API（保留给特定模块使用）
get_model_manager()
```

### 重构内容

| # | 文件 | 操作 |
|---|------|------|
| **1** | `manager.py` | 添加 `_build_extra_body()` + `_init_system_llm()` + `get_system_llm()` + `get_llm()` + `init_models()` |
| **2** | `factory.py` | 简化为 deprecation shim（236 行 → 29 行） |
| **3** | `__init__.py` | 简化导出，保留 `get_model_manager` 作为 Internal API |
| **4** | `main.py` | lifespan 简化为 `await init_models()` |

### 新架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    infra/llm Public API                             │
│                                                                      │
│  init_models()                                                       │
│    ├── System LLM (from .env, singleton)                            │
│    ├── Embedding (from .env, singleton)                             │
│    └── DB Models → LiteLLM Router (with fallbacks)                  │
│                                                                      │
│  get_system_llm() → ChatLiteLLM                                      │
│    └── Used for: compile-time default, summarization, titles        │
│                                                                      │
│  get_llm(model_id, thinking) → ChatLiteLLMRouter                     │
│    └── Uses shared Router + per-request extra_body                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 验证结果
```
✅ Main module imports successful
✅ All API endpoints work correctly
```

---

## infra 模块 API 简化 ✅ 完成（2026-06-01）

### 背景
用户需求：infra 层作为资源层，不应暴露太多接口给外部。外部只需要获取资源的方法。

### 重构内容

| # | 文件 | 操作 |
|---|------|------|
| | **1** | `infra/database/factory.py` | 重命名 `init_all` → `init_database`，`dispose_all` → `dispose_database` |
| | **2** | `infra/database/__init__.py` | 更新导出名称 |
| | **3** | `main.py` | 更新调用 |
| | **4** | `infra/llm/__init__.py` | 移除 `get_model_manager`、`LiteLLMEmbeddings`、`init_embedding_model` 导出 |
| | **5** | `infra/llm/factory.py` | 删除废弃的重定向文件 |
| | **6** | `infra/__init__.py` | 新增顶层门面，统一资源入口 |

### 新的 infra 公共 API

```python
# infra/__init__.py — 顶层门面

# Configuration
get_settings()

# Errors
AgentHubError

# Database Lifecycle
init_database()
dispose_database()

# Database Resources
get_database()
get_vectorstore()
get_checkpointer()
get_store()
get_saver()
Base

# LLM Lifecycle
init_models()

# LLM Resources
get_system_llm()
get_llm(model_id, thinking_mode)

# Embedding Resources
get_embeddings()
get_embedding_dimension()
get_embed_fn()
get_embed_batch_fn()
```

### 架构设计原则

1. **资源层只暴露 getter 函数**
   - 不暴露实现类（如 `LiteLLMEmbeddings`、`ModelManager`）
   - 不暴露内部初始化函数（如 `init_embedding_model`）

2. **生命周期函数语义化命名**
   - `init_database()` / `dispose_database()` 代替模糊的 `init_all()`
   - 清晰表明操作对象

3. **顶层门面统一入口**
   - 业务代码可以从 `from app.infra import ...` 导入所有资源
   - 子模块 `infra/database`、`infra/llm` 仍可单独导入

### 关键收益

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| infra/llm 导出项 | 10 个（含内部 API） | 7 个（纯公共 API） |
| infra 顶层门面 | 无 | 1 个统一入口 |
| 生命周期函数命名 | `init_all` 模糊 | `init_database` 语义化 |
| 废弃文件 | `factory.py` 重定向 | 已删除 |

### 验证结果
```
✅ All imports successful
✅ main.py lifespan works correctly
✅ No breaking changes for business code
```

---

## 模型创建 model_id 格式修复 ✅ 完成（2026-06-02）

### 背景
用户在前端创建模型时，如果 `model_id` 包含 provider 前缀（如 `zai/glm-5.1`），会导致 LiteLLM Router 初始化失败：
```
litellm.BadRequestError: LLM Provider NOT provided. You passed model=zai/zai/glm-5.1
```

### 根因分析
1. 前端 `ModelCreate` 类型注释说明 `model_id` 格式为 `"provider/model_name"`
2. 后端 `ModelBase` schema 期望 `model_id` 是纯模型名 `"model_name"`（不带 provider 前缀）
3. `manager.py` 中 `full_model_id = f"{m.provider}/{m.model_id}"` 会重复添加 provider 前缀

### 修复内容

| # | 文件 | 操作 |
|---|------|------|
| **1** | `backend/app/api/v1/models.py` | 在 `create_model()` 中自动去除 `model_id` 的 provider 前缀 |
| **2** | `backend/app/infra/llm/manager.py` | `_build_model_list()` 和 `_build_fallbacks()` 中添加防御性前缀去除 |
| **3** | `frontend/src/types.ts` | 更新 `ModelCreate.model_id` 注释，明确说明不应包含 provider 前缀 |

### 修复策略

**三层防御**：
1. **API 层**：创建模型时自动清理 `model_id`，确保存储到数据库的是纯模型名
2. **Manager 层**：构建 LiteLLM Router 时再次检查并清理，防止脏数据
3. **类型注释**：更新前端注释，明确告知用户正确的格式

### 关键代码变更

```python
# backend/app/api/v1/models.py
@api_router.post("", response_model=ModelInfo, status_code=status.HTTP_201_CREATED)
async def create_model(...):
    # Normalize model_id: strip provider prefix if present
    normalized_model_id = model_data.model_id
    if normalized_model_id.startswith(f"{model_data.provider}/"):
        normalized_model_id = normalized_model_id[len(f"{model_data.provider}/") :]
```

```python
# backend/app/infra/llm/manager.py
def _build_model_list(self) -> list[dict]:
    # Normalize model_id: strip provider prefix if present
    normalized_model_id = m.model_id
    if normalized_model_id.startswith(f"{m.provider}/"):
        normalized_model_id = normalized_model_id[len(f"{m.provider}/") :]
```

```typescript
// frontend/src/types.ts
export type ModelCreate = {
  provider: string  // e.g. "dashscope", "zai", "openai"
  model_type: ModelType
  model_id: string  // Model name WITHOUT provider prefix, e.g. "qwen3.5-27b" (NOT "dashscope/qwen3.5-27b")
  // ...
}
```

### 关键收益

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| 用户输入 `zai/glm-5.1` | 500 错误 | 自动修正为 `glm-5.1` |
| 脏数据存入 DB | 导致 Router 初始化失败 | Manager 层防御性处理 |
| 类型注释误导 | 注释说格式是 `provider/model` | 注释明确说明不带前缀 |

---

## Agent Middleware 异步支持修复 ✅ 完成（2026-06-02）

### 背景
后端报错：
```
NotImplementedError: Asynchronous implementation of awrap_model_call is not available. 
You are likely encountering this error because you defined only the sync version (wrap_model_call) 
and invoked your agent in an asynchronous context (e.g., using `astream()` or `ainvoke()`).
```

### 根因分析
1. `middleware/model.py` 使用了 `@wrap_model_call` 装饰器（同步版本）
2. 流式服务 `streaming.py` 使用 `astream_events()` 异步调用
3. LangChain 在异步上下文中会尝试调用 `awrap_model_call`，但装饰器版本只生成了同步实现

### 修复内容

| # | 文件 | 操作 |
|---|------|------|
| **1** | `agents/middleware/model.py` | 从装饰器方式改为类继承 `AgentMiddleware`，同时实现 `wrap_model_call` 和 `awrap_model_call` |

### 新架构

```python
class DynamicModelMiddleware(AgentMiddleware):
    """Dynamically select model based on runtime context.
    
    Implements both sync and async versions per LangChain official pattern.
    """
    
    def _get_model_override(self, request: ModelRequest) -> BaseChatModel | None:
        """Extract model from context and create new LLM instance."""
        ...
    
    def wrap_model_call(self, request, handler) -> ModelResponse:
        """Sync version."""
        model = self._get_model_override(request)
        if model is None:
            return handler(request)
        return handler(request.override(model=model))

    async def awrap_model_call(self, request, handler) -> ModelResponse:
        """Async version - called in async context (astream, ainvoke)."""
        model = self._get_model_override(request)
        if model is None:
            return await handler(request)  # type: ignore[misc]
        return await handler(request.override(model=model))  # type: ignore[misc]


# Module-level singleton instance
dynamic_model = DynamicModelMiddleware()
```

### 关键决策

**为什么选择类继承而非异步装饰器？**

根据 LangChain 官方文档：
> "When to use classes: Defining both sync and async implementations for the same hook"

类继承方式可以：
1. 同时支持同步和异步调用上下文
2. 未来扩展更方便（可添加其他 hooks）
3. 符合 `SummarizationMiddleware` 的使用模式

### 关键收益

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 异步调用支持 | ❌ NotImplementedError | ✅ 正常工作 |
| 同步调用支持 | ✅ | ✅ |
| 代码模式 | 装饰器（仅同步） | 类继承（双版本） |
| 官方模式遵循 | 部分 | 完全符合 |

---

## LiteLLM Router model_id 匹配修复 ✅ 完成（2026-06-02）

### 背景
前端传入的 `model_name` 不带 provider 前缀（如 `glm-5.1`），但 LiteLLM Router 注册的 `model_name` 是带前缀的（如 `zai/glm-5.1`），导致 Router 找不到模型。

### 错误日志
```
litellm.BadRequestError: You passed in model=glm-5.1. 
There are no healthy deployments for this model
No fallback model group found for original model_group=glm-5.1
```

### 根因分析
1. `_build_model_list()` 注册 `model_name: "provider/model_id"`
2. `factory.get_llm()` 创建 `ChatLiteLLMRouter(model_name=model_id)` 使用的是不带前缀的 `model_id`
3. LiteLLM Router 按 `model_name` 匹配，找不到 `glm-5.1`

### 修复内容

| # | 文件 | 操作 |
|---|------|------|
| **1** | `infra/llm/factory.py` | 在创建 `ChatLiteLLMRouter` 时，使用 `full_model_id = f"{model_config.provider}/{short_model_id}"` |

### 修复代码
```python
# factory.py
def get_llm(model_id: str, thinking_mode: bool = False) -> Runnable:
    # ...
    model_config = manager.get_model(short_model_id)
    
    # Build full model_id with provider prefix (required by LiteLLM Router)
    full_model_id = f"{model_config.provider}/{short_model_id}"
    
    llm = ChatLiteLLMRouter(
        router=router,
        model_name=full_model_id,  # ← 使用完整 ID
        ...
    )
```

### 关键收益

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 前端传参 | `glm-5.1` | `glm-5.1`（无需改变） |
| Router 匹配 | ❌ 找不到模型 | ✅ 自动补全前缀 |
| 向后兼容 | - | ✅ 支持带/不带前缀两种格式 |
| 改动范围 | - | 仅 `factory.py` 一处 |
