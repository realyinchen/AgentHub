import logging
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, AnyMessage
from typing import Any

from app.agents import AgentGraph, DEFAULT_AGENT, get_all_agent_info, get_agent
from app.schema import ChatMessage, UserInput, ChatHistoryInput, ChatHistory
from app.schema.agent_info import AgentInfoMetadata
from app.utils.message_utils import (
    handle_input,
    langchain_to_chat_message,
    streaming_message_generator,
)

logger = logging.getLogger(__name__)

api_router = APIRouter()


def _sse_response_example() -> dict[int | str, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }


@api_router.post(
    "/{agent_id}/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
)
async def stream(
    user_input: UserInput, agent_id: str = DEFAULT_AGENT
) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """
    agent: AgentGraph = get_agent(agent_id)
    return StreamingResponse(
        streaming_message_generator(user_input, agent),
        media_type="text/event-stream",
    )


@api_router.post("/{agent_id}/invoke")
async def invoke(user_input: UserInput, agent_id: str = DEFAULT_AGENT) -> ChatMessage:
    """
    Async invoke an agent with user input to retrieve a final response.

    Use thread_id to persist and continue a multi-turn conversation.
    """

    # NOTE: Currently this only returns the last message or interrupt.
    # In the case of an agent outputting multiple AIMessages (such as the background step
    # in interrupt-agent, or a tool step in research-assistant), it's omitted. Arguably,
    # you'd want to include it. You could update the API to return a list of ChatMessages
    # in that case.
    agent: AgentGraph = get_agent(agent_id)
    kwargs = await handle_input(user_input, agent)

    try:
        response_events: list[tuple[str, Any]] = await agent.ainvoke(
            **kwargs,
            stream_mode=["updates", "values"],  # type: ignore
        )
        response_type, response = response_events[-1]
        if response_type == "values":
            # Normal response, the agent completed successfully
            output = langchain_to_chat_message(response["messages"][-1])
        elif response_type == "updates" and "__interrupt__" in response:
            # The last thing to occur was an interrupt
            # Return the value of the first interrupt as an AIMessage
            output = langchain_to_chat_message(
                AIMessage(content=response["__interrupt__"][0].value)
            )
        else:
            raise ValueError(f"Unexpected response type: {response_type}")

        return output
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


@api_router.post("/{agent_id}/history")
async def history(
    input: ChatHistoryInput, agent_id: str = DEFAULT_AGENT
) -> ChatHistory:
    """
    Get chat history.
    """
    agent: AgentGraph = get_agent(agent_id)
    config = RunnableConfig({"configurable": {"thread_id": input.thread_id}})
    try:
        state_snapshot = await agent.aget_state(config=config)
        messages: list[AnyMessage] = state_snapshot.values.get("messages", [])
        chat_messages: list[ChatMessage] = [
            langchain_to_chat_message(m) for m in messages
        ]
        return ChatHistory(messages=chat_messages)
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


@api_router.get("/agent-info")
async def agent_info() -> AgentInfoMetadata:
    return AgentInfoMetadata(agents=get_all_agent_info(), default_agent=DEFAULT_AGENT)
