# Active Context

## Current Focus

**修复 SSE 流式响应批量到达问题** (June 3, 2026)

### 问题
前端调用 `/api/v1/chat/stream` 时，SSE 事件不是逐个实时到达，而是积累到约 16KB 后一批一批出现。用户看到的是"一批一批"的内容更新，而不是逐 token 的真正流式效果。

### 根本原因
Vite 开发服务器的 proxy 使用 `http-proxy` 库，该库内部有 16KB 的 `highWaterMark` 缓冲。SSE 事件通常很小（几十到几百字节），`http-proxy` 会将多个小事件缓冲到填满 16KB 后才一次性刷新给客户端，导致批量到达的现象。

### 解决方案
使用 Vite 内置 proxy 的 `selfHandleResponse: true` 选项，让 http-proxy 不自动转发响应，改为手动零缓冲转发：

1. **`selfHandleResponse: true`** — http-proxy 不自动 pipe 响应，我们手动控制
2. **立即刷新响应头** — `res.flushHeaders()` 在收到后端响应后立即发送
3. **禁用 Nagle 算法** — `res.socket.setNoDelay(true)` 确保 TCP 不延迟小包
4. **零缓冲转发** — 每个 `data` 事件直接 `res.write(chunk)` 写入

### 踩坑记录

1. **自定义 http.request() 代理方案**：最初创建自定义 `sseProxyPlugin` 使用 `http.request()` 绕过 http-proxy，但出现 `socket hang up` 错误（502 Bad Gateway）。可能因为自定义代理的连接管理和请求头转发不够完善。

2. **Connect 中间件路径剥离**：使用 `server.middlewares.use("/api/v1/chat/stream", handler)` 时，Connect 会从 `req.url` 中剥离挂载路径，导致代理请求发到 `/` → 502。

**最终方案**：使用 Vite 内置 proxy + `selfHandleResponse`，比自定义代理更可靠（连接管理交给成熟的 http-proxy），只覆盖响应转发逻辑。

### 修改的文件
- `frontend/vite.config.ts` — SSE 路由使用 `selfHandleResponse: true` + 手动零缓冲转发

### 架构说明
```
浏览器 → Vite Dev Server
  ├── /api/v1/chat/stream (POST) → Vite http-proxy + selfHandleResponse (手动零缓冲) → Backend:8080
  └── /api/* (其他)            → Vite http-proxy (正常代理) → Backend:8080
```

### 前端 React 渲染
React 18 的自动 `setState` 批处理是正确的行为 — 多个 token 的状态更新合并为一次重渲染是性能优化，不需要改变。真正的问题是网络层的缓冲。

---

## Previous Focus

**重构 Agent 执行 DAG 构建** (June 3, 2026)

### 问题
Sidebar 显示的 DAG 不正确：用户 → 最终 → unknown 等待中 → 最终 → unknown... 
而不是真实的执行流程：用户 → AI(判断) → 工具 → AI(回复)

### 根本原因
之前的 DAG 构建逻辑基于 checkpoint metadata.writes，但 LangGraph checkpoint 的 writes 字段是空的（`{}`）。

### 解决方案
改用 **消息推断法** 构建 DAG：
1. 从最终状态获取所有消息
2. 根据消息类型推断执行流程：
   - HumanMessage → 用户节点
   - AIMessage + tool_calls → AI 决策节点（注册待处理工具调用）
   - ToolMessage → 通过 tool_call_id 匹配到 AI 节点，创建工具节点

### 修改的文件

1. **`backend/app/utils/dag.py`**
   - 重构 `_build_dag_from_messages()` 使用消息推断
   - 正确处理 tool_call_id 匹配和并行工具调用
   - 添加扁平化字段填充

2. **`backend/app/schemas/trace.py`**
   - StepOutput 添加扁平化字段：`thinking`, `tool_calls`, `model_name`, `tool_name`, `tool_args`, `tool_output`, `tool_call_id`
   - 方便前端直接访问，无需深入 metadata

3. **`frontend/src/types.ts`**
   - MessageStep 类型添加 `human` 消息类型
   - 添加 `tool_call_id`, `tool_calls`, `model_name` 字段

### 正确的 DAG 流程
```
用户 → AI(工具调用) → 工具1 → AI(最终回复)
                   ↘ 工具2 ↗
```

---

## Previous Focus

**简化 infra/llm 模块** (June 2, 2026)

### 变更内容
大幅简化 infra/llm 模块，彻底放弃 zai provider，只保留 dashscope provider。

### 修改的文件
1. `backend/app/infra/llm/factory.py`
   - 移除 `_build_extra_body()` 函数，直接内联 `extra_body = {"enable_thinking": thinking_mode}`
   - 移除 provider 参数判断和多 provider 分支逻辑
   - 文档注释更新：说明只支持 DashScope provider

2. `backend/scripts/sql/init_database.sql`
   - 移除 `zai` provider 的 INSERT 语句
   - 只保留 `dashscope` provider

### 设计决策
- **DashScope only**: 所有模型通过 DashScope API 访问
- **思考模式默认关闭**: `extra_body = {"enable_thinking": False}` 为默认值
- **LiteLLM Router**: 继续使用 Router 提供 fallback 和 retry 支持

---

## Previous Focus

**优化工具调用展示** (June 2, 2026)

### 问题
Agent 调用工具时，在 AI 消息气泡中看到了工具的返回结果（如搜索结果的 JSON），然后才是最终的 AI 消息回复。

### 根本原因
**三个问题：**

1. **`await call.output` 错误** - 后端 `_consume_tool_calls` 方法错误地使用了 `await call.output`。根据 LangChain v3 官方文档，Python 中 `call.output` 是直接属性访问，不需要 await。这导致异常：`object ToolMessage can't be used in 'await' expression`

2. **事件格式不匹配** - 后端之前发送 `type: "step"` 事件，前端期望 `type: "tool"` 和 `type: "tool_result"` 事件

3. **ToolMessage 内容被当作 token 发送** - `_consume_messages` 方法没有过滤消息类型，ToolMessage 的内容（工具返回的 JSON 结果）被当作 `type: "token"` 发送给前端，导致用户看到工具返回结果

### 解决方案
修改后端 `streaming.py`：

1. **`_consume_tool_calls`** - 去掉错误的 `await`，直接访问 `call.output` 和 `call.error`
2. **`_consume_messages`** - 在处理 text deltas 之前检查消息类型，只处理 `type="ai"` 的 AIMessage，跳过 ToolMessage
3. **最终消息发送** - 遍历 `final_messages` 倒序，只发送最后一个 AIMessage

### 修改的代码
**_consume_tool_calls (第472-494行):**
```python
raw_output = call.output  # 不需要 await
if raw_output is not None:
    if hasattr(raw_output, "content"):
        output = raw_output.content
```

**_consume_messages (第312-325行):**
```python
msg_type = getattr(final, "type", None)
if msg_type != "ai":
    # Skip ToolMessage, HumanMessage, etc.
    continue
# 然后才处理 text deltas
```

### 修改的文件
- `backend/app/services/streaming.py` - 三个问题的修复

### 推理过程展示
**已修复**：前端现在同时处理 `type: "llm"` 和 `type: "reasoning"` 事件（App.tsx 第772行）。
- `type: "llm"` - 旧版事件类型（兼容）
- `type: "reasoning"` - LangChain v3 streaming 标准

修改的文件：
- `frontend/src/App.tsx` - 添加 `|| event.type === "reasoning"` 条件
- `frontend/src/types.ts` - 添加 `reasoning` 类型到 `StreamEvent` union type

---

## Previous Focus

**修复多轮对话 non_standard 错误** (June 2, 2026)

添加 ContentFilterMiddleware 过滤消息中不支持的内容类型，解决 DashScope/智谱 AI 等模型在多轮对话时的 BadRequestError。

## Recent Changes (2026-06-02)

### 新增 ContentFilterMiddleware

**问题**：多轮对话时报错 `Invalid value: non_standard. Supported values are: 'text','image_url','video_url' and 'video'`

**根因**：thinking 模式下 AI 响应包含 `thinking`/`reasoning`/`non_standard` 类型内容块，第二轮对话时这些历史消息被发送给 API，导致 400 错误。

**解决方案**：
- 新增 `middleware/content_filter.py` — 过滤非标准内容类型
- 在 supervisor.py 的 middleware 列表中添加 `content_filter`
- 只保留 DashScope/智谱 AI 支持的类型：`text`, `image_url`, `video_url`, `video`

### Supervisor Agent 简化重构完成 (June 2, 2026)

基于 LangChain v1 官方最佳实践，简化 Agent 和 Middleware 代码，保持生产级特性（TTLCache、启动预加载）。

## Recent Changes (2026-06-02 重构)

### 已完成的重构步骤：

1. **简化 `middleware/prompt.py`** (328行 → ~140行, -57%)
   - 移除 `PromptService` 类，改用模块级函数和变量
   - 保留 TTLCache (5分钟过期) — 提示词修改后自动生效
   - 保留 asyncio.Lock — 防止并发文件 I/O
   - 保留 `preload_templates()` — 启动时预加载零延迟
   - 移除 `make_dynamic_prompt()` 工厂，直接定义 `@dynamic_prompt` 函数

2. **简化 `supervisor.py`** (126行 → ~75行, -40%)
   - 移除 `AgentManager` 类，改用模块级单例
   - 导出 `init_agent()` 和 `get_agent()` 函数
   - 添加 `is_ready()` 检查函数

3. **更新所有引用**
   - `agents/__init__.py` — 导出新 API
   - `main.py` — lifespan 调用 `preload_templates()` + `init_agent()`
   - `api/v1/chat/run.py` — 使用 `get_agent()`

### 代码量对比：

| 文件 | 重构前 | 重构后 | 变化 |
|------|--------|--------|------|
| `middleware/prompt.py` | 328行 | ~140行 | -57% |
| `supervisor.py` | 126行 | ~75行 | -40% |
| **Agent 相关总计** | **454行** | **~215行** | **-53%** |

### 保留的生产特性：

- ✅ TTLCache (5分钟) — 提示词修改无需重启
- ✅ asyncio.Lock — 防止并发文件 I/O
- ✅ 启动预加载 — 首次请求零延迟
- ✅ SummarizationMiddleware — 多轮对话历史压缩
- ✅ 动态模型切换 — per-request model override

### 新的文件结构：

```
backend/app/agents/
├── __init__.py          # 导出 init_agent, get_agent, is_ready
├── supervisor.py        # ~75行 (简化)
├── context.py           # 33行 (不变)
├── middleware/
│   ├── __init__.py
│   ├── prompt.py        # ~140行 (大简化)
│   └── model.py         # 86行 (不变)
├── prompts/
│   └── supervisor.md    # 不变
└── tools/               # 不变
```

## Active Decisions

- **不使用 LangGraph v0 `build_standard_agent_graph`** — 已迁移到 LangChain v1 `create_agent`
- **Middleware 使用官方装饰器模式** — `@dynamic_prompt`, `@wrap_model_call`
- **提示词缓存策略** — TTLCache 5分钟过期，适合 A/B 测试和紧急修复场景

## Active Branches

- Main development on `main` branch