from __future__ import annotations

import re

from app.services.conversation.contracts import (
    ConversationRecallResult,
    ConversationTurn,
    ConversationWindow,
)


_USER_ONLY_RE = re.compile(
    r"(?:我|用户).*(?:说|讲|问|告诉)|我刚才|我上面|what did i",
    re.IGNORECASE,
)


def recall_recent_conversation(
    window: ConversationWindow,
    *,
    query: str,
    limit: int = 4,
) -> ConversationRecallResult:
    """Render recent thread messages without consulting durable memory."""

    requested = max(1, min(int(limit), 8))
    source = window.user_turns if _USER_ONLY_RE.search(query) else window.turns
    selected = source[-requested:]
    if not selected:
        return ConversationRecallResult(
            status="empty",
            answer="当前会话里没有更早的消息可供回顾。",
        )

    if all(turn.role == "user" for turn in selected):
        if len(selected) == 1:
            answer = f"你刚才说：“{selected[0].content}”"
        else:
            rendered = "；随后说".join(f"“{turn.content}”" for turn in selected)
            answer = f"你之前说了{rendered}。"
    else:
        lines = [
            f"{'你' if turn.role == 'user' else '我'}：{turn.content}"
            for turn in selected
        ]
        answer = "当前会话最近的内容是：\n" + "\n".join(
            f"- {line}" for line in lines
        )
    return ConversationRecallResult(turns=selected, answer=answer)
