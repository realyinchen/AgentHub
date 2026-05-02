"""Trace builder for Agent Kanban view.

This module builds structured AgentTrace from raw message_steps records,
using session_id as the turn boundary (1 session_id = 1 turn).
"""

import logging
from uuid import UUID
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict

from app.models.message_step import MessageStepRecord
from app.schemas.trace import (
    AgentTrace,
    AgentTurn,
    AIMessageInfo,
    ToolCall,
    ToolResultInfo,
    SubagentRun,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Turn Builder - Internal state management
# ============================================================================


class _TurnBuilder:
    """Turn builder (internal state management for one session_id group)."""

    def __init__(self, turn_id: str, session_id: str, started_at: datetime):
        self.turn_id = turn_id
        self.session_id = session_id
        self.started_at = started_at
        self.human_msg: Optional[str] = None
        self.ai_msgs: List[AIMessageInfo] = []  # All AI messages (with or without tool_calls)
        self.all_tool_calls: List[ToolCall] = []  # Accumulated tool_calls from all AI steps
        self.tools: List[ToolResultInfo] = []
        self.subagents: List[SubagentRun] = []
        self.final_response: Optional[AIMessageInfo] = None

    def set_human_msg(self, msg: str) -> None:
        """Set human message (first human in this session)."""
        if self.human_msg is None:
            self.human_msg = msg

    def add_ai_msg(self, ai_msg: AIMessageInfo) -> None:
        """Add AI message. If it has tool_calls, accumulate them.
        
        If this AI has no tool_calls and comes after some tools,
        it's likely the final response.
        """
        self.ai_msgs.append(ai_msg)
        if ai_msg.tool_calls:
            self.all_tool_calls.extend(ai_msg.tool_calls)

    def add_tool(self, tool: ToolResultInfo) -> None:
        """Add tool result."""
        self.tools.append(tool)

    def add_subagent(self, subagent: SubagentRun) -> None:
        """Add subagent run."""
        self.subagents.append(subagent)

    def set_final_response(self, response: AIMessageInfo) -> None:
        """Set final AI response (last AI without tool_calls)."""
        self.final_response = response

    def build(self) -> AgentTurn:
        """Build final AgentTurn."""
        # Calculate total latency
        total_latency = 0
        for ai_msg in self.ai_msgs:
            if ai_msg.latency_ms:
                total_latency += ai_msg.latency_ms
        for tool in self.tools:
            if tool.latency_ms:
                total_latency += tool.latency_ms
        for sa in self.subagents:
            total_latency += sa.latency_ms
        if self.final_response and self.final_response.latency_ms:
            total_latency += self.final_response.latency_ms

        # Determine aiMsg: use first AI message (typically with tool_calls)
        # If no AI messages but has final_response, use that
        ai_msg = self.ai_msgs[0] if self.ai_msgs else self.final_response
        if ai_msg is None:
            ai_msg = AIMessageInfo(content=None, thinking=None, tool_calls=[], model_name=None, latency_ms=None)
        
        # Override tool_calls with accumulated list (for multi-round tool calls)
        ai_msg = AIMessageInfo(
            content=ai_msg.content,
            thinking=ai_msg.thinking,
            tool_calls=self.all_tool_calls,  # All accumulated tool_calls
            model_name=ai_msg.model_name,
            latency_ms=ai_msg.latency_ms,
        )

        return AgentTurn(
            turn_id=self.turn_id,
            session_id=self.session_id,
            humanMsg=self.human_msg or "(No user message)",
            aiMsg=ai_msg,
            toolMsgs=self.tools,
            subagentRuns=self.subagents,
            isParallelTools=False,  # Set later
            aiFinalResponse=self.final_response,
            total_latency_ms=total_latency,
            started_at=self.started_at,
        )


# ============================================================================
# Main trace building algorithm (session_id based grouping)
# ============================================================================


def build_trace_from_steps(
    thread_id: UUID,
    steps: List[MessageStepRecord],
    title: str = "Untitled Conversation",
) -> AgentTrace:
    """Build structured AgentTrace from raw message_steps.

    Core algorithm: Group by session_id (1 session_id = 1 turn)
    
    Processing within each session_id group:
    1. First human message -> humanMsg
    2. AI with tool_calls -> accumulate tool_calls, add to aiMsgs
    3. Tool steps -> add to tools
    4. Consecutive parent_run_id steps -> pack as SubagentRun
    5. Last AI without tool_calls -> aiFinalResponse

    Args:
        thread_id: Conversation thread ID
        steps: List of raw MessageStepRecord
        title: Conversation title

    Returns:
        AgentTrace: Structured trace for Kanban view
    """
    if not steps:
        logger.debug(f"No steps provided for thread {thread_id}")
        return AgentTrace(
            thread_id=thread_id,
            title=title,
            turns=[],
            total_turns=0,
            total_tool_calls=0,
            total_subagent_calls=0,
            total_latency_ms=0,
        )

    logger.debug(f"Building trace for thread {thread_id} with {len(steps)} steps")

    # Step 1: Sort by step_number globally (ensure linear execution flow)
    sorted_steps = sorted(steps, key=lambda s: s.step_number)

    # Step 2: Group by session_id
    session_groups: Dict[str, List[MessageStepRecord]] = defaultdict(list)
    for step in sorted_steps:
        session_id_str = str(step.session_id)
        session_groups[session_id_str].append(step)

    logger.debug(f"Found {len(session_groups)} unique session_ids")

    # Step 3: Build Turn for each session_id group
    turns: List[AgentTurn] = []
    turn_counter = 1

    for session_id_str, group_steps in session_groups.items():
        # Sort group by step_number (should already be sorted, but ensure)
        group_steps = sorted(group_steps, key=lambda s: s.step_number)
        
        logger.debug(f"Processing session {session_id_str} with {len(group_steps)} steps")

        # Create TurnBuilder
        first_step = group_steps[0]
        turn_builder = _TurnBuilder(
            turn_id=f"turn-{turn_counter}",
            session_id=session_id_str,
            started_at=first_step.created_at or datetime.utcnow(),
        )

        # Track last AI without tool_calls for final response
        last_ai_no_tools: Optional[AIMessageInfo] = None

        # Process steps within group
        i = 0
        n = len(group_steps)

        while i < n:
            step = group_steps[i]

            # -----------------------------------------------------------------
            # Case A: Human message -> set human_msg
            # -----------------------------------------------------------------
            if step.message_type == "human":
                turn_builder.set_human_msg(step.content or "")
                logger.debug(f"  -> Human msg: {step.content[:50] if step.content else ''}...")
                i += 1
                continue

            # -----------------------------------------------------------------
            # Case B: Subagent steps -> pack consecutive parent_run_id steps
            # -----------------------------------------------------------------
            if step.parent_run_id:
                # Collect consecutive Subagent steps
                subagent_steps: List[MessageStepRecord] = []
                target_parent_run_id = step.parent_run_id

                while i < n and group_steps[i].parent_run_id == target_parent_run_id:
                    subagent_steps.append(group_steps[i])
                    i += 1

                # Build SubagentRun
                subagent_run = _build_subagent_run(subagent_steps, target_parent_run_id)
                turn_builder.add_subagent(subagent_run)
                logger.debug(
                    f"  -> Subagent detected: {subagent_run.name}, "
                    f"steps={len(subagent_steps)}, latency={subagent_run.latency_ms}ms"
                )
                continue

            # -----------------------------------------------------------------
            # Case C: AI message
            # -----------------------------------------------------------------
            if step.message_type == "ai":
                ai_msg = AIMessageInfo(
                    content=step.content,
                    thinking=step.thinking,
                    tool_calls=_parse_tool_calls(step.tool_calls) if step.tool_calls else [],
                    model_name=step.model_name,
                    latency_ms=step.latency_ms,
                )

                if step.tool_calls:
                    # AI with tool_calls -> add to ai_msgs, accumulate tool_calls
                    turn_builder.add_ai_msg(ai_msg)
                    logger.debug(
                        f"  -> AI with {len(ai_msg.tool_calls)} tool_calls"
                    )
                else:
                    # AI without tool_calls
                    # If there are already some tools processed, this is final response
                    # Otherwise, it's a simple AI response (add to ai_msgs)
                    if len(turn_builder.tools) > 0 or len(turn_builder.all_tool_calls) > 0:
                        # This is final response after tool calls
                        last_ai_no_tools = ai_msg
                        logger.debug(f"  -> Final AI response (no tool_calls)")
                    else:
                        # Simple conversation, no tools yet
                        # Could be the first/only AI message
                        turn_builder.add_ai_msg(ai_msg)
                        logger.debug(f"  -> AI message (no tool_calls, simple)")
                
                i += 1
                continue

            # -----------------------------------------------------------------
            # Case D: Tool -> add to turn
            # -----------------------------------------------------------------
            if step.message_type == "tool":
                tool_result = ToolResultInfo(
                    tool_call_id=step.tool_call_id,
                    name=step.tool_name or "unknown",
                    args=step.tool_args or {},
                    output=step.tool_output or "",
                    latency_ms=step.latency_ms,
                    status=(
                        "error"
                        if step.tool_output and "error" in step.tool_output.lower()
                        else "success"
                    ),
                )
                turn_builder.add_tool(tool_result)
                logger.debug(f"  -> Tool added: {step.tool_name}")
                i += 1
                continue

            # Unknown type, skip
            i += 1

        # Set final response if exists
        if last_ai_no_tools:
            turn_builder.set_final_response(last_ai_no_tools)

        # Build Turn
        turn = turn_builder.build()
        turns.append(turn)
        turn_counter += 1

    # -------------------------------------------------------------------------
    # Post-processing: parallel detection + tool result reordering
    # -------------------------------------------------------------------------
    for turn in turns:
        turn.isParallelTools = _detect_parallel_tools(
            turn.toolMsgs, turn.aiMsg.tool_calls if turn.aiMsg else []
        )
        if turn.aiMsg:
            turn.toolMsgs = _reorder_tool_results(turn.aiMsg.tool_calls, turn.toolMsgs)

    # -------------------------------------------------------------------------
    # Summary statistics
    # -------------------------------------------------------------------------
    total_tool_calls = sum(len(t.toolMsgs) for t in turns)
    total_subagent_calls = sum(len(t.subagentRuns) for t in turns)
    total_latency = sum(t.total_latency_ms for t in turns)

    trace = AgentTrace(
        thread_id=thread_id,
        title=title,
        turns=turns,
        total_turns=len(turns),
        total_tool_calls=total_tool_calls,
        total_subagent_calls=total_subagent_calls,
        total_latency_ms=total_latency,
    )

    logger.debug(
        f"Trace built successfully: {len(turns)} turns, "
        f"{total_tool_calls} tool calls, {total_subagent_calls} subagents, "
        f"{total_latency}ms total latency"
    )

    return trace


# ============================================================================
# Helper functions
# ============================================================================


def _parse_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[ToolCall]:
    """Parse tool_calls JSON into ToolCall objects."""
    return [
        ToolCall(
            name=tc.get("name", "unknown"),
            args=tc.get("args", {}),
            id=tc.get("id"),
        )
        for tc in tool_calls
    ]


def _build_subagent_run(
    subagent_steps: List[MessageStepRecord],
    parent_run_id: str,
) -> SubagentRun:
    """Pack consecutive subagent steps into black-box SubagentRun."""
    if not subagent_steps:
        return SubagentRun(
            name="unknown", input="", output="", latency_ms=0, step_count=0
        )

    first_step = subagent_steps[0]
    last_step = subagent_steps[-1]

    # Extract subagent name from tool_args or model_name
    name = "subagent"
    for step in subagent_steps:
        if step.tool_args and "agent_id" in step.tool_args:
            name = str(step.tool_args["agent_id"])
            break
        if step.model_name and "navigator" in step.model_name.lower():
            name = "navigator"
            break

    # Input: from first step content / thinking / tool_args
    if first_step.content:
        input_msg = first_step.content
    elif first_step.thinking:
        input_msg = first_step.thinking
    elif first_step.tool_args:
        input_msg = str(first_step.tool_args)
    else:
        input_msg = "(Subagent started)"

    # Output: from last step content / tool_output
    if last_step.content:
        output_msg = last_step.content
    elif last_step.tool_output:
        output_msg = last_step.tool_output
    else:
        output_msg = "(Subagent finished)"

    # Total latency: sum of all steps
    total_latency = sum(s.latency_ms or 0 for s in subagent_steps)

    return SubagentRun(
        name=name,
        input=input_msg[:500],  # Truncate to avoid excessive length
        output=output_msg[:1000],
        latency_ms=total_latency,
        step_count=len(subagent_steps),
    )


def _detect_parallel_tools(
    tool_results: List[ToolResultInfo],
    ai_tool_calls: List[ToolCall],
) -> bool:
    """Detect if tool calls were executed in parallel.

    Criteria (both must be satisfied):
    1. Number of tools >= 2
    2. Tool call_ids exist in ai_tool_calls (same LLM step)
    3. At least 2 distinct tool_call_ids (genuine parallelism)
    """
    if len(tool_results) < 2:
        return False

    # Get all call_ids from ai_tool_calls
    ai_call_ids = set(tc.id for tc in ai_tool_calls if tc.id)

    # Count matched distinct tool_call_ids in results
    matched_ids = set(
        t.tool_call_id
        for t in tool_results
        if t.tool_call_id and t.tool_call_id in ai_call_ids
    )

    return len(matched_ids) >= 2


def _reorder_tool_results(
    tool_calls: List[ToolCall],
    tool_results: List[ToolResultInfo],
) -> List[ToolResultInfo]:
    """Reorder tool results to match the order of aiMsg.tool_calls.

    This ensures Kanban view displays tools in the same order the AI called them.
    """
    if not tool_calls or not tool_results:
        return tool_results

    # Build call_id -> result mapping
    result_map: Dict[str, ToolResultInfo] = {
        t.tool_call_id: t for t in tool_results if t.tool_call_id
    }

    # Match in tool_calls order
    ordered: List[ToolResultInfo] = []
    for call in tool_calls:
        if call.id and call.id in result_map:
            ordered.append(result_map.pop(call.id))

    # Append unmatched results (no call_id or matching failed)
    matched_ids = set(t.tool_call_id for t in ordered if t.tool_call_id)
    for result in tool_results:
        if result.tool_call_id and result.tool_call_id not in matched_ids:
            ordered.append(result)
        elif not result.tool_call_id:
            ordered.append(result)

    return ordered


# ============================================================================
# Test functions
# ============================================================================


def _create_test_record(
    *,
    step_number: int,
    message_type: str,
    session_id: str = "00000000-0000-0000-0000-000000000001",
    content: str | None = None,
    thinking: str | None = None,
    tool_calls: list | None = None,
    tool_name: str | None = None,
    tool_args: dict | None = None,
    tool_output: str | None = None,
    tool_call_id: str | None = None,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    model_name: str | None = None,
    latency_ms: int | None = None,
) -> MessageStepRecord:
    """Create a test MessageStepRecord (in-memory only)."""
    return MessageStepRecord(
        thread_id="00000000-0000-0000-0000-000000000000",  # type: ignore
        session_id=session_id,  # type: ignore
        step_number=step_number,
        message_type=message_type,
        content=content,
        thinking=thinking,
        tool_calls=tool_calls,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_output=tool_output,
        tool_call_id=tool_call_id,
        run_id=run_id,
        parent_run_id=parent_run_id,
        model_name=model_name,
        latency_ms=latency_ms,
        created_at=datetime.utcnow(),
    )


def mock_scenario_simple() -> List[MessageStepRecord]:
    """Scenario 1: Simple conversation without tools."""
    return [
        _create_test_record(
            step_number=1,
            message_type="human",
            content="你好，介绍一下你自己",
        ),
        _create_test_record(
            step_number=2,
            message_type="ai",
            content="你好！我是一个智能助手，我可以帮助你回答问题、提供信息。",
            thinking="用户只是打招呼，我应该友好地回应",
            model_name="qwen-plus",
            latency_ms=450,
        ),
    ]


def mock_scenario_single_tool() -> List[MessageStepRecord]:
    """Scenario 2: Single tool call + final response."""
    return [
        _create_test_record(
            step_number=1,
            message_type="human",
            content="北京现在的天气怎么样？",
        ),
        _create_test_record(
            step_number=2,
            message_type="ai",
            tool_calls=[
                {
                    "name": "get_weather",
                    "args": {"city": "北京"},
                    "id": "call_abc123",
                }
            ],
            thinking="用户想知道北京的天气，我需要调用天气工具",
            model_name="qwen-plus",
            latency_ms=620,
        ),
        _create_test_record(
            step_number=3,
            message_type="tool",
            tool_name="get_weather",
            tool_args={"city": "北京"},
            tool_output="北京当前天气：晴，22°C，微风",
            tool_call_id="call_abc123",
            latency_ms=280,
        ),
        _create_test_record(
            step_number=4,
            message_type="ai",
            content="北京现在是晴天，气温 22°C，微风，天气不错适合外出！",
            thinking="工具返回了天气信息，我用自然语言总结给用户",
            model_name="qwen-plus",
            latency_ms=380,
        ),
    ]


def mock_scenario_multi_round_tools() -> List[MessageStepRecord]:
    """Scenario 3: Multi-round tool calls (like the Hefei example).
    
    User asks -> AI calls 2 tools -> AI calls 1 more tool -> Final response.
    All within same session_id.
    """
    session_id = "8035682a9a57407689acf56fb7e1515c"
    return [
        _create_test_record(
            step_number=1,
            session_id=session_id,
            message_type="human",
            content="明天合肥有什么新鲜事",
        ),
        _create_test_record(
            step_number=2,
            session_id=session_id,
            message_type="ai",
            tool_calls=[
                {"name": "get_current_time", "args": {"timezone_name": "Asia/Shanghai"}, "id": "call_8ce6"},
                {"name": "web_search", "args": {"query": "合肥 明天 活动"}, "id": "call_5894"},
            ],
            model_name="qwen-plus",
            latency_ms=620,
        ),
        _create_test_record(
            step_number=3,
            session_id=session_id,
            message_type="tool",
            tool_name="get_current_time",
            tool_call_id="call_8ce6",
            tool_output="2026-05-02 00:00:00 Asia/Shanghai",
            latency_ms=100,
        ),
        _create_test_record(
            step_number=4,
            session_id=session_id,
            message_type="tool",
            tool_name="web_search",
            tool_call_id="call_5894",
            tool_output="搜索结果：...",
            latency_ms=500,
        ),
        # Second round tool call
        _create_test_record(
            step_number=5,
            session_id=session_id,
            message_type="ai",
            tool_calls=[
                {"name": "web_search", "args": {"query": "合肥 2026年5月2日 活动"}, "id": "call_77c9"},
            ],
            model_name="qwen-plus",
            latency_ms=400,
        ),
        _create_test_record(
            step_number=6,
            session_id=session_id,
            message_type="tool",
            tool_name="web_search",
            tool_call_id="call_77c9",
            tool_output="更多搜索结果...",
            latency_ms=600,
        ),
        # Final response
        _create_test_record(
            step_number=7,
            session_id=session_id,
            message_type="ai",
            content="明天合肥有以下活动...",
            model_name="qwen-plus",
            latency_ms=300,
        ),
    ]


def mock_scenario_parallel_subagent() -> List[MessageStepRecord]:
    """Scenario 4: Parallel tool calls + Subagent execution."""
    return [
        _create_test_record(
            step_number=1,
            message_type="human",
            content="帮我查一下上海和深圳的天气，然后搜索一下附近的餐厅",
        ),
        _create_test_record(
            step_number=2,
            message_type="ai",
            tool_calls=[
                {
                    "name": "get_weather",
                    "args": {"city": "上海"},
                    "id": "call_sh",
                },
                {
                    "name": "get_weather",
                    "args": {"city": "深圳"},
                    "id": "call_sz",
                },
            ],
            thinking="用户需要两个城市的天气，我可以并行调用",
            model_name="qwen-plus",
            latency_ms=750,
        ),
        _create_test_record(
            step_number=3,
            message_type="tool",
            tool_name="get_weather",
            tool_args={"city": "上海"},
            tool_output="上海：多云，25°C",
            tool_call_id="call_sh",
            latency_ms=220,
        ),
        _create_test_record(
            step_number=4,
            message_type="tool",
            tool_name="get_weather",
            tool_args={"city": "深圳"},
            tool_output="深圳：雷阵雨，28°C",
            tool_call_id="call_sz",
            latency_ms=240,
        ),
        # Subagent starts here (navigator searching restaurants)
        _create_test_record(
            step_number=5,
            message_type="ai",
            content="我需要调用 navigator 来搜索餐厅",
            model_name="qwen-plus",
            run_id="run_nav",
            parent_run_id="run_main",
        ),
        _create_test_record(
            step_number=6,
            message_type="tool",
            tool_name="search_restaurants",
            tool_args={"location": "上海"},
            tool_output="找到餐厅：A餐厅、B餐厅、C餐厅",
            tool_call_id="call_rest",
            run_id="run_nav",
            parent_run_id="run_main",
            latency_ms=350,
        ),
        _create_test_record(
            step_number=7,
            message_type="ai",
            content="已完成餐厅搜索",
            run_id="run_nav",
            parent_run_id="run_main",
            latency_ms=180,
        ),
        # Final AI response
        _create_test_record(
            step_number=8,
            message_type="ai",
            content="上海：多云 25°C | 深圳：雷阵雨 28°C。推荐餐厅：A餐厅、B餐厅、C餐厅",
            model_name="qwen-plus",
            latency_ms=420,
        ),
    ]


def run_tests() -> None:
    """Run all test scenarios and print results."""
    from uuid import UUID

    test_thread_id = UUID("00000000-0000-0000-0000-000000000000")

    scenarios = [
        ("Scenario 1: Simple conversation", mock_scenario_simple),
        ("Scenario 2: Single tool call", mock_scenario_single_tool),
        ("Scenario 3: Multi-round tools (Hefei style)", mock_scenario_multi_round_tools),
        ("Scenario 4: Parallel + Subagent", mock_scenario_parallel_subagent),
    ]

    for name, mock_fn in scenarios:
        print(f"\n{'=' * 60}")
        print(f"  {name}")
        print(f"{'=' * 60}")

        steps = mock_fn()
        trace = build_trace_from_steps(test_thread_id, steps)

        print(f"\nTurns: {trace.total_turns}")
        print(f"Tool calls: {trace.total_tool_calls}")
        print(f"Subagent calls: {trace.total_subagent_calls}")
        print(f"Total latency: {trace.total_latency_ms}ms")

        for i, turn in enumerate(trace.turns, 1):
            print(f"\n  Turn {i}: {turn.turn_id} (session={turn.session_id})")
            print(f"    Human: {turn.humanMsg[:60]}...")
            if turn.aiMsg.content:
                print(f"    AI msg: {turn.aiMsg.content[:60]}...")
            print(f"    Tool calls in aiMsg: {len(turn.aiMsg.tool_calls)}")
            print(f"    Tool results (toolMsgs): {len(turn.toolMsgs)} (parallel={turn.isParallelTools})")
            print(f"    Subagents: {len(turn.subagentRuns)}")
            if turn.aiFinalResponse and turn.aiFinalResponse.content:
                print(f"    Final AI: {turn.aiFinalResponse.content[:60]}...")

    print(f"\n{'=' * 60}")
    print("  All tests completed!")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    run_tests()