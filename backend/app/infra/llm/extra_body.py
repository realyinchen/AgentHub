"""Provider-specific extra_body builder for thinking-mode control.

Builds the `extra_body` dict that LiteLLM passes to the underlying provider
API. Each provider has a different mechanism for enabling/disabling
reasoning/thinking mode.

IMPORTANT: When `thinking_enabled=False`, we MUST explicitly disable
reasoning to prevent LiteLLM from auto-enabling it based on model name.

Supported providers:
    - DashScope (Alibaba Cloud): `enable_thinking: bool`
    - ZhipuAI (zai):             `thinking: {type: enabled|disabled}`
    - DeepSeek:                  no extra params (R1 reasons by design)
    - OpenAI:                    `reasoning_effort: medium` for o1/o3 when on
    - Others:                    no params
"""


def build_extra_body(provider: str, thinking_enabled: bool) -> dict:
    """Build provider-specific `extra_body` for thinking-mode control.

    Args:
        provider: Provider name (e.g. "dashscope", "zai", "openai").
        thinking_enabled: Whether to enable thinking/reasoning mode.

    Returns:
        Dict to pass as `extra_body` to LiteLLM.
    """
    p = provider.lower()
    if "dashscope" in p:
        return {"enable_thinking": thinking_enabled}
    if "zai" in p or "zhipu" in p:
        return {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
    if "deepseek" in p:
        return {}
    if "openai" in p:
        return {"reasoning_effort": "medium"} if thinking_enabled else {}
    return {}
