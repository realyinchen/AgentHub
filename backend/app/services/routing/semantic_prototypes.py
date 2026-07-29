"""Immutable semantic prototype catalog for routing recall."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntentPrototype:
    intent: str
    domain: str
    phrases: tuple[str, ...]


PROTOTYPES: tuple[IntentPrototype, ...] = (
    IntentPrototype(
        intent="conversation_recall",
        domain="conversation",
        phrases=(
            "what did I just say",
            "what did you say earlier in this chat",
            "我刚才跟你说了什么",
            "回顾一下上面的对话",
        ),
    ),
    IntentPrototype(
        intent="memory_lookup",
        domain="memory",
        phrases=(
            "what do you remember about me",
            "what is my personal schedule",
            "我之前告诉过你的事情",
            "查询我的个人信息",
            "我平时什么时候做这件事",
        ),
    ),
    IntentPrototype(
        intent="weather_lookup",
        domain="weather",
        phrases=(
            "weather forecast",
            "will it rain today",
            "今天的天气预报",
            "气温和降雨",
        ),
    ),
    IntentPrototype(
        intent="external_lookup",
        domain="web",
        phrases=(
            "find the current official information",
            "latest news and current facts",
            "look up an address online",
            "搜索最新公开信息",
            "查一下官方网站和地址",
        ),
    ),
    IntentPrototype(
        intent="recommend_books",
        domain="books",
        phrases=(
            "recommend well reviewed books",
            "books similar to this one",
            "推荐最近口碑好的书",
            "找适合我的新书",
        ),
    ),
    IntentPrototype(
        intent="deep_research",
        domain="research",
        phrases=(
            "conduct deep research with verified sources",
            "produce a source backed research report",
            "深度搜索并给出证据",
            "做一份研究报告",
        ),
    ),
    IntentPrototype(
        intent="answer_question",
        domain="general",
        phrases=(
            "explain a stable concept",
            "how does this work",
            "解释一个概念和原理",
            "什么是递归",
        ),
    ),
)
