# How to Add a New Agent

## Overview

AgentHub uses a plugin-based design, making it extremely simple to add new Agents. All Agents are built on LangGraph and support tool calling, streaming output, token statistics, and other features.

## Agent Development Process

### Step 1: Create Agent File

Create a new Agent file in the `backend/app/agents/` directory, for example `my_agent.py`:

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
    """Create custom Agent"""
    
    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(tools)
    
    # Define nodes
    def agent_node(state: AgentState):
        messages = state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}
    
    # Define routing
    def should_continue(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools"
        return END
    
    # Build Graph
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))
    
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    
    return workflow.compile()
```

### Step 2: Use Streaming Output + Token Statistics (Recommended)

To automatically get token statistics functionality and streaming output, please use the `streaming_completion` utility function:

```python
async def my_agent_node(state: AgentState, config):
    messages = state["messages"]
    
    # Use streaming_completion to automatically handle token tracking
    result = await streaming_completion(
        llm,
        messages,
        agent_id="my_agent",
        config=config,
        system_prompt=SYSTEM_PROMPTS["my_agent"]
    )
    
    # Return raw_response to include complete token statistics
    return {"messages": [result.raw_response]}
```

**Automatically available features**:
- ✅ Token-by-Token streaming output
- ✅ Input/Output/Reasoning Token statistics
- ✅ Automatic integration with frontend Token visualization component
- ✅ Thinking mode support

### Step 3: Register Agent

Register your new Agent in `backend/app/agents/__init__.py`:

```python
from app.agents.chatbot import chatbot
from app.agents.navigator import navigator
from app.agents.my_agent import my_agent  # Import your Agent

__all__ = ["chatbot", "navigator", "my_agent"]  # Add to list
```

### Step 4: Add Prompt Template

Add your Agent system prompt in the `backend/app/prompt/` directory:

```python
# backend/app/prompt/my_agent.py
MY_AGENT_PROMPT = """
You are a specialized agent for [Task Description].

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

Then export in `backend/app/prompt/__init__.py`:

```python
from app.prompt.chatbot import CHATBOT_PROMPT
from app.prompt.navigator import NAVIGATOR_PROMPT
from app.prompt.my_agent import MY_AGENT_PROMPT

SYSTEM_PROMPTS = {
    "chatbot": CHATBOT_PROMPT,
    "navigator": NAVIGATOR_PROMPT,
    "my_agent": MY_AGENT_PROMPT,  # Add your prompt
}
```

### Step 5: Add Tools (Optional)

If your Agent needs custom tools, create tool files in the `backend/app/tools/` directory:

```python
# backend/app/tools/my_tools.py
from langchain_core.tools import tool


@tool
def my_custom_tool(param: str) -> str:
    """Tool description"""
    # Tool implementation
    return f"Result: {param}"
```

Then export in `backend/app/tools/__init__.py`:

```python
from app.tools.time import get_current_time
from app.tools.web import web_search
from app.tools.my_tools import my_custom_tool

__all__ = ["get_current_time", "web_search", "my_custom_tool"]
```

### Step 6: Initialize Database

Register your Agent in the database to make it visible in the frontend. Update `backend/scripts/sql/init_database.sql`:

```sql
INSERT INTO agents (id, name, description, is_active, created_at) VALUES
('chatbot', 'General Conversation Assistant', 'General conversation Agent supporting web search', true, NOW()),
('navigator', 'Navigation Planning Assistant', 'Agent supporting location search and route planning', true, NOW()),
('my_agent', 'My Custom Agent', 'Agent function description', true, NOW());  -- Add your Agent
```

Then run the initialization script:

```bash
cd backend
python scripts/init_database.py
```

## Complete Example: Agent with Tools

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
    """Create custom Agent with tools"""
    
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

## Advanced Mode: Master Agent Routing

If you want your Agent to be automatically routed by the Chatbot Master Agent, you need to:

1. **Describe your Agent in the Master Agent's Prompt**
   
   Update the routing logic in `backend/app/prompt/chatbot.py`:

   ```python
   # Add your Agent description in the Chatbot's system prompt
   """
   Available Agents:
   - chatbot: General conversation, suitable for daily questions, search
   - navigator: Navigation planning, suitable for location search, route planning
   - my_agent: Your Agent function description
   
   When to use which:
   - If user asks XXX → use my_agent
   - If user asks YYY → use navigator
   - Other cases use chatbot
   """
   ```

2. **Implement Agent switching logic**

   The Master Agent will automatically select the most appropriate Agent based on user queries and seamlessly switch within the same session.

## Test Your Agent

1. Start backend:
   ```bash
   cd backend
   python run_backend.py
   ```

2. Start frontend:
   ```bash
   cd frontend
   npm run dev
   ```

3. In the frontend interface:
   - Select your Agent from the Agent dropdown list
   - Send test message
   - Verify: Normal streaming output, normal tool calls, normal token statistics

## API Testing

Test the Agent directly using curl:

```bash
# Streaming call
curl -N -X POST http://localhost:8080/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my_agent",
    "thread_id": "test-thread-001",
    "message": "Test message",
    "model_id": "gpt-4o"
  }'
```

## Best Practices

### 1. Always Use streaming_completion

```python
# ✅ Recommended: Automatic Token statistics + streaming output
from app.utils.llm import streaming_completion
result = await streaming_completion(llm, messages, agent_id="my_agent", ...)

# ❌ Not recommended: Manually call LLM
result = await llm.ainvoke(messages)  # Lose Token statistics
```

### 2. Clear Tool Naming

```python
# ✅ Good naming
@tool
def search_restaurants(city: str, cuisine: str) -> list:
    """Search for restaurants in specified city"""

# ❌ Bad naming
@tool
def func1(a: str, b: str) -> str:
    """Tool"""
```

### 3. Layered Prompt Design

```
System Prompt
  ├── Role definition
  ├── Capability description
  ├── Tool usage guidelines
  ├── Output format requirements
  └── Examples (if complex)
```

### 4. Error Handling

```python
@tool
def my_tool(param: str) -> str:
    try:
        # Tool logic
        return result
    except Exception as e:
        return f"Error: {str(e)}. Please try again with different parameters."
```

## Common Issues

### Q: Agent doesn't call tools?

A: Check:
1. Is the tool's `@tool` decorator correct?
2. Is the tool description clear?
3. Does the System Prompt explain tool usage scenarios?
4. Does the LLM support tool calling (use supported models like GPT-4, Claude 3, etc.)?

### Q: Token statistics not showing?

A: Ensure:
1. Used the `streaming_completion()` function
2. Returned `result.raw_response` (not `result.content`)
3. Frontend version supports Token visualization

### Q: How to support multi-modal?

A: Explain multi-modal capabilities in the Prompt and ensure you use VLM models (like GPT-4o, Claude 3 Opus, etc.). AgentHub will automatically handle image messages.