# 如何添加新的 Agent

## 概述

AgentHub 采用插件化设计，添加新 Agent 非常简单。所有 Agent 都基于 LangGraph 构建，支持工具调用、流式输出、Token 统计等特性。

## Agent 开发流程

### 步骤 1: 创建 Agent 文件

在 `backend/app/agents/` 目录下创建新的 Agent 文件，例如 `my_agent.py`：

```python
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.utils.llm import streaming_completion
from app.prompt import SYSTEM_PROMPTS


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


def create_my_agent(llm, tools):
    """创建自定义 Agent"""
    
    # 绑定工具到 LLM
    llm_with_tools = llm.bind_tools(tools)
    
    # 定义节点
    def agent_node(state: AgentState):
        messages = state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}
    
    # 定义路由
    def should_continue(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools"
        return END
    
    # 构建 Graph
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))
    
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    
    return workflow.compile()
```

### 步骤 2: 使用流式输出 + Token 统计（推荐）

为了自动获得 Token 统计功能和流式输出，请使用 `streaming_completion` 工具函数：

```python
async def my_agent_node(state: AgentState, config):
    messages = state["messages"]
    
    # 使用 streaming_completion 自动处理 Token 追踪
    result = await streaming_completion(
        llm,
        messages,
        agent_id="my_agent",
        config=config,
        system_prompt=SYSTEM_PROMPTS["my_agent"]
    )
    
    # 返回 raw_response 以包含完整 Token 统计
    return {"messages": [result.raw_response]}
```

**自动获得的特性**：
- ✅ Token-by-Token 流式输出
- ✅ Input/Output/Reasoning Token 统计
- ✅ 与前端 Token 可视化组件自动集成
- ✅ 思考模式支持

### 步骤 3: 注册 Agent

在 `backend/app/agents/__init__.py` 中注册你的新 Agent：

```python
from app.agents.chatbot import chatbot
from app.agents.navigator import navigator
from app.agents.my_agent import my_agent  # 导入你的 Agent

__all__ = ["chatbot", "navigator", "my_agent"]  # 添加到列表
```

### 步骤 4: 添加 Prompt 模板

在 `backend/app/prompt/` 目录下添加你的 Agent 系统提示词：

```python
# backend/app/prompt/my_agent.py
MY_AGENT_PROMPT = """
You are a specialized agent for [任务描述].

Your capabilities:
1. [Capability 1]
2. [Capability 2]
3. [Capability 3]

Follow these rules:
- Think carefully before answering
- Use tools when needed
- Be concise and helpful
"""
```

然后在 `backend/app/prompt/__init__.py` 中导出：

```python
from app.prompt.chatbot import CHATBOT_PROMPT
from app.prompt.navigator import NAVIGATOR_PROMPT
from app.prompt.my_agent import MY_AGENT_PROMPT

SYSTEM_PROMPTS = {
    "chatbot": CHATBOT_PROMPT,
    "navigator": NAVIGATOR_PROMPT,
    "my_agent": MY_AGENT_PROMPT,  # 添加你的 prompt
}
```

### 步骤 5: 添加工具（可选）

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

然后在 `backend/app/tools/__init__.py` 中导出：

```python
from app.tools.time import get_current_time
from app.tools.web import web_search
from app.tools.my_tools import my_custom_tool

__all__ = ["get_current_time", "web_search", "my_custom_tool"]
```

### 步骤 6: 初始化数据库

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

## 完整示例：带工具的 Agent

```python
# backend/app/agents/my_agent.py
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.utils.llm import streaming_completion
from app.prompt import SYSTEM_PROMPTS
from app.tools import my_custom_tool, get_current_time


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


async def create_my_agent(llm, checkpointer):
    """创建带工具的自定义 Agent"""
    
    tools = [my_custom_tool, get_current_time]
    llm_with_tools = llm.bind_tools(tools)
    
    async def agent_node(state: AgentState, config):
        messages = state["messages"]
        
        result = await streaming_completion(
            llm_with_tools,
            messages,
            agent_id="my_agent",
            config=config,
            system_prompt=SYSTEM_PROMPTS["my_agent"]
        )
        
        return {"messages": [result.raw_response]}
    
    def should_continue(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools"
        return END
    
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))
    
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    
    return workflow.compile(checkpointer=checkpointer)
```

## 高级模式：Master Agent 路由

如果你想让你的 Agent 被 Chatbot Master Agent 自动路由，需要：

1. **在 Master Agent 的 Prompt 中描述你的 Agent**
   
   更新 `backend/app/prompt/chatbot.py` 中的路由逻辑：

   ```python
   # 在 Chatbot 的系统提示词中添加你的 Agent 描述
   """
   Available Agents:
   - chatbot: 通用对话，适合日常问题、搜索
   - navigator: 导航规划，适合地点搜索、路线规划
   - my_agent: 你的 Agent 功能描述
   
   When to use which:
   - 如果用户问 XXX → 使用 my_agent
   - 如果用户问 YYY → 使用 navigator
   - 其他情况使用 chatbot
   """
   ```

2. **实现 Agent 切换逻辑**

   Master Agent 会根据用户查询自动选择最合适的 Agent，并在同一会话中无缝切换。

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

### 1. 始终使用 streaming_completion

```python
# ✅ 推荐：自动 Token 统计 + 流式输出
from app.utils.llm import streaming_completion
result = await streaming_completion(llm, messages, agent_id="my_agent", ...)

# ❌ 不推荐：手动调用 LLM
result = await llm.ainvoke(messages)  # 丢失 Token 统计
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

A: 确保：
1. 使用了 `streaming_completion()` 函数
2. 返回了 `result.raw_response`（不是 `result.content`）
3. 前端版本支持 Token 可视化

### Q: 如何支持多模态？

A: 在 Prompt 中说明多模态能力，并确保使用 VLM 模型（如 GPT-4o、Claude 3 Opus 等）。AgentHub 会自动处理图片消息。