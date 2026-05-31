## 全量更新 TODO.md 内容

以下是完整的 Phase 1-4 计划内容，覆盖从代码清理到 Supervisor StateGraph 迁移的全部步骤。

---

# AgentHub 后端全面重构计划

> **核心原则**: 
> - 简单 SubAgent → `create_agent`（快，够用）
> - 复杂 SubAgent → LangGraph StateGraph（灵活，可控）
> - Supervisor → **LangGraph StateGraph**（手写 agent loop，获得完全掌控）
> - 遵循 LangChain v1 + FastAPI 生产级分层架构

---

## 一、架构决策总览

| Agent 类型 | 引擎 | 原因 |
|-----------|------|------|
| **Supervisor** | LangGraph StateGraph（手写） | 需要自定义 tool loop、超时控制、并行调度、HITL |
| **简单 SubAgent**（chatbot, 简单 RAG） | `create_agent` | 标准 ReAct loop 足够，无需自定义 |
| **复杂 SubAgent**（多步推理、条件路由） | LangGraph StateGraph（手写） | 需要节点级控制 |

**LangChain 官方指导**: *"LangChain's `create_agent` runs on LangGraph. Use LangChain for a fast start; drop to LangGraph for custom orchestration."*

---

## 二、当前问题清单

| # | 优先级 | 问题 | 状态 |
|---|--------|------|------|
| **1** | 🔴 P0 | **`GET /agents` API + `schemas/agent.py`** — 暴露内部细节，违反唯一入口原则 | ✅ 已删除 |
| **2** | 🔴 P0 | **`persist_tokens_and_dag()` 在 `utils/`** — 混合工具函数和业务编排 | ✅ 已迁移到服务层 |
| **3** | 🔴 P0 | **`create_subagent()` 不支持 `store`** — SubAgent 无法访问长期记忆 | ✅ 已增强 |
| **4** | 🔴 P0 | **Supervisor 使用 `create_agent` 黑盒** — 无法自定义 tool loop/超时/HITL | 待迁移 |
| **5** | 🟡 P1 | **模型 fallback 逻辑分散** — `stream_helpers` 和 `conversations` 各自维护 | ✅ 已统一 |
| **6** | 🟡 P1 | **`build_agent_kwargs()` 职责过重** — 参数构建+DB查询+历史+标题 | 待拆分 |
| **7** | 🟢 P2 | **`schemas/interrupt_message.py` 碎片化** — 可合并到 `schemas/chat.py` | ✅ 已整合 |

---

## 三、执行路线图

```
Phase 1 — 代码清理（~1.5h，极低风险）
├── Step 1: 删除 GET /agents API + schemas/agent.py
├── Step 2: 整合 interrupt_message.py → schemas/chat.py
└── Step 3: 统一模型 fallback 入口

Phase 2 — 服务层提取（~3h，中风险）
├── Step 4: 创建 AgentExecutionService → 统一 invoke/stream 持久化
└── Step 5: create_subagent() 支持 store 参数

Phase 3 — 渐进重构（~2h，中风险）
└── Step 6: 拆分 build_agent_kwargs() → ChatService + 纯工具函数

Phase 4 — Supervisor StateGraph 迁移（~5-7天，高风险）
├── Step 7: 新建 agents/graph/ 模块
├── Step 8: 定义 SupervisorState + 实现 llm_node / tool_node / router
├── Step 9: 组装 build_supervisor_graph()
├── Step 10: SupervisorManager 支持 feature flag 双模式切换
├── Step 11: 中间件重构为纯函数（create_agent 和 StateGraph 共享）
├── Step 12: 流式适配 + 超时控制
└── Step 13: 回归测试 + 性能验证
```

---

## 四、Phase 1 — 代码清理 ✅ 已完成 (2025-05-30)

### Step 1: 删除 `GET /agents` API 及关联代码 ✅

**已执行操作**:

| 文件 | 操作 | 状态 |
|------|------|------|
| `backend/app/schemas/agent.py` | **删除整个文件** | ✅ 已删除 |
| `backend/app/api/v1/chat/run.py` | 删除 `from app.schemas.agent import AgentInfo, AgentsResponse` | ✅ 已移除 |
| `backend/app/api/v1/chat/run.py` | 删除 `GET /agents` 端点函数 | ✅ 已移除 |
| 前端代码 | 验证无调用引用 | ✅ 无影响 |

### Step 2: 整合 `interrupt_message.py` → `schemas/chat.py` ✅

| 文件 | 操作 | 状态 |
|------|------|------|
| `backend/app/schemas/chat.py` | 末尾追加 `InterruptMessage` 类 | ✅ 已完成 |
| `backend/app/schemas/__init__.py` | 更新导出路径 | ✅ 已更新 |
| `backend/app/schemas/interrupt_message.py` | **删除** | ✅ 已删除 |

### Step 3: 统一模型 fallback 入口 ✅

| 文件 | 操作 | 状态 |
|------|------|------|
| `backend/app/utils/stream_helpers.py` | 保持 `resolve_model_name()` 作为唯一入口 | ✅ 基准 |
| `backend/app/api/v1/chat/conversations.py` | 新增导入 `resolve_model_name` | ✅ 已更新 |

**Phase 1 改革收益**:
- 消除 1 处死代码端点 + 2 个冗余模块文件
- 减少 `InterruptMessage` 跨模块耦合
- 模型降级逻辑统一到 `resolve_model_name` 单一入口

---

## 五、Phase 2 — 服务层提取 ✅ 已完成 (2025-05-30)

### Step 4: 创建 `AgentExecutionService` ✅

**已执行操作**:

| 文件 | 操作 | 状态 |
|------|------|------|
| `backend/app/services/agent_execution.py` | **新建** — `AgentExecutionService` 类封装 token + DAG 持久化 | ✅ 已创建 |
| `backend/app/services/__init__.py` | 新增 `AgentExecutionService` 导出 | ✅ 已更新 |
| `backend/app/utils/stream_helpers.py` | 删除 `persist_tokens_and_dag()` 函数 | ✅ 已移除 |
| `backend/app/api/v1/chat/run.py` | 改用 `AgentExecutionService(supervisor).persist(...)` | ✅ 已更新 |
| `backend/app/api/v1/chat/_streaming.py` | 改用 `AgentExecutionService(supervisor).persist(...)` | ✅ 已更新 |

### Step 5: `create_subagent()` 支持 `store` 参数 ✅

| 文件 | 操作 | 状态 |
|------|------|------|
| `backend/app/agents/subagents/_base.py` | 新增 `store: BaseStore \| None = None` 参数 | ✅ 已更新 |

**实现**:
```python
def create_subagent(
    name: str,
    *,
    tools: list,
    system_prompt: str,
    store: BaseStore | None = None,  # ← 新增
) -> CompiledStateGraph:
    return create_agent(
        model=get_system_default_llm(),
        tools=tools,
        system_prompt=system_prompt,
        store=store,  # ← 传递给 create_agent
        middleware=[
            make_dynamic_prompt(name, store=store),  # ← 传递给 prompt 中间件
            dynamic_model,
        ],
        context_schema=AgentRuntimeContext,
    )
```

**Phase 2 改革收益**:
- `persist_tokens_and_dag()` 从 `utils/` 迁移到独立服务类
- `AgentExecutionService` 可被 invoke/stream 两路径复用
- `create_subagent()` 支持长期记忆 (`store`) 注入
- 符合 LangChain `create_agent` 最佳实践

---

## 六、Phase 3 — 渐进重构 ✅ 已完成（2026-05-30）

### Step 6: 拆分 `build_agent_kwargs()` → `ChatService` — **已验证无需修改**

经过 LangChain v1 官方文档对照和代码分析，确认当前架构已经符合最佳实践：

#### 验证结论

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

---

## 七、Phase 4 — Supervisor 从 `create_agent` 迁移到 LangGraph StateGraph

### 设计目标

把 Supervisor 从 `create_agent` 黑盒下沉到手写 StateGraph，获得：
- 自定义 tool 调用循环（非标准 ReAct）
- 在 tool call 之间插入审查/校验/降级节点
- 超时控制和优雅降级
- Human-in-the-Loop（审批敏感操作）
- 并行 sub-agent 调度

**简单 SubAgent（chatbot 等）继续使用 `create_agent`，不受影响。**

### Step 7: 新建 `backend/app/agents/graph/` 模块

```
backend/app/agents/graph/
├── __init__.py
├── state.py                 # SupervisorState (TypedDict)
├── supervisor_graph.py      # build_supervisor_graph() 工厂
├── nodes/
│   ├── __init__.py
│   ├── llm_node.py          # LLM 调用节点
│   ├── tool_node.py         # 工具执行节点
│   └── router.py            # 条件路由函数
└── middleware_adapters.py   # 中间件纯函数适配层
```

### Step 8: 定义状态 + 实现核心节点

**`state.py`**:
```python
class SupervisorState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    iteration_count: NotRequired[int]
    tool_call_history: NotRequired[list]
    routing_decision: NotRequired[dict]
```

**`nodes/llm_node.py`** — 在节点内显式调用动态 prompt/model 逻辑：
```python
async def supervisor_llm_node(state: SupervisorState, config: RunnableConfig) -> dict:
    # 1. 动态 prompt
    system_prompt = prompt_service.build_system_prompt("supervisor", timezone=...)
    # 2. 动态 model
    model = resolve_model_from_context(config)
    # 3. 调用 LLM
    response = await model.bind_tools([list_agents, task]).ainvoke(
        [SystemMessage(content=system_prompt)] + state["messages"]
    )
    return {"messages": [response], "iteration_count": state.get("iteration_count", 0) + 1}
```

**`nodes/router.py`**:
```python
def route_after_llm(state: SupervisorState) -> str:
    last_msg = state["messages"][-1]
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        if state.get("iteration_count", 0) >= 25:
            return "end"
        return "tools"
    return "end"
```

### Step 9: 组装 `build_supervisor_graph()`

```python
# supervisor_graph.py
def build_supervisor_graph(
    *, checkpointer: BaseCheckpointSaver, store: BaseStore | None = None
) -> CompiledStateGraph:
    builder = StateGraph(SupervisorState)

    builder.add_node("llm", supervisor_llm_node)
    builder.add_node("tools", ToolNode([list_agents, task]))

    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", route_after_llm, {
        "tools": "tools",
        "end": END,
    })
    builder.add_edge("tools", "llm")

    return builder.compile(checkpointer=checkpointer, store=store)
```

**拓扑图**:
```
START → [llm] ──(有 tool_calls)──→ [tools] ──→ [llm] (循环)
                ──(无 tool_calls)──→ END
```

### Step 10: `SupervisorManager` 支持 feature flag 双模式

```python
# supervisor.py
class SupervisorManager:
    async def init(self, checkpointer, store=None) -> CompiledStateGraph:
        settings = get_settings()
        if settings.SUPERVISOR_ENGINE == "state_graph":
            self._instance = build_supervisor_graph(
                checkpointer=checkpointer, store=store
            )
        else:
            self._instance = create_agent(...)  # 现有逻辑
        return self._instance
```

通过环境变量 `SUPERVISOR_ENGINE=state_graph` 灰度切换，可随时回退。

### Step 11: 中间件重构为纯函数

将 `@wrap_model_call` 和 `@dynamic_prompt` 的核心逻辑提取为纯函数：

```python
# middleware_adapters.py
def resolve_model_from_context(context) -> BaseChatModel: ...
def resolve_system_prompt(agent_id: str, context) -> str: ...
```

- `create_agent` 路径：装饰器内部调用纯函数（行为不变）
- StateGraph 路径：节点内直接调用纯函数

### Step 12: 流式适配 + 超时控制

**流式**: 保持 SSE event 格式不变，`graph.astream()` 输出与 `create_agent` 兼容。

**超时**: 在 `llm_node` 和 `tool_node` 中加 `asyncio.wait_for`，超时后走降级路径。

### Step 13: 回归测试 + 性能验证

- 单元测试：llm_node / router / tool_node
- 集成测试：完整 supervisor flow（invoke + stream）
- 性能基准：Locust 压测 P50/P95/P99，确保不退化
- A/B 对比：`create_agent` vs `StateGraph` 行为一致性

---

## 八、最终项目目录架构

```
backend/app/
│
├── main.py                              # FastAPI app + lifespan
│
├── agents/                              # Agent 定义层
│   ├── __init__.py                      # 导出 get_supervisor()
│   ├── context.py                       # AgentRuntimeContext (dataclass)
│   ├── supervisor.py                    # SupervisorManager（支持 feature flag 双模式）
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── model.py                     # @wrap_model_call dynamic_model（装饰器）
│   │   └── prompt.py                    # @dynamic_prompt + PromptService
│   ├── graph/                           # ★ Phase 4 新增：手写 StateGraph
│   │   ├── __init__.py
│   │   ├── state.py                     # SupervisorState (TypedDict)
│   │   ├── supervisor_graph.py          # build_supervisor_graph() 工厂
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── llm_node.py              # LLM 调用节点
│   │   │   ├── tool_node.py             # 工具执行节点
│   │   │   └── router.py                # 条件路由
│   │   └── middleware_adapters.py       # ★ 中间件纯函数适配层
│   ├── schemas/
│   │   └── routing.py                   # RoutingDecision
│   └── subagents/
│       ├── __init__.py
│       ├── _base.py                     # create_subagent()（简单 SubAgent 工厂，支持 store）
│       └── chatbot.py                   # 简单 chatbot SubAgent（create_agent）
│       # 未来可加:
│       # └── rag_agent.py               # 复杂 RAG SubAgent（StateGraph 手写）
│
├── core/
│   └── agent_registry.py                # AgentRegistry（Single Dispatch Tool 模式）
│
├── api/
│   ├── errors.py                        # 全局异常 handler
│   └── v1/
│       ├── __init__.py
│       ├── dependencies.py
│       └── chat/
│           ├── run.py                   # POST /invoke, POST /stream
│           ├── _streaming.py            # ChatStreamingService
│           ├── conversations.py         # CRUD + title + thinking-mode
│           ├── history.py
│           └── stats.py
│       ├── models.py
│       └── traces.py
│
├── services/                            # ★ 业务服务层
│   ├── __init__.py
│   ├── agent_execution.py               # ★ AgentExecutionService（统一持久化）
│   ├── chat_service.py                  # ★ ChatService（对话生命周期编排）
│   ├── checkpoint.py                    # CheckpointReader
│   ├── trace.py                         # TraceBuilder
│   ├── dag.py                           # DagBuilder
│   └── parsers.py                       # 纯解析工具
│
├── schemas/                             # Pydantic v2 DTO
│   ├── chat.py                          # UserInput, ChatMessage, Conversation, InterruptMessage
│   ├── model.py                         # ModelCreate, ModelUpdate
│   ├── provider.py
│   └── trace.py                         # CheckpointInfo, StepOutput, ExecutionDag
│   # ❌ 已删除: agent.py, interrupt_message.py
│
├── crud/                                # SQLAlchemy CRUD（纯数据访问）
│   ├── chat.py
│   ├── model.py
│   ├── provider.py
│   └── trace.py
│
├── models/                              # SQLAlchemy ORM
│   ├── base.py
│   ├── chat.py
│   ├── model.py
│   ├── provider.py
│   └── trace.py
│
├── infra/                               # 基础设施
│   ├── config.py                        # Settings (pydantic-settings)
│   ├── errors.py
│   ├── database/
│   │   ├── factory.py
│   │   └── postgres/
│   │       ├── vectorstore.py
│   │       ├── checkpointer.py
│   │       └── store.py
│   ├── llm/
│   │   ├── model_manager.py
│   │   └── system.py
│   └── tools/
│       ├── time.py
│       └── web.py
│
├── prompts/                             # 提示词模板（.md 文件）
│   ├── supervisor.md
│   └── chatbot.md
│
├── scripts/                             # 运维脚本
└── tests/                               # 测试
```

---

## 九、分层职责总结

```
┌─────────────────────────────────────────────────────┐
│  API Layer (api/v1/)                                 │
│  HTTP 请求解析、响应格式、SSE 流、权限校验              │
│  → 调用 services，不包含业务逻辑                      │
├─────────────────────────────────────────────────────┤
│  Service Layer (services/)       ★ 本次重构核心      │
│  AgentExecutionService: 持久化 + DAG 快照             │
│  ChatService: 对话生命周期（创建/历史/标题）           │
│  CheckpointReader / TraceBuilder / DagBuilder         │
│  → 编排多个 crud/agents，不依赖 FastAPI               │
├─────────────────────────────────────────────────────┤
│  Agent Layer (agents/)                                │
│  Supervisor: StateGraph 手写 / create_agent（灰度）    │
│  SubAgents: create_agent 工厂 / StateGraph 手写       │
│  Middleware: 模型选择、动态提示词（纯函数+装饰器）      │
│  AgentRegistry: 单例注册表 + list_agents/task 工具     │
├─────────────────────────────────────────────────────┤
│  Domain Layer (crud/ + models/ + schemas/)            │
│  SQLAlchemy ORM + Pydantic DTO + 纯数据访问           │
│  零业务逻辑，零 FastAPI 依赖                           │
├─────────────────────────────────────────────────────┤
│  Infra Layer (infra/)                                 │
│  数据库连接、LLM 管理、配置、外部工具                   │
└─────────────────────────────────────────────────────┘
```

---

## 十、Phase 4 拓扑图详解

```
                    ┌──────────┐
                    │   START  │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
         ┌─────────│   LLM    │◄──────────────────────┐
         │         └────┬─────┘                       │
         │              │                             │
         │     route_after_llm                        │
         │      ╱         ╲                          │
         │     ╱           ╲                          │
         │    ▼             ▼                         │
         │ ┌──────┐     ┌─────┐                       │
         │ │tools │     │ END │                       │
         │ └──┬───┘     └─────┘                       │
         │    │                                       │
         └────┘                                       │
                                                      
    未来可扩展为:
    
                    ┌──────────┐
                    │   START  │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
         ┌─────────│   LLM    │◄──────────────────────┐
         │         └────┬─────┘                       │
         │              │                             │
         │     route_after_llm                        │
         │      ╱    │    ╲                           │
         │     ╱     │     ╲                          │
         │    ▼      ▼      ▼                         │
         │ ┌──────┐┌──────┐┌─────┐                    │
         │ │review││tools ││ END │                    │
         │ └──┬───┘└──┬───┘└─────┘                    │
         │    │       │                               │
         │    │  ┌────▼────┐                          │
         │    │  │ timeout │                          │
         │    │  │ handler │                          │
         │    │  └────┬────┘                          │
         │    │       │                               │
         │    └───┬───┘                               │
         │        │                                   │
         └────────┘                                   
```

---

## 十一、实施顺序与风险矩阵

| Phase | 步骤 | 预计工时 | 风险 | 依赖 | 可并行？ |
|-------|------|---------|------|------|---------|
| **P1** | Step 1: 删除 GET /agents | 0.5h | 极低 | 无 | ✅ |
| **P1** | Step 2: 整合 interrupt_message | 0.5h | 极低 | 无 | ✅ |
| **P1** | Step 3: 统一 model fallback | 0.5h | 低 | 无 | ✅ |
| **P2** | Step 4: AgentExecutionService | 2h | 中 | P1 | ❌ |
| **P2** | Step 5: store 参数 | 1h | 中 | P2:Step4 | ❌ |
| **P3** | Step 6: ChatService | 2h | 中 | P2 | ❌ |
| **P4** | Step 7: 新建 graph/ 模块 | 1h | 低 | 无 | ✅ (独立) |
| **P4** | Step 8: State + 核心节点 | 2h | 中 | Step 7 | ❌ |
| **P4** | Step 9: 组装 graph | 0.5h | 中 | Step 8 | ❌ |
| **P4** | Step 10: Feature flag | 1h | 中 | Step 9 | ❌ |
| **P4** | Step 11: 中间件纯函数 | 1.5h | 高 | Step 10 | ❌ |
| **P4** | Step 12: 流式适配 | 1h | 高 | Step 10 | ❌ |
| **P4** | Step 13: 测试 + 压测 | 1.5h | 高 | Step 12 | ❌ |

**总计**: ~15h（P1-P3 ~6.5h, P4 ~8.5h）

**执行策略**: P1 可一天内全部完成。P2-P3 逐步推进。P4 独立于 P1-P3，可在任何阶段启动。

---

## 十二、配置文件变更

### `backend/.env` 新增变量

```bash
# Phase 4: Supervisor 引擎选择
# "create_agent" (默认, 当前行为) | "state_graph" (手写 LangGraph)
SUPERVISOR_ENGINE=create_agent
```

### `backend/app/infra/config.py` 新增字段

```python
class Settings(BaseSettings):
    # ... 现有字段 ...
    
    # Phase 4: Supervisor engine
    SUPERVISOR_ENGINE: Literal["create_agent", "state_graph"] = "create_agent"
```

---

## 十三、验收标准

### Phase 1-3 验收
- [x] `GET /agents` 端点已删除，前端无调用报错 ✅ (Phase 1)
- [x] `schemas/agent.py` 和 `schemas/interrupt_message.py` 已删除 ✅ (Phase 1)
- [x] 模型 fallback 逻辑统一到 `resolve_model_name()` ✅ (Phase 1)
- [x] `persist_tokens_and_dag()` 已从 `utils/` 移出 ✅ (Phase 2)
- [x] `AgentExecutionService.persist()` 可被 invoke 和 stream 两路径复用 ✅ (Phase 2)
- [ ] `ChatService.prepare_agent_input()` 承载对话生命周期 (Phase 3)
- [x] `create_subagent()` 接受 `store` 参数 ✅ (Phase 2)

### Phase 4 验收
- [ ] `SUPERVISOR_ENGINE=create_agent` 时行为与重构前完全一致
- [ ] `SUPERVISOR_ENGINE=state_graph` 时功能正常（invoke + stream）
- [ ] SSE 流式格式与前端兼容
- [ ] 超时后优雅降级，不丢连接
- [ ] Locust 压测 P95 < 当前基准 +10%
- [ ] `create_agent` → `state_graph` 一键回退