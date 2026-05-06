# 如何添加新的 Agent

## 概述

AgentHub 采用插件化设计，添加新 Agent 非常简单。所有 Agent 都基于 LangGraph 构建，支持工具调用、流式输出、Token 统计等特性。

**核心优势**：新增 Agent 只需三步——创建 Agent 文件、导入到 `__init__.py`、添加数据库记录。**无需修改 `agent_utils.py`**。

## Agent 开发流程

### 步骤 1: 创建 Agent 文件

在 `backend/app/agents/` 目录下创建新的 Agent 文件，例如 `my_agent.py`：

```python
"""My custom agent."""

from app.prompts.my_agent import get_my_agent_prompt
from app.tools.my_tools import my_custom_tool
from app.tools.time import get_current_time
from app.agents.base import build_standard_agent_graph, register_agent


def _get_tools():
    """Get tools for this agent."""
    return [my_custom_tool, get_current_time]


# Get system prompt
system_prompt = get_my_agent_prompt()

# Build the graph using the base builder
workflow = build_standard_agent_graph(
    system_prompt=system_prompt,
    get_tools_fn=_get_tools,
)

# Compile and register the agent
# 这一行会自动将 agent 注册到 AgentRegistry
my_agent = register_agent("my_agent")(workflow.compile())
```

**关键点**：
- 使用 `build_standard_agent_graph()` 工厂函数，自动获得流式输出、Token 统计、并行工具执行
- 使用 `register_agent("agent_id")` 注册 agent，无需在其他地方维护映射

### 步骤 2: 导入到 `__init__.py`

在 `backend/app/agents/__init__.py` 中添加导入：

```python
from app.agents.base import AgentRegistry
from app.agents.chatbot import chatbot
from app.agents.navigator import navigator
from app.agents.my_agent import my_agent  # 添加你的 Agent

__all__ = ["AgentRegistry", "chatbot", "navigator", "my_agent"]
```

**注意**：只需添加导入语句，agent 会自动注册到 AgentRegistry。

### 步骤 3: 添加 Prompt 模板

在 `backend/app/prompts/` 目录下添加你的 Agent 系统提示词：

```python
# backend/app/prompts/my_agent.py
import time
from datetime import datetime

PROMPT_TEMPLATE = """
You are a specialized agent for [任务描述].

Current Time: {current_datetime}

Your capabilities:
1. [Capability 1]
2. [Capability 2]
3. [Capability 3]

Follow these rules:
- Think carefully before answering
- Use tools when needed
- Be concise and helpful
"""


def get_my_agent_prompt(timezone: str = "Asia/Shanghai") -> str:
    """Get the system prompt with current time context."""
    now = datetime.now()
    
    context = {
        "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "current_date": now.strftime("%Y-%m-%d"),
        "current_weekday": now.strftime("%A"),
        "iso_time": now.isoformat(),
        "timestamp": int(time.time()),
        "timezone": timezone,
    }
    
    return PROMPT_TEMPLATE.format(**context)
```

### 步骤 4: 添加工具（可选）

如果你的 Agent 需要自定义工具，在 `backend/app/tools/` 目录下创建工具文件：

```python
# backend/app/tools/my_tools.py
from langchain_core.tools import tool


@tool
def my_custom_tool(param: str) -> str:
    """工具描述"""
    # 工具实现
    return f"Result: {param}"
```

### 步骤 5: 初始化数据库

在数据库中注册你的 Agent，使其在前端可见。更新 `backend/scripts/sql/init_database.sql`：

```sql
INSERT INTO agents (id, name, description, is_active, created_at) VALUES
('chatbot', '通用对话助手', '支持联网搜索的通用对话 Agent', true, NOW()),
('navigator', '导航规划助手', '支持地点搜索和路线规划的 Agent', true, NOW()),
('my_agent', '我的自定义 Agent', 'Agent 功能描述', true, NOW());  -- 添加你的 Agent
```

然后运行初始化脚本：

```bash
cd backend
python scripts/init_database.py
```

## 完整示例

参考现有的 `chatbot.py` 和 `navigator.py` 实现：

```python
# backend/app/agents/chatbot.py
from app.prompts.chatbot import get_prompt
from app.tools.time import get_current_time
from app.tools.web import create_web_search
from app.agents.base import build_standard_agent_graph, register_agent


def _get_tools():
    """Get tools lazily to avoid import-time errors when API keys are missing."""
    try:
        web_search = create_web_search()
        return [get_current_time, web_search]
    except Exception:
        return [get_current_time]


# Get system prompt
system_prompt = get_prompt()

# Build the graph
workflow = build_standard_agent_graph(
    system_prompt=system_prompt,
    get_tools_fn=_get_tools,
)

# Compile and register
chatbot = register_agent("chatbot")(workflow.compile())
```

## 注册机制说明

AgentHub 使用 **Registry + 装饰器模式** 管理 agents：

1. **AgentRegistry**：一个全局注册表类，存储所有 agent 实例
2. **register_agent()**：装饰器/函数，在 agent 编译时自动注册到 AgentRegistry
3. **agent_utils.py**：从 AgentRegistry 获取 agent，无需手动维护映射

这种设计遵循"开闭原则"——对扩展开放，对修改关闭。

### 新增 Agent 时需要改动的文件

| 文件 | 改动内容 |
|------|---------|
| `agents/my_agent.py` | 创建 agent（核心工作） |
| `agents/__init__.py` | 添加一行导入 |
| `prompts/my_agent.py` | 创建 prompt |
| `tools/` | 创建或复用 tools |
| 数据库 | 添加 agent 记录 |

**不再需要修改 `agent_utils.py`**。

## 测试你的 Agent

1. 启动后端：
   ```bash
   cd backend
   python run_backend.py
   ```

2. 启动前端：
   ```bash
   cd frontend
   npm run dev
   ```

3. 在前端界面中：
   - 从 Agent 下拉列表中选择你的 Agent
   - 发送测试消息
   - 验证：流式输出正常、工具调用正常、Token 统计正常

## API 测试

使用 curl 直接测试 Agent：

```bash
# 流式调用
curl -N -X POST http://localhost:8080/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my_agent",
    "thread_id": "test-thread-001",
    "message": "测试消息",
    "model_id": "gpt-4o"
  }'
```

## 最佳实践

### 1. 使用 build_standard_agent_graph

```python
# ✅ 推荐：自动获得流式输出、Token 统计、并行工具执行
workflow = build_standard_agent_graph(
    system_prompt=system_prompt,
    get_tools_fn=_get_tools,
)
agent = register_agent("my_agent")(workflow.compile())

# ❌ 不推荐：手动构建 graph（丢失标准化功能）
workflow = StateGraph(AgentState)
# ... 手动添加节点和边 ...
```

### 2. 工具命名要清晰

```python
# ✅ 好的命名
@tool
def search_restaurants(city: str, cuisine: str) -> list:
    """搜索指定城市的餐厅"""

# ❌ 不好的命名
@tool
def func1(a: str, b: str) -> str:
    """工具"""
```

### 3. 分层的 Prompt 设计

```
System Prompt
  ├── 角色定义
  ├── 能力描述
  ├── 工具使用指南
  ├── 输出格式要求
  └── 例子（如果复杂）
```

### 4. 错误处理

```python
@tool
def my_tool(param: str) -> str:
    try:
        # 工具逻辑
        return result
    except Exception as e:
        return f"Error: {str(e)}. Please try again with different parameters."
```

## 常见问题

### Q: Agent 不调用工具怎么办？

A: 检查：
1. 工具的 `@tool` 装饰器是否正确
2. 工具描述是否清晰
3. System Prompt 中是否说明了工具使用场景
4. LLM 是否支持 tool calling（使用支持的模型如 GPT-4、Claude 3 等）

### Q: Token 统计不显示？

A: 确保使用了 `build_standard_agent_graph()` 函数，它会自动处理流式输出和 Token 统计。

### Q: 如何支持多模态？

A: 在 Prompt 中说明多模态能力，并确保使用 VLM 模型（如 GPT-4o、Claude 3 Opus 等）。AgentHub 会自动处理图片消息。

## 高级主题：复杂 Agent 编排

### build_standard_agent_graph 的适用范围

`build_standard_agent_graph` 构建的是经典的 **ReAct 单循环模式**：

```
START → llm_call → [有 tool_calls? → tools → llm_call（循环）]
                      [无 tool_calls? → END]
```

**适用场景**（约 80% 的 agent）：
- 通用对话助手（如 chatbot）
- 单一领域的工具调用 agent（如 navigator）
- "思考 → 调工具 → 再思考 → 回答"模式

**不适用场景**：

| 场景 | 为什么不行 |
|------|-----------|
| 多 Agent 协作（supervisor 模式） | 需要多个 llm_call 节点 + 路由节点 |
| 顺序工作流（step1 → step2 → step3） | 需要多个不同逻辑的节点串联 |
| 并行分支 + 汇聚 | 需要扇出/扇入的边结构 |
| Human-in-the-loop | 需要中断/恢复机制 |
| 内容分类路由（先分类，再走不同路径） | `should_continue` 只有 tools/END 两个分支 |
| 自定义 State（追踪阶段、累积数据） | 固定使用 `AgentState(MessagesState)`，只有 messages |

### 复杂 Agent 的构建方式

复杂场景下，可以直接使用 `base.py` 提供的底层构件自由编排图拓扑：

```python
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState

from app.agents.base import (
    create_llm_call_node,
    create_tool_node,
    register_agent,
    _filter_message_content_for_model,
)


# 1. 自定义 State（比 AgentState 更丰富）
class MyComplexState(MessagesState):
    """复杂 agent 的状态，追踪更多上下文。"""
    stage: str = "classification"       # 当前阶段
    collected_data: dict = {}            # 累积的数据
    needs_review: bool = False           # 是否需要人工审核


# 2. 自定义节点函数
async def classify_node(state: MyComplexState, config) -> dict:
    """分类节点：判断用户请求类型。"""
    # ... 分类逻辑 ...
    return {"stage": "research"}


async def synthesis_node(state: MyComplexState, config) -> dict:
    """综合节点：汇总所有研究结果。"""
    # ... 综合逻辑 ...
    return {"messages": [final_response]}


# 3. 复用底层构件创建 LLM 节点
def get_research_tools():
    return [web_search, document_retriever]

research_llm = create_llm_call_node(
    system_prompt="You are a research assistant...",
    get_tools_fn=get_research_tools,
)
research_tools = create_tool_node(get_research_tools, parallel=True)


# 4. 自由编排图拓扑
workflow = StateGraph(MyComplexState)

# 添加节点
workflow.add_node("classify", classify_node)
workflow.add_node("research", research_llm)           # 复用底层构件
workflow.add_node("research_tools", research_tools)   # 复用底层构件
workflow.add_node("synthesize", synthesis_node)

# 定义路由函数
def route_by_type(state: MyComplexState) -> str:
    """根据分类结果路由。"""
    if state["stage"] == "research":
        return "research"
    else:
        return "synthesize"

def should_continue_research(state: MyComplexState) -> str:
    """判断 research 阶段是否继续。"""
    messages = state.get("messages", [])
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "next"

# 添加边
workflow.add_edge(START, "classify")
workflow.add_conditional_edges("classify", route_by_type, {
    "research": "research",
    "synthesize": "synthesize",
})
workflow.add_conditional_edges("research", should_continue_research, {
    "tools": "research_tools",
    "next": "synthesize",
})
workflow.add_edge("research_tools", "research")
workflow.add_edge("synthesize", END)

# 5. 编译并注册
complex_agent = register_agent("complex_agent")(workflow.compile())
```

### 可复用的底层构件

| 构件 | 用途 |
|------|------|
| `create_llm_call_node(prompt, tools_fn)` | 创建 LLM 调用节点，自动处理流式输出、Token 统计 |
| `create_tool_node(tools_fn, parallel)` | 创建工具执行节点，支持并行执行 |
| `_filter_message_content_for_model(msg)` | 过滤消息内容，移除 thinking 块等不支持的内容 |
| `should_continue(state)` | 标准的路由函数：有 tool_calls → tools，否则 → END |
| `AgentState` | 标准 State，只包含 messages |
| `register_agent(agent_id)` | 注册函数，编译后调用 |

### 选择指南

```
你的 agent 需要：
├── 单一 LLM + 工具循环？
│   └── ✅ 使用 build_standard_agent_graph()
│
├── 多阶段处理（先分类、再处理、再汇总）？
│   └── ✅ 自定义 State + 复用 create_llm_call_node
│
├── 多 Agent 协作（supervisor 分发任务）？
│   └── ✅ 多个 llm_call 节点 + 自定义路由
│
└── 需要 Human-in-the-loop？
    └── ✅ 使用 interrupt() + 自定义 State
```

无论简单还是复杂，最后都用 `register_agent()` 注册即可。
