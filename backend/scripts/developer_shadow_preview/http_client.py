from __future__ import annotations

import uuid
from collections import Counter

import httpx
from pydantic import ValidationError

from app.schemas.chat import ChatMessage


SAFE_PROMPTS = (
    "\u4f60\u597d\uff0c\u8bf7\u7528\u4e00\u53e5\u7b80\u77ed\u7684\u8bdd\u56de\u5e94\u3002",
    "\u8bf7\u8ba1\u7b97 7 + 5\uff0c\u53ea\u7ed9\u51fa\u7ed3\u679c\u3002",
    "\u8bf7\u7528\u4e00\u53e5\u8bdd\u89e3\u91ca\u4ec0\u4e48\u662f\u5e42\u7b49\u3002",
    "\u8bf7\u5c06\u201c\u4fdd\u6301\u63a5\u53e3\u6e05\u6670\u201d\u6539\u5199\u5f97\u66f4\u7b80\u6d01\u3002",
    "\u8bf7\u5217\u51fa\u4e24\u4e2a\u5e38\u89c1\u7684\u5143\u97f3\u5b57\u6bcd\u3002",
    "\u8bf7\u7528\u5341\u4e2a\u5b57\u4ee5\u5185\u5b9a\u4e49\u6570\u636e\u5951\u7ea6\u3002",
    "\u4e0a\u4e00\u8f6e\u6211\u8bf7\u4f60\u5b9a\u4e49\u4e86\u4ec0\u4e48\uff1f",
    "\u8bf7\u7528\u4e00\u53e5\u8bdd\u8bf4\u660e\u8bfb\u64cd\u4f5c\u548c\u5199\u64cd\u4f5c\u7684\u533a\u522b\u3002",
    "\u8bf7\u628a\u201c\u5148\u6821\u9a8c\uff0c\u540e\u6267\u884c\u201d\u6362\u4e00\u79cd\u8bf4\u6cd5\u3002",
    "\u8bf7\u56de\u7b54\uff1a\u4e09\u89d2\u5f62\u6709\u51e0\u6761\u8fb9\uff1f",
    "\u521a\u624d\u54ea\u4e00\u8f6e\u63d0\u5230\u4e86\u8bfb\u64cd\u4f5c\u548c\u5199\u64cd\u4f5c\uff1f",
    "\u8bf7\u7528\u4e00\u53e5\u8bdd\u89e3\u91ca\u4ec0\u4e48\u662f\u4f9d\u8d56\u5173\u7cfb\u3002",
    "\u8bf7\u5c06 API \u6269\u5c55\u4e3a\u82f1\u6587\u5168\u79f0\u3002",
    "\u8bf7\u5224\u65ad\uff1a10 \u662f\u5426\u5927\u4e8e 8\uff1f",
    "\u8bf7\u7528\u4e00\u4e2a\u77ed\u8bed\u6982\u62ec\u201c\u5355\u4e00\u804c\u8d23\u201d\u3002",
    "\u6211\u4e0a\u4e00\u53e5\u8bf7\u4f60\u6982\u62ec\u7684\u662f\u4ec0\u4e48\uff1f",
    "\u8bf7\u7ed9\u201c\u53ef\u6062\u590d\u6267\u884c\u201d\u4e00\u4e2a\u7b80\u77ed\u7684\u540c\u4e49\u8868\u8fbe\u3002",
    "\u8bf7\u7528\u4e00\u53e5\u8bdd\u8bf4\u660e\u65e5\u5fd7\u7684\u4f5c\u7528\u3002",
    "\u8bf7\u8ba1\u7b97 9 - 4\uff0c\u53ea\u7ed9\u51fa\u7ed3\u679c\u3002",
    "\u8bf7\u7528\u4e00\u53e5\u7b80\u77ed\u7684\u8bdd\u7ed3\u675f\u672c\u6b21\u5bf9\u8bdd\u3002",
)


class DeveloperShadowHttpError(RuntimeError):
    """Fail-closed HTTP error with no response body or provider output."""


class DeveloperShadowHttpClient:
    """Send only the fixed, non-writing preview conversation over HTTP."""

    @staticmethod
    def parse_response_mode(payload: object, *, request_id: str) -> str:
        try:
            message = ChatMessage.model_validate(payload)
        except ValidationError as exc:
            raise DeveloperShadowHttpError(
                "http_response_invalid"
            ) from exc
        runtime_trace = message.custom_data.get("runtime_trace")
        traced_request_id = (
            runtime_trace.get("request_id")
            if isinstance(runtime_trace, dict)
            else None
        )
        response_request_id = message.request_id or traced_request_id
        if message.type != "ai" or response_request_id != request_id:
            raise DeveloperShadowHttpError(
                "http_response_contract_mismatch"
            )
        mode = str(
            message.custom_data.get("agent_mode") or "legacy_runtime"
        )
        if mode == "controller_v1":
            raise DeveloperShadowHttpError(
                "shadow_handled_main_response"
            )
        return mode

    @staticmethod
    def new_request_ids(turn_count: int) -> list[str]:
        run_id = uuid.uuid4().hex
        return [
            f"developer-shadow-{run_id}-{index + 1:02d}"
            for index in range(turn_count)
        ]

    @staticmethod
    def prompts(turn_count: int) -> list[str]:
        return [SAFE_PROMPTS[index % len(SAFE_PROMPTS)] for index in range(turn_count)]

    @staticmethod
    def request_payload(
        *,
        prompt: str,
        user_id: uuid.UUID,
        thread_id: uuid.UUID,
        request_id: str,
        model_id: uuid.UUID,
        configured_thinking: bool,
    ) -> dict[str, object]:
        return {
            "content": prompt,
            "user_id": str(user_id),
            "thread_id": str(thread_id),
            "request_id": request_id,
            "model_uuid": str(model_id),
            "thinking_mode": configured_thinking,
            "timezone": "Asia/Shanghai",
        }

    async def send(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        user_id: uuid.UUID,
        thread_id: uuid.UUID,
        model_id: uuid.UUID,
        configured_thinking: bool,
        request_ids: list[str],
    ) -> Counter[str]:
        prompts = self.prompts(len(request_ids))
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
        ) as client:
            health = await client.get("/health")
            if health.status_code != 200:
                raise DeveloperShadowHttpError("isolated_backend_unhealthy")
            modes: Counter[str] = Counter()
            for request_id, prompt in zip(request_ids, prompts, strict=True):
                response = await client.post(
                    "/api/v1/chat/invoke",
                    json=self.request_payload(
                        prompt=prompt,
                        user_id=user_id,
                        thread_id=thread_id,
                        request_id=request_id,
                        model_id=model_id,
                        configured_thinking=configured_thinking,
                    ),
                )
                if response.status_code != 200:
                    raise DeveloperShadowHttpError(
                        f"http_turn_rejected:{response.status_code}"
                    )
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise DeveloperShadowHttpError(
                        "http_response_invalid"
                    ) from exc
                mode = self.parse_response_mode(
                    payload,
                    request_id=request_id,
                )
                modes[mode] += 1
            return modes


__all__ = [
    "DeveloperShadowHttpClient",
    "DeveloperShadowHttpError",
    "SAFE_PROMPTS",
]
