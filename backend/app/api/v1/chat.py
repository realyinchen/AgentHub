import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List

from app.database import adb_manager
from app.schemas.chat import (
    ConversationCreate,
    ConversationInDB,
    ConversationUpdate,
    ChatMessage,
    UserInput,
    ChatHistory,
)
from app.schemas.title import TitleGenerateRequest, TitleGenerateResponse
from app.utils.agent_utils import get_agent
from app.utils.llm import is_thinking_mode_available
from app.core.config import settings
from app.core.model_manager import ModelManager
from app.utils.message_utils import (
    handle_input,
    langchain_to_chat_message,
    streaming_message_generator,
)
from app.crud.chat import (
    read_conversation_by_thread_id,
    update_conversation_by_thread_id,
    list_conversations,
    create_conversation,
)
from app.crud import message_step as message_step_crud


logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/chat", tags=["Chat"])


async def get_db():
    """Dependency to provide async session"""
    async with adb_manager.session() as session:
        yield session


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
    "/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
)
async def stream(user_input: UserInput) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.

    Set `thinking_mode=true` to enable thinking mode for models that support it
    (e.g., DeepSeek-R1, Qwen3). This requires THINKING_LLM_NAME to be configured.
    """
    agent_id = user_input.agent_id
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    logger.info(
        "stream endpoint called: agent_id=%s, thread_id=%s, thinking_mode=%s",
        agent_id,
        user_input.thread_id,
        user_input.thinking_mode,
    )

    agent: CompiledStateGraph = await get_agent(agent_id)
    return StreamingResponse(
        streaming_message_generator(user_input, agent),
        media_type="text/event-stream",
        headers={
            # Help intermediaries keep SSE unbuffered for true token streaming.
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@api_router.post("/invoke")
async def invoke(user_input: UserInput) -> ChatMessage:
    """
    Async invoke an agent with user input to retrieve a final response.

    Use thread_id to persist and continue a multi-turn conversation.
    """

    agent_id = user_input.agent_id
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    agent: CompiledStateGraph = await get_agent(agent_id)
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


def _collect_tool_calls_for_final_response(
    messages: list[AnyMessage], final_ai_index: int
) -> list[dict[str, Any]]:
    """
    Collect all tool calls from preceding AI messages that belong to a final AI response.

    In LangGraph execution flow:
    1. User sends a message
    2. AI responds with tool_calls (intermediate message)
    3. Tool executes and returns ToolMessage
    4. AI generates final response (with content)

    This function looks backward from the final AI response to find all tool calls
    and their corresponding results, preserving the original call order.
    """
    tool_info_list: list[dict[str, Any]] = []
    tool_call_id_to_output: dict[str, str] = {}

    # First, build mapping from tool_call_id to tool output by scanning all ToolMessages
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_call_id = msg.tool_call_id
            if tool_call_id:
                content = msg.content
                if isinstance(content, str):
                    output = content
                elif isinstance(content, list):
                    output = "".join(
                        item.get("text", str(item))
                        if isinstance(item, dict)
                        else str(item)
                        for item in content
                    )
                else:
                    output = str(content)
                if len(output) > 2000:
                    output = output[:2000] + "..."
                tool_call_id_to_output[tool_call_id] = output

    # Collect all tool calls from preceding AI messages, preserving order
    # Since we scan backward, we need to:
    # 1. For each AIMessage, collect its tool_calls in reverse order
    # 2. Then reverse the entire list at the end
    # This gives us the correct final order
    temp_tool_calls: list[dict[str, Any]] = []

    for i in range(final_ai_index - 1, -1, -1):
        msg = messages[i]

        if isinstance(msg, HumanMessage):
            # Stop when we reach the user's message
            break

        if isinstance(msg, AIMessage):
            # Found an intermediate AI message with tool_calls
            if msg.tool_calls:
                # Collect tool calls from this AIMessage in reverse order
                # because we're scanning backward
                batch_tool_calls: list[dict[str, Any]] = []
                for tool_call in msg.tool_calls:
                    # Handle both dict and object types for tool_call
                    if isinstance(tool_call, dict):
                        tool_call_id = str(tool_call.get("id", "") or "")
                        tool_name = str(tool_call.get("name", "unknown") or "unknown")
                        tool_args = tool_call.get("args") or {}
                    else:
                        tool_call_id = str(getattr(tool_call, "id", "") or "")
                        tool_name = str(
                            getattr(tool_call, "name", "unknown") or "unknown"
                        )
                        tool_args = getattr(tool_call, "args", {}) or {}

                    if tool_call_id:
                        tool_info = {
                            "name": tool_name,
                            "id": tool_call_id,
                            "args": tool_args,
                            "output": tool_call_id_to_output.get(tool_call_id),
                        }
                        batch_tool_calls.append(tool_info)

                # Reverse this batch and add to temp list
                # This ensures tool calls within the same AIMessage stay in correct order
                batch_tool_calls.reverse()
                temp_tool_calls.extend(batch_tool_calls)

    # Reverse the entire list to get the original call order (first call first)
    temp_tool_calls.reverse()

    # Add order field to each tool call
    for order, tool_info in enumerate(temp_tool_calls):
        tool_info["order"] = order
        tool_info_list.append(tool_info)

    return tool_info_list


def _extract_thinking_from_ai_message(msg: AIMessage) -> str | None:
    """Extract thinking content from an AI message."""
    thinking = ""

    # 1. Check structured content (DashScope thinking models)
    if isinstance(msg.content, list):
        thinking_blocks = []
        for block in msg.content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                content = block.get("thinking", "")
                if content:
                    thinking_blocks.append(content)
        thinking = "".join(thinking_blocks)

    # 2. Check reasoning_content attribute (DeepSeek-R1 style)
    if not thinking:
        reasoning_attr = getattr(msg, "reasoning_content", None)
        if reasoning_attr:
            if isinstance(reasoning_attr, str):
                thinking = reasoning_attr
            elif isinstance(reasoning_attr, list):
                thinking = "".join(
                    item.get("text", str(item)) if isinstance(item, dict) else str(item)
                    for item in reasoning_attr
                )

    # 3. Check additional_kwargs for reasoning_content
    if not thinking:
        reasoning_from_kwargs = msg.additional_kwargs.get("reasoning_content", "")
        if reasoning_from_kwargs:
            thinking = reasoning_from_kwargs

    return thinking.strip() if thinking.strip() else None


def _convert_message_content_to_string(content: str | list | dict) -> str:
    """Convert message content to string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif isinstance(item, dict) and item.get("type") == "thinking":
                # Skip thinking blocks in content conversion
                pass
            else:
                text_parts.append(str(item))
        return "".join(text_parts)
    return str(content)


@api_router.get("/history/{agent_id}/{thread_id}")
async def history(
    agent_id: str | None = None,
    thread_id: UUID | None = None,
) -> ChatHistory:
    """
    Get chat history with message sequence for sidebar.

    Reads from both:
    - message_steps table: Complete message sequence for sidebar display
    - checkpointer: Main chat messages (human and final AI)

    Returns:
        - messages: Human and final AI messages for main chat UI
        - message_sequence: All messages as steps for sidebar display
    """
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    if not thread_id:
        return ChatHistory(messages=[], message_sequence=[])

    try:
        # Get message steps from database for sidebar
        async with adb_manager.session() as session:
            message_sequence = await message_step_crud.get_message_steps_by_thread(
                db=session, thread_id=thread_id
            )

        # Get messages from checkpointer for main chat UI
        agent: CompiledStateGraph = await get_agent(agent_id)
        config = RunnableConfig({"configurable": {"thread_id": thread_id}})
        state_snapshot = await agent.aget_state(config=config)
        messages: list[AnyMessage] = state_snapshot.values.get("messages", [])

        # Build messages for main chat UI: only human and final AI messages
        chat_messages: list[ChatMessage] = []

        for i, msg in enumerate(messages):
            # Skip ToolMessage - not shown in main chat
            if isinstance(msg, ToolMessage):
                continue

            # For AIMessage: only include if it has content and no tool_calls
            if isinstance(msg, AIMessage):
                if msg.tool_calls:
                    continue
                if not msg.content or not str(msg.content).strip():
                    continue

            chat_message = langchain_to_chat_message(msg)

            # For final AI messages, collect tool info from preceding messages
            if isinstance(msg, AIMessage) and msg.content and str(msg.content).strip():
                tool_info = _collect_tool_calls_for_final_response(messages, i)
                if tool_info:
                    chat_message.custom_data["tool_info"] = tool_info

            chat_messages.append(chat_message)

        return ChatHistory(messages=chat_messages, message_sequence=message_sequence)

    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


@api_router.get("/title/{thread_id}")
async def get_conversation_title(
    thread_id: UUID | None = None, db: AsyncSession = Depends(get_db)
) -> ConversationInDB | None:
    """Get the title of a conversation.

    Args:
        thread_id: The thread ID of the conversation

    Returns:
        Dictionary containing the conversation title
    """
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is not provided")

    try:
        return await read_conversation_by_thread_id(db=db, thread_id=thread_id)
    except Exception as e:
        logger.error(f"Error retrieving conversation title for thread {thread_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving conversation title: {str(e)}"
        )


@api_router.post("/title")
async def update_conversation_title(
    conversation_title: ConversationUpdate, db: AsyncSession = Depends(get_db)
) -> ConversationInDB | None:
    """
    Set or update the title of a conversation.
    """
    thread_id = conversation_title.thread_id
    title = conversation_title.title.strip()

    if not thread_id:
        raise HTTPException(
            status_code=400, detail="thread_id is required to set conversation title."
        )
    if not title:
        raise HTTPException(
            status_code=400, detail="title is required to set conversation title."
        )

    try:
        return await update_conversation_by_thread_id(
            db=db, update_data=conversation_title
        )
    except Exception as e:
        logger.error(f"Error setting conversation title: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error setting conversation title: {str(e)}"
        )


@api_router.get("/conversations")
async def get_conversations(
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of conversations to retrieve (1-100)",
    ),
    offset: int = Query(
        0, ge=0, description="Number of conversations to skip (for pagination)"
    ),
    db: AsyncSession = Depends(get_db),
) -> List[ConversationInDB]:
    """
    Get a list of recent conversations (most recently updated first).

    Returns a paginated list of conversations that are not deleted.
    Response includes X-Total-Count header with total number of conversations.
    """
    try:
        conversations, total = await list_conversations(
            db=db, limit=limit, offset=offset
        )

        # Return conversations with total count in header
        from fastapi.responses import JSONResponse

        response = JSONResponse(
            content=[conv.model_dump(mode="json") for conv in conversations],
            headers={"X-Total-Count": str(total)},
        )
        return response  # type: ignore

    except Exception as e:
        logger.error(f"Error retrieving conversations: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving conversations: {str(e)}"
        )


@api_router.post("/conversations", response_model=ConversationInDB)
async def save_conversation(
    conversation_in: ConversationCreate,
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB:
    """
    Create a conversation in DB.
    """
    try:
        return await create_conversation(db=db, conversation_in=conversation_in)
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error creating conversation: {str(e)}"
        )


@api_router.post("/title/generate", response_model=TitleGenerateResponse)
async def generate_title(request: TitleGenerateRequest) -> TitleGenerateResponse:
    """
    Generate a conversation title using the default LLM.

    This is a lightweight endpoint that directly uses LiteLLM
    without going through LangChain to avoid pydantic compatibility warnings.

    Args:
        request: Contains user_message and optional ai_response

    Returns:
        TitleGenerateResponse with the generated title
    """
    try:
        # Get the default LLM model ID
        model_id = ModelManager.get_default_llm_id()
        if not model_id:
            raise ValueError("No default LLM configured")

        # Get Router (direct LiteLLM, bypassing LangChain)
        router = await ModelManager.get_router()
        if not router:
            raise ValueError("Model router not initialized")

        # Build the prompt for title generation
        if request.ai_response:
            prompt = f"""Based on the following conversation, generate a concise title (max 20 characters, in the same language as the conversation):

User: {request.user_message[:200]}
AI: {request.ai_response[:200]}

Title:"""
        else:
            prompt = f"""Generate a concise title (max 20 characters, in the same language) for this message:

{request.user_message[:200]}

Title:"""

        # Direct LiteLLM call (bypassing LangChain to avoid pydantic warnings)
        resp = await router.acompletion(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract and clean the title
        content = resp.choices[0].message.content
        title = content.strip() if content else ""
        # Remove quotes if present (both single and double quotes)
        if title.startswith('"') and title.endswith('"'):
            title = title[1:-1]
        elif title.startswith("'") and title.endswith("'"):
            title = title[1:-1]
        # Limit length
        if len(title) > 50:
            title = title[:47] + "..."

        return TitleGenerateResponse(title=title)

    except Exception as e:
        logger.error(f"Error generating title: {e}")
        # Return a fallback title instead of raising an error
        # This ensures the frontend can continue without issues
        fallback = request.user_message[:30]
        if len(request.user_message) > 30:
            fallback += "..."
        return TitleGenerateResponse(title=fallback)


@api_router.get("/thinking-mode")
async def get_thinking_mode_status() -> dict[str, bool]:
    """
    Check if thinking mode is available.

    Returns:
        dict: {"available": bool} - Whether thinking mode is available
    """
    return {"available": is_thinking_mode_available()}


@api_router.get("/models")
async def get_available_models() -> dict[str, Any]:
    """
    Get all available models from .env configuration.

    A model is considered a "thinking" model if its model_name ends with "thinking".

    Returns:
        dict: {
            "models": [{"name": str, "is_thinking": bool}, ...],
            "default_model": str | null
        }
    """
    models = settings.get_model_info_list()
    default_model = settings.LLM_DEFAULT_MODEL
    return {"models": models, "default_model": default_model}
