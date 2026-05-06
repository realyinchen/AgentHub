# How to Add a New Agent

## Overview

AgentHub uses a plugin-based design, making it extremely simple to add new Agents. All Agents are built on LangGraph and support tool calling, streaming output, token statistics, and other features.

**Key Advantage**: Adding a new Agent requires only three steps—create the Agent file, import it in `__init__.py`, and add a database record. **No need to modify `agent_utils.py`**.

## Agent Development Process

### Step 1: Create Agent File

Create a new Agent file in the `backend/app/agents/` directory, for example `my_agent.py`:

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
# This line automatically registers the agent to AgentRegistry
my_agent = register_agent("my_agent")(workflow.compile())
```

**Key Points**:
- Use `build_standard_agent_graph()` factory function to automatically get streaming output, token statistics, and parallel tool execution
- Use `register_agent("agent_id")` to register the agent, no need to maintain mappings elsewhere

### Step 2: Import in `__init__.py`

Add the import in `backend/app/agents/__init__.py`:

```python
from app.agents.base import AgentRegistry
from app.agents.chatbot import chatbot
from app.agents.navigator import navigator
from app.agents.my_agent import my_agent  # Add your Agent

__all__ = ["AgentRegistry", "chatbot", "navigator", "my_agent"]
```

**Note**: Just add the import statement, the agent will automatically register to AgentRegistry.

### Step 3: Add Prompt Template

Add your Agent system prompt in the `backend/app/prompts/` directory:

```python
# backend/app/prompts/my_agent.py
import time
from datetime import datetime

PROMPT_TEMPLATE = """
You are a specialized agent for [Task Description].

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

### Step 4: Add Tools (Optional)

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

### Step 5: Initialize Database

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

## Complete Example

Refer to the existing `chatbot.py` and `navigator.py` implementations:

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

## Registration Mechanism Explained

AgentHub uses **Registry + Decorator pattern** to manage agents:

1. **AgentRegistry**: A global registry class that stores all agent instances
2. **register_agent()**: A decorator/function that automatically registers agents to AgentRegistry when compiled
3. **agent_utils.py**: Gets agents from AgentRegistry, no manual mapping needed

This design follows the "Open-Closed Principle"—open for extension, closed for modification.

### Files to Modify When Adding a New Agent

| File | Change Required |
|------|-----------------|
| `agents/my_agent.py` | Create agent (core work) |
| `agents/__init__.py` | Add one import line |
| `prompts/my_agent.py` | Create prompt |
| `tools/` | Create or reuse tools |
| Database | Add agent record |

**No longer need to modify `agent_utils.py`**.

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

### 1. Use build_standard_agent_graph

```python
# ✅ Recommended: Automatic streaming output, token statistics, parallel tool execution
workflow = build_standard_agent_graph(
    system_prompt=system_prompt,
    get_tools_fn=_get_tools,
)
agent = register_agent("my_agent")(workflow.compile())

# ❌ Not recommended: Manually build graph (loses standardized features)
workflow = StateGraph(AgentState)
# ... manually add nodes and edges ...
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

A: Ensure you're using the `build_standard_agent_graph()` function, which automatically handles streaming output and token statistics.

### Q: How to support multi-modal?

A: Explain multi-modal capabilities in the Prompt and ensure you use VLM models (like GPT-4o, Claude 3 Opus, etc.). AgentHub will automatically handle image messages.

## Advanced Topic: Complex Agent Orchestration

### Scope of build_standard_agent_graph

`build_standard_agent_graph` builds the classic **ReAct single-loop pattern**:

```
START → llm_call → [has tool_calls? → tools → llm_call (loop)]
                      [no tool_calls?  → END]
```

**Suitable scenarios** (~80% of agents):
- General conversation assistants (e.g., chatbot)
- Single-domain tool-calling agents (e.g., navigator)
- "Think → call tool → think again → answer" pattern

**Unsuitable scenarios**:

| Scenario | Why it doesn't work |
|----------|-------------------|
| Multi-agent collaboration (supervisor pattern) | Needs multiple llm_call nodes + routing nodes |
| Sequential workflow (step1 → step2 → step3) | Needs multiple nodes with different logic in sequence |
| Parallel branches + join | Needs fan-out/fan-in edge structure |
| Human-in-the-loop | Needs interrupt/resume mechanism |
| Content classification routing (classify first, then route) | `should_continue` only has tools/END two branches |
| Custom State (tracking stages, accumulated data) | Fixed to `AgentState(MessagesState)`, only messages |

### Building Complex Agents

For complex scenarios, use the low-level building blocks from `base.py` to freely orchestrate graph topology:

```python
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState

from app.agents.base import (
    create_llm_call_node,
    create_tool_node,
    register_agent,
    _filter_message_content_for_model,
)


# 1. Custom State (richer than AgentState)
class MyComplexState(MessagesState):
    """State for complex agents with additional context tracking."""
    stage: str = "classification"       # Current stage
    collected_data: dict = {}            # Accumulated data
    needs_review: bool = False           # Whether human review is needed


# 2. Custom node functions
async def classify_node(state: MyComplexState, config) -> dict:
    """Classification node: determine user request type."""
    # ... classification logic ...
    return {"stage": "research"}


async def synthesis_node(state: MyComplexState, config) -> dict:
    """Synthesis node: summarize all research results."""
    # ... synthesis logic ...
    return {"messages": [final_response]}


# 3. Reuse low-level building blocks to create LLM nodes
def get_research_tools():
    return [web_search, document_retriever]

research_llm = create_llm_call_node(
    system_prompt="You are a research assistant...",
    get_tools_fn=get_research_tools,
)
research_tools = create_tool_node(get_research_tools, parallel=True)


# 4. Freely orchestrate graph topology
workflow = StateGraph(MyComplexState)

# Add nodes
workflow.add_node("classify", classify_node)
workflow.add_node("research", research_llm)           # Reuse building block
workflow.add_node("research_tools", research_tools)   # Reuse building block
workflow.add_node("synthesize", synthesis_node)

# Define routing functions
def route_by_type(state: MyComplexState) -> str:
    """Route based on classification result."""
    if state["stage"] == "research":
        return "research"
    else:
        return "synthesize"

def should_continue_research(state: MyComplexState) -> str:
    """Determine if research stage should continue."""
    messages = state.get("messages", [])
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "next"

# Add edges
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

# 5. Compile and register
complex_agent = register_agent("complex_agent")(workflow.compile())
```

### Reusable Low-Level Building Blocks

| Building Block | Purpose |
|---------------|---------|
| `create_llm_call_node(prompt, tools_fn)` | Create LLM call node with automatic streaming, token stats |
| `create_tool_node(tools_fn, parallel)` | Create tool execution node with parallel execution support |
| `_filter_message_content_for_model(msg)` | Filter message content, remove unsupported blocks like thinking |
| `should_continue(state)` | Standard routing function: has tool_calls → tools, otherwise → END |
| `AgentState` | Standard State with only messages |
| `register_agent(agent_id)` | Registration function, call after compilation |

### Selection Guide

```
Your agent needs:
├── Single LLM + tool loop?
│   └── ✅ Use build_standard_agent_graph()
│
├── Multi-stage processing (classify → process → summarize)?
│   └── ✅ Custom State + reuse create_llm_call_node
│
├── Multi-agent collaboration (supervisor dispatches tasks)?
│   └── ✅ Multiple llm_call nodes + custom routing
│
└── Human-in-the-loop needed?
    └── ✅ Use interrupt() + custom State
```

Regardless of simplicity or complexity, always use `register_agent()` to register at the end.
