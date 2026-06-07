"""WeChat (iLink) channel module.

This module implements WeChat personal account authentication via Tencent's iLink API.
Based on the openclaw-weixin protocol: https://github.com/Tencent/openclaw-weixin
"""

from app.channels.weixin.service import WeixinService

__all__ = ["WeixinService"]
