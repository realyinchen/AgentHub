# AgentHub Multi-Agent 架构演进路线图

> **版本**: 1.2.0  
> **更新日期**: 2026-05-27  
> **参考标准**: LangChain v1.3 + LangGraph v1.2 官方生产最佳实践（MCP 验证）  
> **核心原则**: 严格遵循「Single Agent → Multi-Agent」自然演进路径，不跳步，每次只做一个小阶段改进  
> **当前进度**: Stage 0 ✅ 完成 → Stage 1 进行中

---

## 一、当前状态与核心问题

**当前架构**: Supervisor + 1 Subagent（`chatbot`），骨架是 Multi-Agent，实质仍是 Single Agent。

### 已具备的能力（保持）
- ✅ `create_agent()` 高层 API + `PostgresSaver` Checkpoint + `PostgresStore` 长期记忆
- ✅ `AgentRuntimeContext` 通过 `context_schema` 自动注入
- ✅ `dynamic_model` middleware（LiteLLM Router 内置 fallback + retry）
- ✅ `SummarizationMiddleware`（`trigger=("tokens", 4000)`, `keep=("messages", 20)`）
- ✅ Agent Registry（`register()` + `list_agents()` + `task()`）自动发现模式
- ✅ Tool 不可用时 Graceful Degradation
- ✅ SSE 流式响应 + Trace 追踪

### 核心问题清单（Stage 0 修复后状态）

| # | 问题 | 影响 | 紧急度 | 状态 |
|---|---|---|---|---|
| 1 | **Tool Calling 无重试/超时** — `task()` 调用 Subagent 失败直接抛给用户 | 网络抖动 → 请求失败 | 🔴 P0 | ✅ 已修复 |
| 2 | **无请求级超时控制** — Agent 可能无限阻塞 | 连接池耗尽 | 🔴 P0 | ✅ 已修复 |
| 3 | **路由决策无结构化约束** — Supervisor 可能跳过路由直接自由回复 | 路由不可靠 | 🟡 P1 | ✅ 已修复 |
| 4 | **无分类错误处理** — 仅基础 try/except | 无法区分错误类型 | 🟡 P1 | ✅ 已修复 |
| 5 | **缺少 Request ID 关联** — 日志无请求级追踪 | 问题定位困难 | 🟡 P1 | ✅ 已修复 |
| 6 | **日志无 JSON 格式** | 不利于日志采集 | 🟢 P2 | ✅ 已修复 |
| 7 | **仅有 1 个 Subagent** — `chatbot` 无工具 | Multi-Agent 形同虚设 | 🟢 P2 |
| 8 | **无 Metrics/分布式追踪** | 线上问题定位困难 | 🟢 P2 |
| 9 | **Subagent 调用无追踪** — `task()` 耗时/成功/失败未记录 | 可观测性缺失 | 🟢 P2 |
| 10 | **Prompt 无版本管理** | 变更无法回滚 | 🟢 P2 |

---

## 二、演进总览

```
当前: Stage 0 ✅ 完成 (2026-05-27) ─── 6 项缺陷已修复
  │
  ▼
Stage 1: 单 Agent 强化 (1.5 周) ─── 补齐稳定性短板（重试/超时/结构化输出/错误分类）
  │
  ▼
Stage 2: 智能路由 Router (1.5 周) ─── 引入意图分类 + 2 个新 Subagent
  │
  ▼
Stage 3: Supervisor + 5 Subagents (1.5 周) ─── 多 Agent 扩展 + 健康检查
  │
  ▼
Stage 4: LangGraph 基础工作流 (2 周) ─── State Machine 化
  │
  ▼
Stage 5: 高级 Multi-Agent 特性 (2 周) ─── Memory/并行/Critic
  │
  ▼
Stage 6: 生产级 Multi-Agent 系统 (2.5 周) ─── 全量生产就绪
```

### 统计

| 阶段 | TODO 数 | P0 | P1 | P2 | 工作量 |
|---|---|---|---|---|---|
| Stage 0（立即修复）✅ | 6 | 2 | 3 | 1 | ~1.5 周（已完成） |
| Stage 1（单 Agent 强化） | 10 | 3 | 4 | 3 | ~1.5 周 |
| Stage 2（智能路由） | 6 | 3 | 3 | 0 | ~1.5 周 |
| Stage 3（Subagent 扩展） | 6 | 2 | 2 | 2 | ~1.5 周 |
| Stage 4（LangGraph 工作流） | 5 | 3 | 1 | 1 | ~2 周 |
| Stage 5（高级特性） | 5 | 2 | 2 | 1 | ~2 周 |
| Stage 6（生产就绪） | 12 | 8 | 4 | 0 | ~2.5 周 |
| **合计** | **50** | **23** | **19** | **8** | **~12 周** |

---

## 三、Stage 0 — 当前已知缺陷（✅ 已完成 — 2026-05-27）

> 所有 6 项缺陷已修复，均通过配置开关控制，可独立回滚。

| # | TODO | 模块 | 优先级 | 状态 | 实现要点 |
|---|---|---|---|---|---|
| T01 | **Tool Calling 重试与超时** | `supervisor.py` | 🔴 P0 | ✅ | `ToolRetryMiddleware(max_retries=3, tools=["task"], backoff_factor=2.0, on_failure="continue")` — 开关 `TOOL_RETRY_ENABLED` |
| T02 | **请求级超时控制** | `api/v1/chat.py`, `stream.py` | 🔴 P0 | ✅ | `asyncio.timeout(invoke=120s, stream=300s)` — 开关 `AGENT_INVOKE_TIMEOUT` / `AGENT_STREAM_TIMEOUT`（设 0 关闭） |
| T03 | **Structured Output 路由约束** | `supervisor.py`, `agents/schemas/routing.py` | 🟡 P1 | ✅ | `RoutingDecision` Pydantic Schema → `state["structured_response"]` — 开关 `USE_STRUCTURED_OUTPUT`（默认 false） |
| T04 | **分类错误处理** | `infra/errors.py`, `api/errors.py` | 🟡 P1 | ✅ | `AgentHubError` → `AgentTimeoutError` / `LLMError` / `ToolError` → HTTP 502/504/500 映射 |
| T05 | **Request ID 关联** | `utils/request_handler.py`, `utils/logging.py` | 🟡 P1 | ✅ | `contextvars` UUID7 + `RequestIdFilter` 自动注入所有日志 |
| T06 | **JSON 结构化日志** | `run_backend.py`, `utils/logging.py` | 🟢 P2 | ✅ | `JsonFormatter`（stdlib json，零依赖），`LOG_FORMAT=json` 启用 |

### Stage 0 交付物

| 文件 | 操作 | 说明 |
|---|---|---|
| `app/infra/config.py` | 修改 | 新增 `TOOL_RETRY_ENABLED`, `AGENT_INVOKE_TIMEOUT`, `AGENT_STREAM_TIMEOUT`, `USE_STRUCTURED_OUTPUT` |
| `app/agents/supervisor.py` | 修改 | 条件启用 `ToolRetryMiddleware` + `response_format=RoutingDecision` |
| `app/api/v1/chat.py` | 修改 | `asyncio.timeout` + `structured_response` 日志读取 |
| `app/api/v1/stream.py` | 修改 | `asyncio.timeout` + `structured_response` 日志读取 |
| `app/agents/schemas/routing.py` | **新增** | `RoutingDecision(BaseModel)` |
| `app/infra/errors.py` | **新增** | 领域错误层次 (`AgentHubError` → `LLMError` / `ToolError` / `AgentTimeoutError`) |
| `app/api/errors.py` | **新增** | HTTP 状态码映射 (502/504/500) + SSE 错误格式化 + `agent_hub_error_handler` |
| `app/utils/logging.py` | 修改 | `RequestIdFilter` + `JsonFormatter` |
| `app/utils/request_handler.py` | 修改 | `request_id` contextvar (UUID7) |
| `run_backend.py` | 修改 | `LOG_FORMAT` 环境变量支持 JSON 日志 |
| `.env.example` | 修改 | 新增配置项文档 |

### Stage 0 MCP 验证记录

| 验证项 | 结果 | 来源 |
|---|---|---|
| `ToolRetryMiddleware` 仅对 `task` 工具重试 | ✅ "Scope to specific tools" | [LangChain Middleware 文档](https://docs.langchain.com/oss/python/langchain/middleware/built-in) |
| `response_format` 输出在 `state["structured_response"]` | ✅ 官方确认键名 | [LangChain Structured Output 文档](https://docs.langchain.com/oss/python/langchain/structured-output) |
| 错误分类层次（瞬态重试/LLM可恢复/暂停） | ✅ "Not all errors handled same way" | [Deep Agents Going to Production](https://docs.langchain.com/oss/python/deepagents/going-to-production) |
| 中间件顺序（前处理→模型选择→重试→后处理） | ✅ 官方建议顺序 | [LangChain Middleware 文档](https://docs.langchain.com/oss/python/langchain/middleware/built-in) |

---

## 四、Stage 1 — 单 Agent 强化

> **目标**: 在不改变架构前提下，补齐核心稳定性短板。  
> **原则**: 零 API 破坏，所有改动通过配置开关控制。  
> **注意**: T10-T15 已在 Stage 0 提前实现，T07 与 Stage 0 T01 重合（`ToolRetryMiddleware` 已部署）。实际剩余工作：T08, T09, T16。

| # | TODO | 模块 | 优先级 | 工作量 | 回滚方式 | 状态 |
|---|---|---|---|---|---|---|
| T07 | **引入 `ToolRetryMiddleware`** — 仅对 `task` 工具配置重试（`list_agents` 是纯内存操作不需要重试） | `supervisor.py` | 🔴 P0 | 2 天 | `TOOL_RETRY_ENABLED=false` | ✅ Stage 0 已完成 |
| T08 | **引入 `ModelRetryMiddleware`** — LLM 调用失败自动重试（**注**: LiteLLM Router 已有 fallback+retry，此项为补充增强） | `middleware/model.py` | 🟡 P1 | 1 天 | `MODEL_RETRY_ENABLED=false` | 🔜 待实现 |
| T09 | **LLM 调用超时配置** — LiteLLM Router 层添加 `timeout=60` | `infra/llm.py` / `config.py` | 🔴 P0 | 1 天 | 配置项调大或设 0 | 🔜 待实现 |
| T10 | **API 层 `asyncio.timeout`** — 请求级 120s / 流式 300s | `api/v1/chat.py` / `stream.py` | 🔴 P0 | 1 天 | `AGENT_INVOKE_TIMEOUT=0` / `AGENT_STREAM_TIMEOUT=0` | ✅ Stage 0 已完成 |
| T11 | **Structured Output 约束路由** — `response_format=RoutingDecision`，输出在 `structured_response` 键中 | `supervisor.py` / `agents/schemas/routing.py` | 🟡 P1 | 2 天 | `USE_STRUCTURED_OUTPUT=false` | ✅ Stage 0 已完成 |
| T12 | **分类异常定义** — `AgentError` / `LLMError` / `ToolError` / `AgentTimeoutError` | `infra/errors.py` | 🟡 P1 | 1 天 | — | ✅ Stage 0 已完成 |
| T13 | **分类 HTTP 状态码映射** — 502(LLM) / 504(Timeout) / 500 | `api/errors.py` | 🟡 P1 | 0.5 天 | — | ✅ Stage 0 已完成 |
| T14 | **Request ID 中间件** — 每个请求生成唯一 ID 贯穿日志 | `utils/request_handler.py`, `utils/logging.py` | 🟢 P2 | 0.5 天 | — | ✅ Stage 0 已完成 |
| T15 | **JSON 结构化日志** — `JsonFormatter` (stdlib json, 零依赖) | `run_backend.py`, `utils/logging.py` | 🟢 P2 | 0.5 天 | `LOG_FORMAT=text` | ✅ Stage 0 已完成 |
| T16 | **Prompt 版本管理** — Prompt 模板版本化与回滚 | `prompts/` / `middleware/prompt.py` | 🟢 P2 | 1 天 | — | 🔜 待实现 |

### Stage 1 关键实现细节

#### 中间件顺序（经 MCP 官方文档验证）

```python
middleware = [
    make_dynamic_prompt("supervisor", store=store),  # 1. 前处理：动态 Prompt
    dynamic_model,                                     # 2. 模型选择
    ToolRetryMiddleware(                               # 3. 工具重试（仅 task）
        max_retries=3,
        backoff_factor=2.0,
        initial_delay=1.0,
        tools=["task"],                                # 仅重试 task 工具
        retry_on=(ConnectionError, TimeoutError),
        on_failure="continue",
    ),
    SummarizationMiddleware(...),                      # 4. 后处理：摘要
]
```

**依据**: LangChain 官方建议 "Scope ToolRetryMiddleware to specific tools rather than retrying everything. A filesystem read_file that fails won't benefit from a retry, but a web search that times out probably will."

#### Structured Output

```python
class RoutingDecision(BaseModel):
    action: Literal["route_to_subagent", "direct_reply"]
    target_agent: str | None = None
    reasoning: str

supervisor = create_agent(
    ...,
    response_format=RoutingDecision,  # 输出在 state["structured_response"]
)
```

**注意**: API 层需同时读取 `structured_response` 键获取路由决策。

#### LiteLLM Router 已有容错（影响 T08 优先级）

当前 `dynamic_model` middleware 通过 LiteLLM Router (`get_llm()`) 已内置 fallback + retry，因此 `ModelRetryMiddleware` 降为 P1 补充增强。

---

## 五、Stage 2 — 智能路由 Router

> **目标**: 引入显式 Classifier/Router 层，根据意图分发到专业 Subagent。  
> **前置条件**: Stage 1 完成。

| # | TODO | 模块 | 优先级 | 工作量 |
|---|---|---|---|---|
| T17 | **意图分类器（Classifier）** — 轻量模型（`gpt-4o-mini`）快速判断意图 | 新增 `agents/router/classifier.py` | 🔴 P0 | 2 天 |
| T18 | **路由分发器（Dispatcher）** — 基于分类结果选择处理路径，置信度 < 0.8 回退 Supervisor | 新增 `agents/router/dispatcher.py` | 🔴 P0 | 1 天 |
| T19 | **特性开关** — `features.router_enabled` 配置，默认关闭 | `config.py` / `api/v1/chat.py` | 🔴 P0 | 0.5 天 |
| T20 | **新增 SearchAgent** — 挂载 Tavily + VectorStore 工具 | 新增 `subagents/search_agent.py` | 🟡 P1 | 2 天 |
| T21 | **新增 CodeAgent** — 挂载 Shell + FileSystem 工具 | 新增 `subagents/code_agent.py` | 🟡 P1 | 2 天 |
| T22 | **Subagent 注册新 Agent** — Registry 中注册 Search/Code Agent | `subagents/registry.py` | 🟡 P1 | 0.5 天 |

**路由架构**:
```
用户请求 → Classifier (轻量 LLM) → Chat / Search / Code / Fallback(Supervisor)
```

**风险控制**: 低置信度回退 Supervisor；特性开关默认关闭；每个 Subagent 独立部署。

---

## 六、Stage 3 — Supervisor + Subagents 最小化

> **目标**: 扩展到 5 个 Subagent，完善健康检查和调用追踪。  
> **前置条件**: Stage 2 完成。

| # | TODO | 模块 | 优先级 | 工作量 |
|---|---|---|---|---|
| T23 | **Subagent 扩展到 5 个** — Chat / Search / Code / Data / RAG | 新增 4 个 `subagents/*.py` | 🔴 P0 | 3 天 |
| T24 | **Supervisor Prompt 更新** — 描述全部 5 个 Subagent 的能力边界 | `prompts/supervisor.md` | 🔴 P0 | 1 天 |
| T25 | **工具归属清晰化** — 每个 Subagent 有明确 Tool 边界定义 | `subagents/registry.py` | 🟡 P1 | 1 天 |
| T26 | **Subagent 健康检查** — 运行时检测可用性，失败时 Graceful Degradation | `subagents/registry.py` | 🟡 P1 | 1 天 |
| T27 | **Subagent 调用追踪** — 记录每次 `task()` 的耗时、成功/失败 | `subagents/registry.py` | 🟢 P2 | 1 天 |
| T28 | **Subagent 并发限制** — 配置 Semaphore 防止 LLM 配额耗尽 | `subagents/registry.py` | 🟢 P2 | 0.5 天 |

---

## 七、Stage 4 — LangGraph 基础工作流

> **目标**: 将隐式 ReAct 循环重构为显式 StateGraph。  
> **前置条件**: Stage 3 完成。

| # | TODO | 模块 | 优先级 | 工作量 |
|---|---|---|---|---|
| T29 | **自定义 StateGraph** — 显式定义节点和边替代 `create_agent` | 新增 `agents/graphs/supervisor_graph.py` | 🔴 P0 | 3 天 |
| T30 | **Conditional Edge 路由** — LangGraph 条件边替代 LLM 自由决策 | 新增 `agents/graphs/nodes/route.py` | 🔴 P0 | 1 天 |
| T31 | **Checkpoint 兼容性保证** — 新 StateGraph 复用旧 Checkpointer，旧对话不丢失 | `supervisor.py` / `graphs/` | 🔴 P0 | 1 天 |
| T32 | **工作流可视化** — 生成 Agent 执行 DAG 图 | `graphs/` / Trace 系统 | 🟡 P1 | 1 天 |
| T33 | **Human-in-the-Loop 节点** — 关键决策需人工确认 | 新增 `graphs/nodes/human_approval.py` | 🟢 P2 | 2 天 |

**回滚**: 保留 `create_agent` 作为 fallback，通过 `use_custom_graph` 配置切换。

---

## 八、Stage 5 — 高级 Multi-Agent 特性

> **目标**: 分层 Memory、结构化通信、并行执行、Critic。  
> **前置条件**: Stage 4 完成。

| # | TODO | 模块 | 优先级 | 工作量 |
|---|---|---|---|---|
| T34 | **分层 Memory 管理器** — 短期(Checkpoint) / 长期(Store) / 摘要 三层统一管理 | 新增 `agents/memory/manager.py` | 🔴 P0 | 2 天 |
| T35 | **结构化 Agent 间通信** — TypedDict 约束 Subagent 输入输出 | 新增 `agents/communication/protocol.py` | 🔴 P0 | 1 天 |
| T36 | **并行执行** — `asyncio.gather` 执行无依赖 Subagent（Semaphore 限流） | `graphs/supervisor_graph.py` | 🟡 P1 | 2 天 |
| T37 | **Critic Agent** — 对 Subagent 输出质量进行审查（轻量模型，异步） | 新增 `agents/critic/quality_check.py` | 🟡 P1 | 2 天 |
| T38 | **Agent 动态编排** — 根据任务复杂度动态选择编排策略 | `graphs/` | 🟢 P2 | 3 天 |

---

## 九、Stage 6 — 生产级 Multi-Agent 系统

> **目标**: 全量生产就绪（Observability + Guardrails + Fault Tolerance + Multi-Tenancy）。  
> **前置条件**: Stage 5 完成。

| # | TODO | 模块 | 优先级 | 工作量 |
|---|---|---|---|---|
| T39 | **OpenTelemetry 集成** — 分布式追踪（Traces → Jaeger） | 新增 `infra/observability.py` | 🔴 P0 | 2 天 |
| T40 | **Prometheus Metrics** — 延迟/错误率/Token 用量 | 新增 `/metrics` 端点 | 🔴 P0 | 1 天 |
| T41 | **Grafana Dashboard** — 预置监控面板 | `docker-compose.yml` | 🔴 P0 | 1 天 |
| T42 | **输入 Guardrails** — PII 检测、敏感词过滤 | 新增 `infra/guardrails/safety.py` | 🔴 P0 | 2 天 |
| T43 | **输出 Guardrails** — 内容安全审查 | 新增 `infra/guardrails/pii.py` | 🔴 P0 | 1 天 |
| T44 | **熔断器（Circuit Breaker）** — LLM 调用熔断保护 | 新增 `infra/fault_tolerance.py` | 🔴 P0 | 1 天 |
| T45 | **降级策略** — 主模型不可用时自动切换备用模型 | `infra/fault_tolerance.py` | 🔴 P0 | 1 天 |
| T46 | **限流（Rate Limiting）** — 用户/API Key 级别限流 | `api/deps.py` / `middleware/` | 🔴 P0 | 1 天 |
| T47 | **Multi-Tenancy** — 租户隔离，资源配额 | `api/deps.py` / `config.py` | 🟡 P1 | 3 天 |
| T48 | **Token 预算管理** — 按租户/会话限制 Token 消耗 | 新增 `infra/cost_control.py` | 🟡 P1 | 2 天 |
| T49 | **模型降级策略** — Token 预算耗尽时自动降级到轻量模型 | `infra/cost_control.py` | 🟡 P1 | 1 天 |
| T50 | **SLA 保障** — 99.9% 可用性，p99 < 5s 目标 | 全系统 | 🟡 P1 | 持续 |

---

## 十、行动计划

### 已完成

| 阶段 | 日期 | TODO | 说明 |
|---|---|---|---|
| Stage 0 | 2026-05-27 | T01-T06 全部完成 | ToolRetryMiddleware + asyncio.timeout + Structured Output + 错误分类 + Request ID + JSON 日志 |

### 下一步（Stage 1）

| 周次 | 改进点 | 阶段 | 优先级 | 预计时间 |
|---|---|---|---|---|
| Week 1 | T07 + T08 + T09: Tool/Model 重试增强 + LLM 超时 | Stage 1 | 🔴 P0 | 3-4 天 |
| Week 2 | T10 + T12 + T13 + T14 + T15: 请求超时 + 错误分类 + Request ID + JSON 日志 | Stage 1 | 🔴 P0/🟡 P1 | 2-3 天 |
| Week 3 | T11 + T16: Structured Output + Prompt 版本管理 | Stage 1 | 🟡 P1/🟢 P2 | 2-3 天 |

> **注**: Stage 0 已将 Stage 1 的 T10/T11/T12/T13/T14/T15 提前实现。实际 Stage 1 剩余工作仅 T07/T08/T09/T16。

---

## 附录 A: 回滚策略

| 改动 | 回滚方式 | 默认值 |
|---|---|---|
| ToolRetryMiddleware | `TOOL_RETRY_ENABLED=false` | `true` |
| 请求级超时 (invoke) | `AGENT_INVOKE_TIMEOUT=0` | `120.0` |
| 请求级超时 (stream) | `AGENT_STREAM_TIMEOUT=0` | `300.0` |
| Structured Output | `USE_STRUCTURED_OUTPUT=false` | `false` |
| JSON 日志 | `LOG_FORMAT=text` | `text` |
| Router 特性 | `features.router_enabled=false` |
| 自定义 StateGraph | `use_custom_graph=false`（回退 `create_agent`） |

## 附录 B: MCP 验证的关键发现

1. **`response_format` 输出位置**: `create_agent` 的结构化输出被捕获在 `state["structured_response"]` 键中，API 层需同时读取此键。
2. **`ToolRetryMiddleware` 按工具粒度配置**: 官方建议 "Scope ToolRetryMiddleware to specific tools" — 仅对 `task` 工具重试，`list_agents` 不需要。
3. **LiteLLM Router 已有容错**: 当前 `dynamic_model` middleware 通过 LiteLLM Router 已内置 fallback + retry，`ModelRetryMiddleware` 降为 P1 补充。
4. **中间件顺序**: 前处理（Prompt）→ 模型选择 → 重试 → 后处理（Summarization）。

## 附录 C: 关键参考文档

- [LangChain create_agent 文档](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain Structured Output 文档](https://docs.langchain.com/oss/python/langchain/structured-output)
- [LangGraph Fault Tolerance 文档](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
- [LangChain Deep Agents 生产实践](https://docs.langchain.com/oss/python/deepagents/going-to-production)
- [LangChain Middleware 内置文档](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
