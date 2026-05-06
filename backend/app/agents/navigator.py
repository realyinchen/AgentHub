"""Navigator agent with Amap (Gaode Map) capabilities.

This agent uses the reusable base infrastructure to minimize code duplication.
Tools are executed in parallel using asyncio.gather for optimal performance.
"""

from app.prompts.navigator import get_navigator_prompt
from app.tools.time import get_current_time
from app.tools.amap import AMAP_TOOLS
from app.agents.base import build_standard_agent_graph, register_agent


def _get_tools():
    """Get tools for navigator agent.

    Tools include:
    - Amap tools for location, routing, and weather
    - Time tool for current time
    """
    # Amap tools (includes amap_weather for weather queries)
    tools = list(AMAP_TOOLS)

    # Add time tool
    tools.append(get_current_time)

    return tools


# Get system prompt
system_prompt = get_navigator_prompt()

# Build the graph using the base builder
# parallel_tools=True by default (navigator uses parallel tool execution
workflow = build_standard_agent_graph(
    system_prompt=system_prompt,
    get_tools_fn=_get_tools,
)

# Compile the agent and register it
navigator = register_agent("navigator")(workflow.compile())
