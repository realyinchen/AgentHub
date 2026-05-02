"""Chatbot agent with time and web search capabilities.

This agent uses the reusable base infrastructure to minimize code duplication.
"""

from app.prompts.chatbot import get_prompt
from app.tools.time import get_current_time
from app.tools.web import create_web_search
from app.agents.base import build_standard_agent_graph


def _get_tools():
    """Get tools lazily to avoid import-time errors when API keys are missing."""
    try:
        web_search = create_web_search()
        return [get_current_time, web_search]
    except Exception:
        # Fallback to just time tool if web search fails to initialize
        return [get_current_time]


# Get system prompt
system_prompt = get_prompt()

# Build the graph using the base builder
# parallel_tools=True by default (all agents use parallel tool execution)
workflow = build_standard_agent_graph(
    system_prompt=system_prompt,
    get_tools_fn=_get_tools,
)

# Compile the agent
chatbot = workflow.compile()
