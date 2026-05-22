# FastAPI + LangChain 最佳实践深度评审

> **状态**：已完成 Phase 0/1/2/3（共 13 项）+ PR-A（2 项），剩余 **18 个待办**
> **目标**：保持 33 个 API 端点行为完全不变的前提下，持续收敛代码复杂度与一致性。

---

## 一、目标目录结构

```
backend/app/
├── main.py                    # FastAPI 入口 + lifespan
├── api/                       # HTTP 接口层
│   ├── errors.py              # 全局异常处理
│   └── v1/
│       ├── router.py          # 路由聚合
│       ├── dependencies.py    # 依赖注入 (get_db)
│       ├── chat.py            # stream / invoke / history
│       ├── chat_title.py      # 标题 CRUD + 自动生成
│       ├── chat_session.py    # 会话管理、统计、thinking 模式
│       ├── agent.py           # Agent 发现与配置
│       ├── model.py           # 模型 CRUD 与选择
│       ├── provider.py        # API Key 配置管理
│       ├── stream.py          # SSE 流式引擎
│       └── trace.py           # Trace Kanban 路由
├── agents/                    # Agent 运行时层
│   ├── registry.py            # 中央注册表 (DB + 原子快照)
│   ├── middleware/
│   │   ├── model/dynamic.py   # @wrap_model_call 动态模型选择
│   │   └── prompt/{dynamic,service}.py
│   ├── chatbot/{chatbot.py,types.py}
│   ├── rag_agent/             # (未来) RAG
│   ├── research/              # (未来) 深度研究
│   └── multi_agent/           # (未来) 多 Agent 协作 Supervisor
├── infra/                     # 基础设施层
│   ├── config.py              # pydantic-settings (单一配置源)
│   ├── cache.py               # vector_search TTLCache 实例
│   ├── database/              # 工厂模式，PG/SQLite 双后端
│   ├── llm/                   # LiteLLM 网关、模型缓存、extra_body
│   └── tools/                 # 基础工具 (time, web, sql, vectorstore)
├── models/                    # SQLAlchemy ORM
├── schemas/                   # Pydantic v2 DTO
├── crud/                      # 异步 DB 操作
├── observability/             # 只读追踪重建
│   ├── checkpoint.py / trace.py / dag.py / parsers.py
├── utils/
│   ├── message_utils.py       # 统一消息转换 (单一来源)
│   ├── request_handler.py     # 请求→Agent 参数转换
│   ├── crypto.py              # AES-GCM 加密
│   ├── async_writer.py        # 异步写入队列
│   ├── cache.py               # @cached decorator (Thundering Herd 防护)
│   └── token_utils.py         # ⬜ (P2-2 待新建) token usage 提取
└── prompts/                   # MD 提示词模板
    └── chatbot.md
```

---

## 二、评审维度

| 维度 | 标准 |
|------|------|
| **高并发** | 无阻塞 I/O、连接池复用、避免 GIL 竞争、异步优先 |
| **低延迟** | 减少序列化开销、零拷贝消息传递、预热缓存 |
| **低代码复杂度** | 单一职责、避免过度抽象、消除中间层 |
| **模块化** | 层间单向依赖、接口明确、每层可独立测试 |
| **高可维护性** | 类型安全、配置集中、错误处理一致 |

---

## 三、待办问题清单（18 项）

> **PR-A 已完成（2026-05-22）**：N1（删除 `app/tools/`）+ F-I（修双 commit）。详见第七章。

### 🔴 P1 — 高 ROI（30 min 内，对架构整洁度提升明显）

#### P3 / P19 / F-A 🔴 `CheckpointTraceReader` 是过度抽象门面
**位置**：`observability/__init__.py:44-105`
**问题**：6 处调用都是 100% 委派转发，无任何逻辑
**操作**：
1. 删除 `class CheckpointTraceReader` 整段
2. `__all__` 改为 `["CheckpointReader", "TraceBuilder", "DagBuilder"]`
3. 修改 6 处调用方（`chat.py:139` 1 处 + `trace.py:34/148/180/213/245/280` 6 处）：
   - `get_checkpoint_history` → `CheckpointReader(agent)`
   - `get_execution_trace / step / replay` → `TraceBuilder(agent)`
   - `get_execution_dag` → `DagBuilder(agent)`

#### N2 / C-3 🟡 `stream.py` 访问 `ModelManager._models_cache` 私有属性
**位置**：`api/v1/stream.py:259-273`
**操作**：在 `ModelManager` 中新增公开方法 `get_first_active_llm_id()`，`stream.py` 改用该方法

```python
# infra/llm/model_manager.py
@classmethod
def get_first_active_llm_id(cls) -> str | None:
    """Return the first active LLM model_id, or None."""
    for m in cls._models_cache.values():
        if m.model_type == "llm" and m.is_active:
            return m.model_id
    return None

# stream.py
initial_model = (
    ModelManager.get_default_llm_id()
    or ModelManager.get_first_active_llm_id()
)
```

---

### 🟡 P2 — 业务功能修复（涉及 LLM 调用路径，需多端验证）

#### N3 / F-G 🟡 `chat_title.generate_title` 绕过统一 LLM 工厂
**位置**：`api/v1/chat_title.py:130-145`
**问题**：唯一直接调 `router.acompletion(...)` 绕过 LangChain 的 LLM 调用
**修复**：改用 `get_system_default_llm().ainvoke([SystemMessage(...), HumanMessage(...)])`
**收益**：统一 LLM 调用路径；title 生成出现在 LangSmith trace
**风险**：中 —— 改动了"已能用"的代码，需验证 title 生成行为不变

#### P13 / F-H 🟡 invoke 端点缺失 token usage
**位置**：`api/v1/chat.py::invoke` + 新建 `utils/token_utils.py`
**操作**：
1. **新建** `utils/token_utils.py`，将 `stream.py` 中的 `_extract_usage` / `_accumulate_usage` 提取为 `extract_usage` / `accumulate_usage` / `empty_totals` 三个公共函数
2. `stream.py` 改用 `from app.utils.token_utils import ...`
3. `chat.py::invoke` 在 `agent.ainvoke` 后聚合所有 AI 消息的 usage 并写入 DB

#### F-B / F-F 🟡 trace 路由 agent 默认值不一致 + 离线无兜底
**问题**：
- `/traces` 默认 `agent_id="all"`；`/traces/{tid}/*` 五个端点默认 `"default"`，DB 中根本没这个 ID
- agent `is_active=false` 下线后所有历史 trace 立即 404
**操作**：
1. 5 个 trace 端点的 `agent_id` 默认值统一为 `"all"`
2. 新增 helper `_resolve_agent(db, agent_id, thread_id)`：当 `agent_id="all"` 时从 `conversation` 表反查
3. agent 已下线时返回 `410 Gone` 而非误导性 404

---

### 🟢 P3 — 一致性收敛（低风险）

#### F-C 🟢 `/chat/conversations` 用 `JSONResponse` 而非 `response_model`
**位置**：`api/v1/chat_session.py:34-65`
**问题**：唯一手动构造 `JSONResponse` 的列表端点，OpenAPI schema 里响应体是 `Any`
**修复**：改为
```python
@api_router.get("/conversations", response_model=list[ConversationInDB])
async def get_conversations(
    response: Response,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationInDB]:
    conversations, total = await list_conversations(db=db, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [ConversationInDB.model_validate(c) for c in conversations]
```

#### P21 / C-5 🟢 `_get_tools()` 缺少结果缓存
**位置**：`agents/chatbot/chatbot.py:23-37`
**修复**：使用模块级 `_tools_cache: list | None = None`，首次成功后缓存

#### P9 / I-4 🟢 `config.py` 缺少 `PROMPTS_DIR` 配置
**位置**：`infra/config.py` + `agents/middleware/prompt/service.py`
**操作**：
```python
# infra/config.py
PROMPTS_DIR: str = Field("", description="Override prompts directory (absolute path). Empty = use app/prompts.")

@computed_field
@property
def prompts_dir(self) -> Path:
    if self.PROMPTS_DIR:
        return Path(self.PROMPTS_DIR)
    return Path(__file__).resolve().parent.parent / "prompts"
```
`PromptService.__init__` 改用 `get_settings().prompts_dir`

#### P10 🟢 清理旧 Schema 残骸
**操作**：grep `MessageStep` / `RequestContext` / `get_chat_litellm` 等已删除符号是否还有遗留 import；清理 docstring 中的过期引用

---

### 🔵 P4 — 测试友好性（仅在引入 pytest-asyncio 时才必要）

#### P17 / C-6 🔵 `ModelManager` 改实例单例
**位置**：`infra/llm/model_manager.py`
**问题**：
1. classmethod + 可变类变量 → 测试无法独立 mock
2. `asyncio.Lock = asyncio.Lock()` 在 import 时绑定 event loop
**操作**：改为 `__init__` 实例 + 模块级 `_model_manager` + 延迟创建 `_router_lock`；约 12 处调用方改造（`ModelManager.refresh()` → `get_model_manager().refresh()`）
**建议**：仅在引入单元测试基建时再做，否则纯增 PR 噪音

---

## 四、推荐 PR 划分（按风险分批落地）

| PR | 内容 | 涉及文件 | 风险 | 行为变更 |
|:---:|------|:---:|:---:|------|
| ~~**PR-A**~~ | ✅ 已完成（2026-05-22）N1 删 `app/tools/` + F-I 修双 commit | 6 | 🟢 零 | 无 |
| **PR-B** | P3/P19 删 CheckpointTraceReader + N2 修私有访问 | 4 | 🟡 低 | 无 |
| **PR-C** | N3 统一 title 走 `get_system_default_llm()` | 1 | 🟡 中 | LLM 调用栈变 |
| **PR-D** | P13 invoke 补 token usage（新增 `utils/token_utils.py`） | 3 | 🟡 中 | invoke 现在写 DB |
| **PR-E** | F-B/F-F trace 路由 agent 默认值 + 离线兜底 | 2 | 🟡 中 | trace 端点新行为 |
| **PR-F** | F-C `/chat/conversations` + P21 `_get_tools` 缓存 + P9 PROMPTS_DIR + P10 清理 | 4 | 🟢 低 | 无 |
| **PR-G**（延后） | P17 ModelManager 实例化 | 12+ | 🟡 中 | 无（仅测试友好性） |

**建议节奏**：
- ~~PR-A~~ ✅ 已完成、PR-B 本周做（零风险 + 高 ROI）
- PR-C、PR-D、PR-E 下周做（带业务回归）
- PR-F 任意时间穿插
- PR-G 等到引入测试基建时再做

---

## 五、行为不变验证清单（每个 PR 必跑）

### 5.1 Smoke Test（33 端点）
```python
import httpx
BASE = "http://localhost:8000/api/v1"

# Health
assert httpx.get("http://localhost:8000/health").json() == {"status":"ok"}

# Agent
assert httpx.get(f"{BASE}/agents/").json()["total"] >= 1
assert httpx.get(f"{BASE}/agents/chatbot").json()["agent_id"] == "chatbot"

# Models / Providers
assert httpx.get(f"{BASE}/models/").json()["default_llm"]
assert "providers" in httpx.get(f"{BASE}/providers/").json()

# Chat - stream
r = httpx.post(f"{BASE}/chat/stream", json={
    "content": "hello", "agent_id": "chatbot", "user_id": "smoke",
    "thread_id": "00000000-0000-0000-0000-000000000001",
    "request_id": "smoke-1",
})
assert "data: [DONE]" in r.text

# Chat - invoke
r = httpx.post(f"{BASE}/chat/invoke", json={...})
assert r.json()["type"] == "ai"

# History / Trace
r = httpx.get(f"{BASE}/chat/history/chatbot/00000000-0000-0000-0000-000000000001")
assert "messages" in r.json() and "message_sequence" in r.json()
r = httpx.get(f"{BASE}/traces?page=0&page_size=10")
assert r.status_code == 200
```

### 5.2 OpenAPI Schema diff
```bash
# 重构前
curl http://localhost:8000/openapi.json > before.json
# 重构后
curl http://localhost:8000/openapi.json > after.json
diff <(jq -S . before.json) <(jq -S . after.json)
```
**期望**：除主动修改的端点（如 F-C 把 `/chat/conversations` 改为强类型）外，**0 差异**。

### 5.3 关键路径手测
1. 前端创建新会话 → 发消息 → 看到流式 token + reasoning
2. 刷新页面 → 历史完整恢复 → `tool_info` 显示正确
3. 切换模型 → 下一条消息走新模型
4. "自动生成标题" → 返回 ≤ 20 字符串
5. Trace Kanban → 列出最近 24h → DAG 渲染 → replay 可用
6. 配置页：模型 CRUD / provider API key 修改

---

## 六、架构健康度评分

| 维度 | 初始 | 当前 | 目标 | 说明 |
|------|:---:|:---:|:---:|------|
| **代码重复** | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | `app/tools/` 死目录已删 ✅ |
| **抽象适度** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | CheckpointTraceReader 门面待删 |
| **模块边界** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | chat.py 拆分完成 ✅ |
| **配置管理** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | PROMPTS_DIR 配置化 ⬜ |
| **类型安全** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | `/chat/conversations` response_model ⬜ |
| **可测试性** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ModelManager 实例化 ⬜ |
| **异步一致性** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | invoke token usage ⬜ |
| **封装** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | stream.py 访问私有属性 ⬜ |
| **LLM 调用一致性** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | title 生成绕过工厂 ⬜ |
| **API 完整性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 33 端点全保留 ✅ |

**整体**：当前 **4.5/5**（+0.1，PR-A 完成），全部 PR 完成后预计 **4.8/5**。

---

## 七、已完成历史汇总（15 项，已删除详细描述以保持 TODO 简洁）

| Phase / PR | 解决问题 | 完成日期 |
|:---:|------|:---:|
| **Phase 0** | P4 + P14（删除未用 DI + RequestContext） | 2026-05-21 |
| **Phase 1** | P5 + P18 + F-6（统一 thinking_mode + 精简 llm/__init__.py） | 2026-05-21 |
| **Phase 2** | P1 + P11 + P12 + P20（消息转换合一 + 请求处理独立） | 2026-05-21 |
| **Phase 3** | P15 + P16 + P6 + P7（删 dict 双路径 + 删 get_chat_litellm + 拆 chat.py + schemas 整理） | 2026-05-22 |
| **PR-A** | N1（删 `app/tools/` 死目录）+ F-I（修 `agent.py` 双 commit → `db.flush()`） | 2026-05-22 |

**已解决（15/33）**：P1, P4, P5, P6, P7, P11, P12, P14, P15, P16, P18, P20, F-6, N1, F-I
**待办（18）**：见第三章节
