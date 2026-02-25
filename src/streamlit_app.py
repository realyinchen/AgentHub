# type: ignore

import asyncio
import streamlit as st
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.schemas.chat import ChatMessage, ChatHistory
from agent_client import AgentClient, AgentClientError

# A Streamlit app for interacting with the langgraph agent via a simple chat interface.
# The app has three main functions which are all run async:

# - main() - sets up the streamlit app and high level structure
# - draw_messages() - draws a set of chat messages - either replaying existing messages
#   or streaming new ones.

# The app heavily uses AgentClient to interact with the agent's FastAPI endpoints.

APP_TITLE = "Agent Hub"
APP_ICON = ":material/experiment:"
AI_ICON = ":material/flare:"
USER_ICON = ":material/person:"
DEFAULT_CONVERSATION_TITLE = "New conversation"

st.logo(image="./agenthub.png", size="large")


async def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, menu_items={})

    if st.get_option("client.toolbarMode") != "minimal":
        st.set_option("client.toolbarMode", "minimal")
        await asyncio.sleep(0.1)
        st.rerun()

    if "agent_client" not in st.session_state:
        agent_url = f"http://{settings.HOST}:{settings.PORT}"
        st.session_state.agent_client = AgentClient(base_url=agent_url)
    agent_client: AgentClient = st.session_state.agent_client

    if "thread_id" not in st.session_state:
        thread_id = st.query_params.get("thread_id")
        if not thread_id:
            thread_id = str(uuid.uuid4())
            messages = []
            conversation_title = DEFAULT_CONVERSATION_TITLE
        else:
            try:
                messages: ChatHistory = agent_client.get_history(
                    thread_id=thread_id
                ).messages
                conversation_title = agent_client.get_conversation_title(
                    thread_id=thread_id
                )
            except AgentClientError as e:
                st.error(f"Error loading conversation: {e}")
                messages = []
                conversation_title = DEFAULT_CONVERSATION_TITLE
        st.session_state.messages = messages
        st.session_state.conversation_title = conversation_title
        st.session_state.thread_id = thread_id

    with st.sidebar:
        agent_list = [agent.agent_id for agent in agent_client.available_agents]
        agent_idx = agent_list.index(agent_client.agent_id)
        st.session_state.agent_id = st.selectbox(
            ":material/tune: Choose Your Agent Here",
            options=agent_list,
            index=agent_idx,
        )
        agent_client.agent_id = st.session_state.agent_id

        if st.button(
            label="**New conversation**",
            use_container_width=False,
            icon=":material/add:",
            type="tertiary",
            disabled=False,
        ):
            st.query_params.clear()
            st.session_state.messages = []
            st.session_state.conversation_title = DEFAULT_CONVERSATION_TITLE
            st.session_state.thread_id = str(uuid.uuid4())
            st.rerun()

        if st.session_state.get("editing_title", False):
            new_title = st.text_input(
                label="Conversation title",
                value=st.session_state.conversation_title,
                key="new_title_input",
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button(label="Save", key="save_title"):
                    agent_client.set_conversation_title(
                        thread_id=st.session_state.thread_id, title=new_title
                    )
                    st.session_state.conversation_title = new_title
                    st.session_state.editing_title = False
                    st.rerun()
            with col2:
                if st.button(label="Cancel", key="cancel_title"):
                    st.session_state.editing_title = False
                    st.rerun()

        try:
            conversations = agent_client.get_conversations(limit=100)
            if conversations:
                st.subheader(body="Recent")
                for conv in conversations:
                    thread_id_conv, title, updated_at = (
                        conv.thread_id,
                        conv.title,
                        conv.updated_at,
                    )
                    updated_date = updated_at.astimezone(
                        ZoneInfo("Asia/Shanghai")
                    )  # UTC time -> Aisa/Shanghai
                    date_str = updated_date.strftime("%d/%m/%Y %H:%M")

                    col1, col2, col3 = st.columns(
                        [90, 5, 5]
                    )  # Adjusted for potentially wider titles. 90:5:5 = 90% : 5% : 5%
                    with col1:
                        if st.button(
                            f"{title}",
                            key=f"conv_{thread_id_conv}",
                            help=f"Last updated: {date_str}",
                            type="tertiary",
                        ):
                            st.query_params["thread_id"] = thread_id_conv
                            st.rerun()
                    with col2:
                        if st.button(
                            ":material/edit:",
                            key=f"edit_{thread_id_conv}",
                            help="Edit conversation title",
                            type="tertiary",
                        ):
                            st.query_params["thread_id"] = thread_id_conv
                            st.session_state.editing_title = True
                            st.rerun()
                    with col3:
                        if st.button(
                            ":material/delete:",
                            key=f"delete_{thread_id_conv}",
                            help="Delete this conversation",
                            type="tertiary",
                        ):
                            if agent_client.delete_conversation(
                                thread_id=thread_id_conv
                            ):
                                if thread_id_conv == st.session_state.thread_id:
                                    st.query_params.clear()
                                st.rerun()
        except Exception as e:
            st.error(f"Error loading conversations: {e}")

    messages: list[ChatMessage] = st.session_state.messages or []
    if len(messages) == 0:
        with st.container(key="welcome-msg"):
            with st.chat_message("ai", avatar=AI_ICON):
                st.write(
                    "Welcome to AgentHub: experience all kinds of agents in one place!"
                )

    # draw_messages() expects an async iterator over messages
    async def amessage_iter() -> AsyncGenerator[ChatMessage, None]:
        for m in messages:
            yield m

    await draw_messages(amessage_iter())

    if user_input := st.chat_input("Type your message here..."):
        hide_welcome()
        user_msg = ChatMessage(type="human", content=user_input)
        st.session_state.messages.append(user_msg)
        st.chat_message("human", avatar=USER_ICON).write(user_input)

        try:
            await agent_client.acreate_conversation(
                thread_id=st.session_state.thread_id,
                title=st.session_state.conversation_title,
            )
            stream = agent_client.astream(
                message=user_input,
                thread_id=st.session_state.thread_id,
            )
            await draw_messages(stream, is_new=True)

            if (
                len(messages) > 1
                and st.session_state.conversation_title == DEFAULT_CONVERSATION_TITLE
            ):
                title_prompt = f"Generate a short title (< 50 chars) summarizing this conversation. First user message: {user_input}"
                agent_client.agent_id = "chatbot"
                try:
                    title_response = await agent_client.ainvoke(message=title_prompt)
                    generated_title = title_response.content.strip().strip("\"'")
                    await agent_client.aset_conversation_title(
                        thread_id=st.session_state.thread_id, title=generated_title
                    )
                    st.session_state.conversation_title = generated_title
                except Exception:
                    pass
                agent_client.agent_id = st.session_state.agent_id
            st.rerun()  # Clear stale containers
        except AgentClientError as e:
            st.error(f"Error generating response: {e}")
            st.stop()


async def draw_messages(
    messages_agen: AsyncGenerator[ChatMessage | str, None],
    is_new: bool = False,
) -> None:
    """
    Draws a set of chat messages - either replaying existing messages
    or streaming new ones.

    This function has additional logic to handle streaming tokens and tool calls.
    - Use a placeholder container to render streaming tokens as they arrive.
    - Use a status container to render tool calls. Track the tool inputs and outputs
      and update the status container accordingly.

    The function also needs to track the last message container in session state
    since later messages can draw to the same container.

    Args:
        messages_aiter: An async iterator over messages to draw.
        is_new: Whether the messages are new or not.
    """

    # Keep track of the last message container
    last_message_type = None
    st.session_state.last_message = None

    # Placeholder for intermediate streaming tokens
    streaming_content = ""
    streaming_placeholder = None

    # Iterate over the messages and draw them
    while msg := await anext(messages_agen, None):
        # str message represents an intermediate token being streamed
        if isinstance(msg, str):
            # If placeholder is empty, this is the first token of a new message
            # being streamed. We need to do setup.
            if not streaming_placeholder:
                if last_message_type != "ai":
                    last_message_type = "ai"
                    st.session_state.last_message = st.chat_message(
                        "ai", avatar=AI_ICON
                    )
                with st.session_state.last_message:
                    streaming_placeholder = st.empty()

            streaming_content += msg
            streaming_placeholder.write(streaming_content)
            continue
        if not isinstance(msg, ChatMessage):
            st.error(f"Unexpected message type: {type(msg)}")
            st.write(msg)
            st.stop()

        match msg.type:
            # A message from the user, the easiest case
            case "human":
                last_message_type = "human"
                st.chat_message("human", avatar=USER_ICON).write(msg.content)

            # A message from the agent is the most complex case, since we need to
            # handle streaming tokens and tool calls.
            case "ai":
                # If we're rendering new messages, store the message in session state
                if is_new:
                    st.session_state.messages.append(msg)

                # If the last message type was not AI, create a new chat message
                if last_message_type != "ai":
                    last_message_type = "ai"
                    st.session_state.last_message = st.chat_message(
                        "ai", avatar=AI_ICON
                    )

                with st.session_state.last_message:
                    # If the message has content, write it out.
                    # Reset the streaming variables to prepare for the next message.
                    if msg.content:
                        if streaming_placeholder:
                            streaming_placeholder.write(msg.content)
                            streaming_content = ""
                            streaming_placeholder = None
                        else:
                            st.write(msg.content)

                    if msg.tool_calls:
                        # Create a status container for each tool call and store the
                        # status container by ID to ensure results are mapped to the
                        # correct status container.
                        call_results = {}
                        for tool_call in msg.tool_calls:
                            label = f"""🛠️ Tool Call: {tool_call["name"]}"""

                            status = st.status(
                                label,
                                state="running" if is_new else "complete",
                            )
                            call_results[tool_call["id"]] = status

                        # Expect one ToolMessage for each tool call.
                        for tool_call in msg.tool_calls:
                            status = call_results[tool_call["id"]]
                            status.write("Input:")
                            status.write(tool_call["args"])
                            tool_result: ChatMessage = await anext(messages_agen)

                            if tool_result.type != "tool":
                                st.error(
                                    f"Unexpected ChatMessage type: {tool_result.type}"
                                )
                                st.write(tool_result)
                                st.stop()

                            # Record the message if it's new, and update the correct
                            # status container with the result
                            if is_new:
                                st.session_state.messages.append(tool_result)
                            if tool_result.tool_call_id:
                                status = call_results[tool_result.tool_call_id]
                            status.write("Output:")
                            status.write(tool_result.content)
                            status.update(state="complete")
            # In case of an unexpected message type, log an error and stop
            case _:
                st.error(f"Unexpected ChatMessage type: {msg.type}")
                st.write(msg)
                st.stop()


def hide_welcome():
    st.markdown(
        '<style>div[class*="st-key-welcome-msg"] { display: none; }</style>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
