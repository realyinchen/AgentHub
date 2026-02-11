from uuid import UUID
import httpx
import json
from collections.abc import AsyncGenerator, Generator
from typing import List
from pydantic import TypeAdapter

from app.core.config import settings
from app.schemas.agent import AgentInDB
from app.schemas.chat import (
    ChatHistory,
    ChatMessage,
    ConversationCreate,
    ConversationInDB,
    UserInput,
    ConversationUpdate,
)


class AgentClient:
    """Client for interacting with the agent service."""

    def __init__(
        self, base_url: str = "http://0.0.0.0:8080", timeout: float | None = None
    ) -> None:
        """
        Initialize the client.

        Args:
            base_url (str): The base URL of the agent service.
            timeout (float, optional): The timeout for requests.
        """
        self.base_url = base_url
        self.timeout = timeout
        self.agent_id: str = "chatbot"
        self.url = f"{self.base_url}{settings.API_V1_STR}"

        try:
            response = httpx.get(
                f"{self.url}/agents/",
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error getting available agents: {e}")

        type_adapter = TypeAdapter(List[AgentInDB])
        self.available_agents = type_adapter.validate_python(response.json())

    def invoke(self, message: str, thread_id: UUID | None = None) -> ChatMessage:
        """
        Invoke the agent asynchronously. Only the final message is returned.

        Args:
            message (str): The message to send to the agent
            thread_id (UUID, optional): Thread ID for continuing a conversation

        Returns:
            AnyMessage: The response from the agent
        """
        request = UserInput(
            content=message, agent_id=self.agent_id, thread_id=thread_id
        )

        try:
            response = httpx.post(
                f"{self.url}/chat/invoke",
                json=request.model_dump(),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error: {e}")

        return ChatMessage.model_validate(response.json())

    async def ainvoke(self, message: str, thread_id: UUID | None = None) -> ChatMessage:
        """
        Invoke the agent asynchronously. Only the final message is returned.

        Args:
            message (str): The message to send to the agent
            thread_id (UUID, optional): Thread ID for continuing a conversation

        Returns:
            AnyMessage: The response from the agent
        """
        request = UserInput(
            content=message, agent_id=self.agent_id, thread_id=thread_id
        )

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.url}/chat/invoke",
                    json=request.model_dump(),
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise AgentClientError(f"Error: {e}")

        return ChatMessage.model_validate(response.json())

    def _parse_stream_line(self, line: str) -> ChatMessage | str | None:
        line = line.strip()
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                return None
            try:
                parsed = json.loads(data)
            except Exception as e:
                raise Exception(f"Error JSON parsing message from server: {e}")
            match parsed["type"]:
                case "message":
                    # Convert the JSON formatted message to an AnyMessage
                    try:
                        return ChatMessage.model_validate(parsed["content"])
                    except Exception as e:
                        raise Exception(f"Server returned invalid message: {e}")
                case "token":
                    # Yield the str token directly
                    return parsed["content"]
                case "error":
                    error_msg = "Error: " + parsed["content"]
                    return ChatMessage(type="ai", content=error_msg)
        return None

    def stream(
        self,
        message: str,
        thread_id: UUID | None = None,
    ) -> Generator[ChatMessage | str, None, None]:
        """
        Stream the agent's response synchronously.

        Each intermediate message of the agent process is yielded as a ChatMessage.
        If stream_tokens is True (the default value), the response will also yield
        content tokens from streaming models as they are generated.

        Args:
            message (str): The message to send to the agent
            thread_id (UUID, optional): Thread ID for continuing a conversation

        Returns:
            Generator[ChatMessage | str, None, None]: The response from the agent
        """
        request = UserInput(
            content=message, agent_id=self.agent_id, thread_id=thread_id
        )
        try:
            with httpx.stream(
                "POST",
                f"{self.url}/chat/stream",
                json=request.model_dump(),
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.strip():
                        parsed = self._parse_stream_line(line)
                        if parsed is None:
                            break
                        yield parsed
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error: {e}")

    async def astream(
        self,
        message: str,
        thread_id: UUID | None = None,
    ) -> AsyncGenerator[ChatMessage | str, None]:
        """
        Stream the agent's response asynchronously.

        Each intermediate message of the agent process is yielded as an AnyMessage.
        If stream_tokens is True (the default value), the response will also yield
        content tokens from streaming modelsas they are generated.

        Args:
            message (str): The message to send to the agent
            thread_id (UUID, optional): Thread ID for continuing a conversation

        Returns:
            AsyncGenerator[ChatMessage | str, None]: The response from the agent
        """
        request = UserInput(
            content=message, agent_id=self.agent_id, thread_id=thread_id
        )
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.url}/chat/stream",
                    json=request.model_dump(mode="json"),
                    timeout=self.timeout,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            parsed = self._parse_stream_line(line)
                            if parsed is None:
                                break
                            # Don't yield empty string tokens as they cause generator issues
                            if parsed != "":
                                yield parsed
            except httpx.HTTPError as e:
                raise AgentClientError(f"Error: {e}")

    def get_history(self, thread_id: UUID | None = None) -> ChatHistory:
        """
        Get chat history.

        Args:
            thread_id (UUID, optional): Thread ID for identifying a conversation
        """
        try:
            response = httpx.get(
                f"{self.url}/chat/history/{self.agent_id}/{thread_id}",
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error: {e}")

        return ChatHistory.model_validate(response.json())

    def get_conversation_title(self, thread_id: UUID) -> str:
        """
        Get the title of a conversation.

        Args:
            thread_id (UUID): The thread ID of the conversation

        Returns:
            str: The title of the conversation
        """
        try:
            response = httpx.get(
                f"{self.url}/chat/title/{thread_id}",
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()["title"]
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error getting conversation title: {e}")

    async def aget_conversation_title(self, thread_id: UUID) -> str:
        """
        Get the title of a conversation asynchronously.

        Args:
            thread_id (str): The thread ID of the conversation

        Returns:
            str: The title of the conversation
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.url}/chat/title/{thread_id}",
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()["title"]
            except httpx.HTTPError as e:
                raise AgentClientError(f"Error getting conversation title: {e}")

    def set_conversation_title(self, thread_id: UUID, title: str) -> None:
        """
        Set or update the title of a conversation.

        Args:
            thread_id (UUID): The thread ID of the conversation
            title (str): The title to set for the conversation
        """
        request = ConversationUpdate(thread_id=thread_id, title=title, is_deleted=False)
        try:
            response = httpx.post(
                f"{self.url}/chat/title",
                json=request.model_dump(mode="json"),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error setting conversation title: {e}")

    async def aset_conversation_title(self, thread_id: UUID, title: str) -> None:
        """
        Set or update the title of a conversation asynchronously.

        Args:
            thread_id (UUID): The thread ID of the conversation
            title (str): The title to set for the conversation
        """
        request = ConversationUpdate(thread_id=thread_id, title=title, is_deleted=False)
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.url}/chat/title",
                    json=request.model_dump(mode="json"),
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise AgentClientError(f"Error setting conversation title: {e}")

    def get_conversations(
        self, limit: int = 20, offset: int = 0
    ) -> List[ConversationInDB]:
        """
        Get a paginated list of recent conversations from the backend API.

        Args:
            limit: Maximum number of conversations to retrieve (default: 20)
            offset: Number of conversations to skip (default: 0)

        Returns:
            List of ConversationInDB objects

        Raises:
            AgentClientError: If the request fails
        """
        params = {
            "limit": limit,
            "offset": offset,
        }
        try:
            response = httpx.get(
                f"{self.url}/chat/conversations",
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()

            if isinstance(data, list):
                return [ConversationInDB.model_validate(item) for item in data]

            else:
                raise AgentClientError("Unexpected response format from API")
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error getting conversations: {e}")

    async def aget_conversations(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> List[ConversationInDB]:
        """
        Get a paginated list of recent conversations from the backend API asynchronously.

        Args:
            limit: Maximum number of conversations to retrieve (default: 20)
            offset: Number of conversations to skip (default: 0)

        Returns:
            List of ConversationInDB objects

        Raises:
            AgentClientError: If the request fails
        """
        params = {
            "limit": limit,
            "offset": offset,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.url}/chat/conversations",
                    params=params,
                    timeout=self.timeout,
                )
                response.raise_for_status()

                data = response.json()

                if isinstance(data, list):
                    return [ConversationInDB.model_validate(item) for item in data]

                else:
                    raise AgentClientError("Unexpected response format from API")

        except Exception as e:
            raise AgentClientError(f"Error getting conversations: {e}")

    def create_conversation(self, thread_id: UUID, title: str) -> ConversationInDB:
        """
        Create a new conversation in DB.

        Args:
            thread_id (UUID): The thread ID of the conversation
            title (str): The title to set for the conversation

        Returns:
            ConversationInDB object

        Raises:
            AgentClientError: If the request fails
        """
        request = ConversationCreate(thread_id=thread_id, title=title)
        try:
            response = httpx.post(
                f"{self.url}/chat/conversations",
                json=request.model_dump(mode="json"),
                timeout=self.timeout,
            )
            response.raise_for_status()

            return ConversationInDB.model_validate(response.json())
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error creating conversations: {e}")

    async def acreate_conversation(
        self, thread_id: UUID, title: str
    ) -> ConversationInDB:
        """
        Create a new conversation in DB asynchronously.

        Args:
            thread_id (UUID): The thread ID of the conversation
            title (str): The title to set for the conversation

        Returns:
            ConversationInDB object

        Raises:
            AgentClientError: If the request fails
        """
        request = ConversationCreate(thread_id=thread_id, title=title)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.url}/chat/conversations",
                    json=request.model_dump(mode="json"),
                    timeout=self.timeout,
                )
                response.raise_for_status()

                return ConversationInDB.model_validate(response.json())
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error creating conversations: {e}")


class AgentClientError(Exception):
    pass
