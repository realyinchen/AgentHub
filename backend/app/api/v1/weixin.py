"""WeChat WebSocket endpoint for QR code login.

Simplified WebSocket endpoint that:
1. Gets QR code and sends to client
2. Polls for scan status (120s timeout)
3. On confirmed: creates user, returns JWT, starts message loop

Protocol (Server → Client):
    {"type": "qrcode", "qrcode": "xxx", "qrcode_img": "/api/v1/weixin/qrcode-image?url=..."}
    {"type": "scaned"}
    {"type": "confirmed", "token": "jwt-xxx", "thread_id": "uuid"}
    {"type": "expired"}
    {"type": "error", "message": "xxx"}
"""

import asyncio
import logging
import time
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.channels.weixin.service import get_weixin_service
from app.crud import (
    get_user_by_channel_user_id,
    create_user,
    get_or_create_user_channel,
)
from app.infra.database import get_database
from app.infra.security import create_access_token
from app.services.weixin_listener import create_listener


logger = logging.getLogger(__name__)

api_router = APIRouter(tags=["WeChat"])

# QR code timeout in seconds
QRCODE_TIMEOUT = 120


@api_router.get("/weixin/qrcode-image")
async def generate_qrcode_image(url: str):
    """Generate QR code image from WeChat official URL.

    Args:
        url: The WeChat official URL (qrcode_img_content) from WeChat API
             e.g. https://liteapp.weixin.qq.com/q/7GiQu1?qrcode=xxx&bot_type=3

    Returns:
        PNG image content
    """
    import qrcode as qrcode_lib
    from qrcode.constants import ERROR_CORRECT_L
    from io import BytesIO

    if not url:
        return Response(content="Missing url parameter", status_code=400)

    try:
        # Generate QR code from the WeChat official URL
        qr = qrcode_lib.QRCode(
            version=1,
            error_correction=ERROR_CORRECT_L,
            box_size=10,
            border=2,
        )
        qr.add_data(url)

        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to PNG bytes
        buffer = BytesIO()
        img.save(buffer, "PNG")
        image_data = buffer.getvalue()

        logger.debug(f"[WeChat] Generated QR code image, size: {len(image_data)} bytes")

        return Response(
            content=image_data,
            media_type="image/png",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )
    except Exception as e:
        logger.error(f"[WeChat] QR code generation error: {e}")
        return Response(content="QR code generation error", status_code=500)


@api_router.websocket("/ws/weixin/auth")
async def weixin_auth_websocket(websocket: WebSocket):
    """WebSocket endpoint for WeChat QR code login.

    Client connects → Server sends QR code → Client shows QR code
    → User scans → Server sends "scaned" → User confirms on phone
    → Server sends JWT + thread_id → Server starts message loop
    """
    await websocket.accept()
    weixin = get_weixin_service()

    logger.info("[WeChat WebSocket] Client connected")

    try:
        # 1. Get QR code
        qr_result = await weixin.get_qrcode()
        qrcode = qr_result.get("qrcode")
        qrcode_img = qr_result.get("qrcode_img_content", "")

        if not qrcode:
            await websocket.send_json(
                {"type": "error", "message": "Failed to get QR code"}
            )
            return

        # Generate QR code image URL using the WeChat official URL
        # The QR code should encode the full WeChat URL so user can scan and see login page
        proxy_img_url = f"/api/v1/weixin/qrcode-image?url={quote(qrcode_img, safe='')}"

        await websocket.send_json(
            {
                "type": "qrcode",
                "qrcode": qrcode,
                "qrcode_img": proxy_img_url,
            }
        )

        logger.info(f"[WeChat WebSocket] QR code sent: {qrcode[:20]}...")

        # 2. Poll for scan status
        start_time = time.time()
        current_base_url = weixin.base_url
        scanned_sent = False

        while time.time() - start_time < QRCODE_TIMEOUT:
            # Check if connection still alive
            try:
                # Non-blocking receive to detect disconnect
                data = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                # Handle verification code if needed (rare case)
                if data.get("type") == "verifycode":
                    # TODO: Handle verification code input
                    pass
            except asyncio.TimeoutError:
                pass  # No message, continue polling
            except WebSocketDisconnect:
                logger.info("[WeChat WebSocket] Client disconnected during polling")
                return

            # Poll QR code status
            try:
                status_result = await weixin.poll_status(
                    qrcode, base_url=current_base_url
                )
            except Exception as e:
                logger.error(f"[WeChat WebSocket] Poll status error: {e}")
                await asyncio.sleep(1)
                continue

            status = status_result.get("status", "")

            # Handle redirect
            if status == "scaned_but_redirect":
                redirect_host = status_result.get("redirect_host")
                if redirect_host:
                    current_base_url = f"https://{redirect_host}"
                    logger.info(f"[WeChat WebSocket] Redirected to: {current_base_url}")
                continue

            # Notify scanned
            if status == "scaned" and not scanned_sent:
                await websocket.send_json({"type": "scaned"})
                scanned_sent = True
                logger.info("[WeChat WebSocket] QR code scanned")

            # Login confirmed
            if status == "confirmed" or status_result.get("bot_token"):
                bot_token = status_result.get("bot_token")
                bot_base_url = (
                    status_result.get("baseurl")
                    or status_result.get("base_url")
                    or current_base_url
                )
                channel_user_id = status_result.get("ilink_user_id")

                if not bot_token or not channel_user_id:
                    await websocket.send_json(
                        {"type": "error", "message": "Login incomplete"}
                    )
                    return

                logger.info(f"[WeChat WebSocket] Login confirmed: {channel_user_id}")

                # 3. Create or get user
                user_id, thread_id = await _create_weixin_user(
                    channel_user_id, bot_token, bot_base_url
                )

                # 4. Generate JWT
                jwt_token = create_access_token(subject=str(user_id))

                await websocket.send_json(
                    {
                        "type": "confirmed",
                        "token": jwt_token,
                        "user_id": str(user_id),
                        "thread_id": str(thread_id),
                    }
                )

                logger.info(
                    f"[WeChat WebSocket] User created: {user_id}, thread: {thread_id}"
                )

                # 5. Start message loop (background task)
                asyncio.create_task(
                    create_listener(
                        bot_token=bot_token,
                        bot_base_url=bot_base_url,
                        user_id=user_id,
                        thread_id=thread_id,
                        channel_user_id=channel_user_id,
                    )
                )

                return  # WebSocket can be closed now

            # QR code expired
            if status == "expired":
                await websocket.send_json({"type": "expired"})
                logger.info("[WeChat WebSocket] QR code expired")
                return

            # Already connected
            if status == "binded_redirect" or status_result.get("binded_redirect"):
                # Reconnection case - treat as error for simplicity
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Already connected from another session",
                    }
                )
                return

            await asyncio.sleep(1)

        # Timeout
        await websocket.send_json({"type": "expired"})
        logger.info("[WeChat WebSocket] Login timeout")

    except WebSocketDisconnect:
        logger.info("[WeChat WebSocket] Client disconnected")
    except Exception as e:
        logger.error(f"[WeChat WebSocket] Error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass


async def _create_weixin_user(
    channel_user_id: str, bot_token: str, bot_base_url: str
) -> tuple[UUID, UUID]:
    """Create or get user from WeChat channel.

    Returns:
        (user_id, thread_id) where thread_id is user_channel.id
    """
    db = get_database()
    async with db.session() as session:
        # Check if user already exists
        user = await get_user_by_channel_user_id(session, "weixin", channel_user_id)

        if user is None:
            # Create new user
            user = await create_user(
                session,
                display_name=f"WeChat User",
                is_mock_user=False,
            )
            logger.info(f"[WeChat] Created new user: {user.id}")

        # Create or get channel binding
        user_channel = await get_or_create_user_channel(
            session,
            user_id=user.id,
            channel="weixin",
            channel_user_id=channel_user_id,
            channel_token=bot_token,
            channel_base_url=bot_base_url,
        )

        await session.commit()

        # Use user_channel.id as the fixed thread_id
        return user.id, user_channel.id
