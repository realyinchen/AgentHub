from __future__ import annotations

import re

from app.services.conversation.contracts import (
    ConversationExchange,
    ConversationReadRequest,
    ConversationReadResult,
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


def read_conversation(
    window: ConversationWindow,
    request: ConversationReadRequest,
) -> ConversationReadResult:
    """Read role-aware exchanges without guessing from query text."""

    exchanges = _project_exchanges(window)
    available = (
        [item for item in exchanges if item.assistant is not None]
        if request.target in {"assistant", "exchange"}
        else exchanges
    )
    requested = 1 if request.selection == "latest" else request.count
    selected = available[-requested:]
    if not selected:
        return ConversationReadResult(
            status="empty",
            target=request.target,
            answer="当前会话里没有符合条件的已发布对话。",
        )

    turns: list[ConversationTurn] = []
    if request.target == "user":
        turns = [item.user for item in selected]
        answer = _render_user_turns(turns)
    elif request.target == "assistant":
        turns = [
            item.assistant
            for item in selected
            if item.assistant is not None
        ]
        answer = _render_assistant_turns(turns)
    else:
        for item in selected:
            turns.append(item.user)
            if item.assistant is not None:
                turns.append(item.assistant)
        answer = _render_exchanges(selected)

    return ConversationReadResult(
        target=request.target,
        exchanges=selected,
        turns=turns,
        answer=answer,
    )


def _project_exchanges(window: ConversationWindow) -> list[ConversationExchange]:
    exchanges: list[ConversationExchange] = []
    for turn in window.turns:
        if turn.role == "user":
            exchanges.append(
                ConversationExchange(
                    user=turn,
                    assistant=None,
                    status="incomplete",
                )
            )
            continue
        if not exchanges or exchanges[-1].assistant is not None:
            continue
        exchanges[-1] = exchanges[-1].model_copy(
            update={"assistant": turn, "status": "completed"}
        )
    return exchanges


def _render_user_turns(turns: list[ConversationTurn]) -> str:
    if len(turns) == 1:
        return f"你刚才说：“{turns[0].content}”"
    return "你之前依次说了：\n" + "\n".join(
        f"{index}. {turn.content}"
        for index, turn in enumerate(turns, start=1)
    )


def _render_assistant_turns(turns: list[ConversationTurn]) -> str:
    if len(turns) == 1:
        return f"我刚才回答：“{turns[0].content}”"
    return "我之前依次回答：\n" + "\n".join(
        f"{index}. {turn.content}"
        for index, turn in enumerate(turns, start=1)
    )


def _render_exchanges(exchanges: list[ConversationExchange]) -> str:
    lines: list[str] = []
    for index, exchange in enumerate(exchanges, start=1):
        lines.append(f"{index}. 你说：{exchange.user.content}")
        if exchange.assistant is not None:
            lines.append(f"   我回答：{exchange.assistant.content}")
        else:
            lines.append("   这一轮没有已发布的完整回答。")
    return "最近的对话是：\n" + "\n".join(lines)
