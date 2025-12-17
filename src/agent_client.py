import httpx
import json
from collections.abc import AsyncGenerator, Generator
from typing import Any

from app.schema import ChatHistory, ChatHistoryInput, ChatMessage, UserInput


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

    def invoke(self, message: str, thread_id: str | None = None) -> ChatMessage:
        """
        Invoke the agent asynchronously. Only the final message is returned.

        Args:
            message (str): The message to send to the agent
            thread_id (str, optional): Thread ID for continuing a conversation

        Returns:
            AnyMessage: The response from the agent
        """
        request = UserInput(content=message)
        if thread_id:
            request.thread_id = thread_id

        try:
            response = httpx.post(
                f"{self.base_url}/api/v1/invoke",
                json=request.model_dump(),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error: {e}")

        return ChatMessage.model_validate(response.json())

    async def ainvoke(self, message: str, thread_id: str | None = None) -> ChatMessage:
        """
        Invoke the agent asynchronously. Only the final message is returned.

        Args:
            message (str): The message to send to the agent
            thread_id (str, optional): Thread ID for continuing a conversation

        Returns:
            AnyMessage: The response from the agent
        """
        request = UserInput(content=message)
        if thread_id:
            request.thread_id = thread_id

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/v1/invoke",
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
        resume: dict[str, Any] | Any | None = None,
        thread_id: str | None = None,
    ) -> Generator[ChatMessage | str, None, None]:
        """
        Stream the agent's response synchronously.

        Each intermediate message of the agent process is yielded as a ChatMessage.
        If stream_tokens is True (the default value), the response will also yield
        content tokens from streaming models as they are generated.

        Args:
            message (str): The message to send to the agent
            thread_id (str, optional): Thread ID for continuing a conversation

        Returns:
            Generator[ChatMessage | str, None, None]: The response from the agent
        """
        request = UserInput(content=message, resume=resume, thread_id=thread_id)
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/v1/stream",
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
        resume: dict[str, Any] | Any | None = None,
        thread_id: str | None = None,
    ) -> AsyncGenerator[ChatMessage | str, None]:
        """
        Stream the agent's response asynchronously.

        Each intermediate message of the agent process is yielded as an AnyMessage.
        If stream_tokens is True (the default value), the response will also yield
        content tokens from streaming modelsas they are generated.

        Args:
            message (str): The message to send to the agent
            model (str, optional): LLM model to use for the agent
            thread_id (str, optional): Thread ID for continuing a conversation

        Returns:
            AsyncGenerator[ChatMessage | str, None]: The response from the agent
        """
        request = UserInput(content=message, resume=resume, thread_id=thread_id)
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/v1/stream",
                    json=request.model_dump(),
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

    def get_history(self, thread_id: str) -> ChatHistory:
        """
        Get chat history.

        Args:
            thread_id (str, optional): Thread ID for identifying a conversation
        """
        request = ChatHistoryInput(thread_id=thread_id)
        try:
            response = httpx.post(
                f"{self.base_url}/api/v1/history",
                json=request.model_dump(),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentClientError(f"Error: {e}")

        return ChatHistory.model_validate(response.json())


class AgentClientError(Exception):
    pass
