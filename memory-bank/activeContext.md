# Active Context

## Current Focus

**Supervisor Agent 简化重构完成** (June 2, 2026)

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