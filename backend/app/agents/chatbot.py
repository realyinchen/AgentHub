from langchain.agents import create_agent

from app.core.models import llm


chatbot = create_agent(
    model=llm,
    tools=[],
    system_prompt="You are a helpful assistant",
)
