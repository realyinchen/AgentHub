"""WeChat iLink Bot message listener.

Simplified service that only handles:
1. Message loop (getupdates → invoke → sendmessage)
2. 24-hour auto-reconnect via WeChat notification

WebSocket handling is in api/v1/weixin.py
"""

import asyncio
import logging
import time
from typing import Any
from uuid import UUID, uuid4

from app.channels.weixin.service import get_weixin_service
from app.infra.database import get_database
from app.schemas.chat import UserInput
from app.services.chat import ChatService
from app.crud.chat import get_or_create_conversation_by_thread_id


logger = logging.getLogger(__name__)


# Reconnect configuration (24-hour session)
RECONNECT_CONFIG = {
    "session_duration": 24 * 3600,
    "warning_before": 2 * 3600,
    "reminder_interval": 30 * 60,
    "force_before": 30 * 60,
    "qrcode_timeout": 120,
}


class WeixinListener:
    """WeChat message listener - handles message loop and reconnection.

    One instance per login session. Created after WebSocket login confirmed.
    """

    def __init__(
        self,
        bot_token: str,
        bot_base_url: str,
        user_id: UUID,
        thread_id: UUID,
        channel_user_id: str,
    ) -> None:
        self.bot_token = bot_token
        self.bot_base_url = bot_base_url
        self.user_id = user_id
        self.thread_id = thread_id
        self.channel_user_id = channel_user_id

        self.weixin = get_weixin_service()
        self._get_updates_buf = ""
        self._typing_ticket_cache: dict[str, str] = {}
        self._last_contact: dict[str, str | None] = {
            "from_id": None,
            "context_token": None,
        }
        self._login_time = time.time()
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start message loop and reconnect monitor."""
        if self._running:
            return

        self._running = True
        logger.info(
            f"[WeChat] Listener started: user={self.user_id}, thread={self.thread_id}"
        )

        self._tasks = [
            asyncio.create_task(self._message_loop()),
            asyncio.create_task(self._reconnect_loop()),
        ]

    async def stop(self) -> None:
        """Stop the listener."""
        self._running = False
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info(f"[WeChat] Listener stopped: user={self.user_id}")

    async def _message_loop(self) -> None:
        """Main message receiving and handling loop."""
        logger.info("[WeChat] Message loop started")

        while self._running:
            try:
                msgs = await self._get_updates()
                for msg in msgs:
                    asyncio.create_task(self._handle_message(msg))
            except Exception as e:
                logger.error(f"[WeChat] Message loop error: {e}")
                await asyncio.sleep(1)

    async def _get_updates(self) -> list[dict[str, Any]]:
        """Long-poll for incoming messages."""
        result = await self.weixin.get_updates(
            self.bot_token, self._get_updates_buf, self.bot_base_url
        )
        self._get_updates_buf = result.get("get_updates_buf") or self._get_updates_buf
        return result.get("msgs") or []

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """Handle a single incoming message."""
        # Only handle text messages (type 1)
        if msg.get("message_type") != 1:
            return

        text = msg.get("item_list", [{}])[0].get("text_item", {}).get("text", "")
        from_user_id = msg.get("from_user_id", "")
        context_token = msg.get("context_token", "")

        if not text or not from_user_id or not context_token:
            return

        logger.info(f"[WeChat] Received: {text[:50]}...")

        # Update last contact for reconnection notifications
        self._last_contact["from_id"] = from_user_id
        self._last_contact["context_token"] = context_token

        # Get typing ticket
        typing_ticket = await self._get_typing_ticket(from_user_id, context_token)

        # Send typing indicator
        if typing_ticket:
            await self.weixin.send_typing(
                self.bot_token, from_user_id, typing_ticket, 1, self.bot_base_url
            )

        try:
            db = get_database()
            async with db.session() as session:
                # Ensure Conversation exists for trace_executions foreign key
                await get_or_create_conversation_by_thread_id(
                    session,
                    thread_id=self.thread_id,
                    user_id=self.user_id,
                    title="微信对话",
                )

                # Invoke agent
                user_input = UserInput(
                    content=text,
                    user_id=self.user_id,
                    thread_id=self.thread_id,
                    request_id=f"weixin-{uuid4().hex[:8]}",
                    timezone="Asia/Shanghai",
                )

                service = ChatService()

                response = await service.invoke(session, user_input)

            # Send response
            await self.weixin.send_message(
                self.bot_token,
                from_user_id,
                context_token,
                response.content,
                self.bot_base_url,
            )
            logger.info(f"[WeChat] Sent: {response.content[:50]}...")

        except Exception as e:
            logger.error(f"[WeChat] Handle message error: {e}")
            await self.weixin.send_message(
                self.bot_token,
                from_user_id,
                context_token,
                "抱歉，处理消息时出现错误。",
                self.bot_base_url,
            )

        finally:
            if typing_ticket:
                await self.weixin.send_typing(
                    self.bot_token, from_user_id, typing_ticket, 2, self.bot_base_url
                )

    async def _get_typing_ticket(self, user_id: str, context_token: str) -> str:
        """Get typing ticket (cached per user, valid 24h)."""
        if user_id not in self._typing_ticket_cache:
            cfg = await self.weixin.get_config(
                self.bot_token, user_id, context_token, self.bot_base_url
            )
            self._typing_ticket_cache[user_id] = cfg.get("typing_ticket", "")
        return self._typing_ticket_cache.get(user_id, "")

    async def _reconnect_loop(self) -> None:
        """Monitor session expiry and handle reconnection via WeChat notification."""
        logger.info("[WeChat] Reconnect monitor started")

        while self._running:
            elapsed = time.time() - self._login_time
            remaining = RECONNECT_CONFIG["session_duration"] - elapsed

            if remaining <= RECONNECT_CONFIG["force_before"]:
                # Force reconnect - send notification via WeChat
                if (
                    self._last_contact["from_id"]
                    and self._last_contact["context_token"]
                ):
                    await self.weixin.send_message(
                        self.bot_token,
                        self._last_contact["from_id"],
                        self._last_contact["context_token"],
                        "⚠️ 连接即将到期，请回复 /重新连接 续期",
                        self.bot_base_url,
                    )

            elif remaining <= RECONNECT_CONFIG["warning_before"]:
                # Warning - send notification
                if (
                    self._last_contact["from_id"]
                    and self._last_contact["context_token"]
                ):
                    hours = remaining / 3600
                    await self.weixin.send_message(
                        self.bot_token,
                        self._last_contact["from_id"],
                        self._last_contact["context_token"],
                        f"⏰ 连接还剩约 {hours:.1f} 小时到期，回复 /重新连接 可提前续期",
                        self.bot_base_url,
                    )

            await asyncio.sleep(60)


# Active listeners by bot_token
_active_listeners: dict[str, WeixinListener] = {}


async def create_listener(
    bot_token: str,
    bot_base_url: str,
    user_id: UUID,
    thread_id: UUID,
    channel_user_id: str,
) -> WeixinListener:
    """Create and start a new listener."""
    listener = WeixinListener(
        bot_token=bot_token,
        bot_base_url=bot_base_url,
        user_id=user_id,
        thread_id=thread_id,
        channel_user_id=channel_user_id,
    )

    # Stop existing listener for this token if any
    if bot_token in _active_listeners:
        await _active_listeners[bot_token].stop()

    _active_listeners[bot_token] = listener
    await listener.start()

    return listener


async def stop_listener(bot_token: str) -> None:
    """Stop and remove a listener."""
    if bot_token in _active_listeners:
        await _active_listeners[bot_token].stop()
        del _active_listeners[bot_token]


def get_listener(bot_token: str) -> WeixinListener | None:
    """Get active listener by token."""
    return _active_listeners.get(bot_token)
