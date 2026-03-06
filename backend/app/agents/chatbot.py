"""Chatbot agent with time and web search capabilities."""

from langchain.agents import create_agent

from app.core.models import llm
from app.prompt.chatbot import get_prompt
from app.tools.time import get_current_time
from app.tools.web import create_web_search


web_search = create_web_search()

tools = [get_current_time, web_search]

system_prompt = get_prompt()

chatbot = create_agent(
    model=llm,
    tools=tools,
    system_prompt=system_prompt,
)
