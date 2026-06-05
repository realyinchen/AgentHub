"""WeChat iLink API service.

This module provides an async HTTP client for WeChat's iLink Bot API.
Based on the openclaw-weixin protocol: https://ilinkai.weixin.qq.com

Reference: https://github.com/Tencent/openclaw-weixin
"""

import base64
import json
import logging
import random
from urllib.parse import quote
from typing import Any

import aiohttp

from app.infra.config import get_settings

logger = logging.getLogger(__name__)

# SDK version info (based on openclaw-weixin 2.4.3)
CHANNEL_VERSION = "2.4.3"
ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = str((2 << 16) | (4 << 8) | 3)  # 131587
BOT_AGENT = "AgentHub/1.0.0 (python)"


class WeixinService:
    """WeChat iLink Bot API client.

    This class provides methods to interact with WeChat's iLink Bot API:
    - get_qrcode: Get login QR code
    - poll_status: Poll QR code scan status
    - get_updates: Long-poll for incoming messages
    - send_message: Send a message to a user
    - send_typing: Send typing indicator

    All methods are async and use aiohttp for HTTP requests.
    """

    def __init__(self, base_url: str | None = None):
        """Initialize the WeChat iLink service.

        Args:
            base_url: Optional custom base URL (defaults to config value)
        """
        self.base_url = base_url or get_settings().WEIXIN_ILINK_BASE_URL
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @staticmethod
    def _make_headers(token: str | None = None) -> dict[str, str]:
        """Generate request headers for iLink API.

        Args:
            token: Optional bot token for authenticated requests

        Returns:
            Dictionary of headers
        """
        uin = str(random.randint(0, 0xFFFFFFFF))
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(uin.encode()).decode(),
            "iLink-App-Id": ILINK_APP_ID,
            "iLink-App-ClientVersion": ILINK_APP_CLIENT_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _base_info() -> dict[str, str]:
        """Generate base_info for request body."""
        return {
            "channel_version": CHANNEL_VERSION,
            "bot_agent": BOT_AGENT,
        }

    async def _api_get(
        self, path: str, token: str | None = None, base_url: str | None = None
    ) -> dict[str, Any]:
        """Make a GET request to iLink API.

        Args:
            path: API endpoint path
            token: Optional bot token
            base_url: Optional custom base URL

        Returns:
            JSON response as dictionary
        """
        url = f"{base_url or self.base_url}/{path}"
        session = await self._get_session()

        try:
            async with session.get(url, headers=self._make_headers(token)) as resp:
                text = await resp.text()
                logger.debug(f"[GET {path}] HTTP {resp.status} → {text[:200]}")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {}
        except Exception as e:
            logger.error(f"[GET {path}] Request failed: {e}")
            raise

    async def _api_post(
        self,
        path: str,
        body: dict[str, Any],
        token: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Make a POST request to iLink API.

        Args:
            path: API endpoint path
            body: Request body
            token: Optional bot token
            base_url: Optional custom base URL

        Returns:
            JSON response as dictionary
        """
        url = f"{base_url or self.base_url}/{path}"
        session = await self._get_session()

        try:
            async with session.post(
                url, json=body, headers=self._make_headers(token)
            ) as resp:
                text = await resp.text()
                logger.debug(f"[POST {path}] HTTP {resp.status} → {text[:200]}")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {}
        except Exception as e:
            logger.error(f"[POST {path}] Request failed: {e}")
            raise

    async def get_qrcode(
        self, local_token_list: list[str] | None = None
    ) -> dict[str, Any]:
        """Get a login QR code.

        Returns a QR code ID and image URL that can be displayed to the user.

        Args:
            local_token_list: Optional list of existing tokens for reconnection

        Returns:
            Dictionary with qrcode and qrcode_img_content (URL)
        """
        body = {"local_token_list": local_token_list or []}

        # Try POST first (2.x style)
        try:
            data = await self._api_post("ilink/bot/get_bot_qrcode?bot_type=3", body)
            if data.get("qrcode"):
                return data
        except Exception as e:
            logger.warning(f"POST get_bot_qrcode failed: {e}")

        # Fallback to GET (1.x style)
        return await self._api_get("ilink/bot/get_bot_qrcode?bot_type=3")

    async def poll_status(
        self, qrcode: str, verify_code: str | None = None, base_url: str | None = None
    ) -> dict[str, Any]:
        """Poll QR code scan status.

        Args:
            qrcode: QR code ID from get_qrcode()
            verify_code: Optional verification code for pairing
            base_url: Optional custom base URL (for redirect handling)

        Returns:
            Status dictionary with possible keys:
            - status: "wait" | "scaned" | "confirmed" | "expired" | "scaned_but_redirect"
            - bot_token: Token after successful login
            - baseurl: API base URL after successful login
            - redirect_host: New host to poll (for scaned_but_redirect)
        """
        endpoint = f"ilink/bot/get_qrcode_status?qrcode={quote(qrcode, safe='')}"
        if verify_code:
            endpoint += f"&verify_code={quote(verify_code, safe='')}"

        return await self._api_get(endpoint, base_url=base_url)

    async def wait_for_login(
        self, qrcode: str, timeout_seconds: int = 120, base_url: str | None = None
    ) -> dict[str, Any]:
        """Wait for user to scan QR code and confirm login.

        This method polls the status until confirmed, expired, or timeout.

        Args:
            qrcode: QR code ID from get_qrcode()
            timeout_seconds: Maximum seconds to wait
            base_url: Optional custom base URL

        Returns:
            Dictionary with:
            - success: True if login confirmed
            - bot_token: Token (if success)
            - baseurl: API base URL (if success)
            - channel_user_id: WeChat user ID (if success)
            - error: Error message (if not success)
        """
        import asyncio
        import time

        start_time = time.time()
        current_base_url = base_url or self.base_url
        pending_verify_code = None

        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                return {"success": False, "error": "timeout"}

            try:
                result = await self.poll_status(
                    qrcode, pending_verify_code, current_base_url
                )
            except Exception as e:
                logger.error(f"Poll status failed: {e}")
                await asyncio.sleep(1)
                continue

            status = result.get("status", "")

            # Login confirmed
            if status == "confirmed" or result.get("bot_token"):
                return {
                    "success": True,
                    "bot_token": result.get("bot_token"),
                    "baseurl": result.get("baseurl")
                    or result.get("base_url")
                    or current_base_url,
                    "channel_user_id": result.get("ilink_user_id"),
                }

            # Already connected (reconnection case)
            if status == "binded_redirect" or result.get("binded_redirect"):
                return {"success": True, "already_connected": True}

            # QR code expired
            if status == "expired":
                return {"success": False, "error": "expired"}

            # Need to switch polling host
            if status == "scaned_but_redirect":
                redirect_host = result.get("redirect_host")
                if redirect_host:
                    current_base_url = f"https://{redirect_host}"
                    logger.info(f"Polling redirected to: {current_base_url}")
                continue

            # User scanned, waiting for confirmation
            if status == "scaned":
                if pending_verify_code and result.get("verify_code_accepted"):
                    pending_verify_code = None
                logger.info("QR code scanned, waiting for confirmation...")

            # Need verification code
            if status in ("need_verifycode", "verify_code_blocked") or result.get(
                "need_verifycode"
            ):
                if status == "verify_code_blocked":
                    return {"success": False, "error": "verify_code_blocked"}
                # In a real implementation, we'd need to prompt the user for the code
                # For WebSocket, this is handled by sending a message to the frontend
                return {
                    "success": False,
                    "error": "need_verifycode",
                    "retry": bool(pending_verify_code),
                }

            await asyncio.sleep(1)

        return {"success": False, "error": "unknown"}

    async def get_updates(
        self, token: str, get_updates_buf: str = "", base_url: str | None = None
    ) -> dict[str, Any]:
        """Long-poll for incoming messages.

        This method blocks for up to 35 seconds until a message arrives.

        Args:
            token: Bot token from successful login
            get_updates_buf: Cursor from previous call
            base_url: Optional custom base URL

        Returns:
            Dictionary with:
            - msgs: List of incoming messages
            - get_updates_buf: New cursor for next call
        """
        body = {
            "get_updates_buf": get_updates_buf,
            "base_info": self._base_info(),
        }
        return await self._api_post("ilink/bot/getupdates", body, token, base_url)

    async def get_config(
        self, token: str, user_id: str, context_token: str, base_url: str | None = None
    ) -> dict[str, Any]:
        """Get user configuration including typing_ticket.

        Args:
            token: Bot token
            user_id: WeChat user ID
            context_token: Context token from message
            base_url: Optional custom base URL

        Returns:
            Dictionary with typing_ticket for send_typing()
        """
        body = {
            "ilink_user_id": user_id,
            "context_token": context_token,
            "base_info": self._base_info(),
        }
        return await self._api_post("ilink/bot/getconfig", body, token, base_url)

    async def send_typing(
        self,
        token: str,
        user_id: str,
        typing_ticket: str,
        status: int = 1,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Send typing indicator.

        Args:
            token: Bot token
            user_id: WeChat user ID
            typing_ticket: Ticket from get_config()
            status: 1 = typing, 2 = stopped
            base_url: Optional custom base URL

        Returns:
            API response
        """
        body = {
            "ilink_user_id": user_id,
            "typing_ticket": typing_ticket,
            "status": status,
            "base_info": self._base_info(),
        }
        return await self._api_post("ilink/bot/sendtyping", body, token, base_url)

    async def send_message(
        self,
        token: str,
        to_user_id: str,
        context_token: str,
        text: str,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Send a text message to a user.

        Args:
            token: Bot token
            to_user_id: Target WeChat user ID
            context_token: Context token from received message
            text: Message text
            base_url: Optional custom base URL

        Returns:
            API response
        """
        client_id = f"agenthub-{random.randint(0, 0xFFFFFFFF):08x}"
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,  # Bot message
                "message_state": 2,  # FINISH (complete message)
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            },
            "base_info": self._base_info(),
        }
        return await self._api_post("ilink/bot/sendmessage", body, token, base_url)


# Global service instance
_weixin_service: WeixinService | None = None


def get_weixin_service() -> WeixinService:
    """Get or create the global WeixinService instance."""
    global _weixin_service
    if _weixin_service is None:
        _weixin_service = WeixinService()
    return _weixin_service
