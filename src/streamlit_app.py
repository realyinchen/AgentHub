# type: ignore

import asyncio
import urllib.parse
import streamlit as st
import uuid
from collections.abc import AsyncGenerator

from app.core.config import settings
from app.schema.chat_message import ChatMessage
from agent_client import AgentClient, AgentClientError

APP_TITLE = "Agent Hub"
APP_ICON = "🧰"


async def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, menu_items={})

    # 隐藏工具栏
    st.html("<style>[data-testid='stStatusWidget'] { visibility: hidden; }</style>")

    # 初始化 client
    if "agent_client" not in st.session_state:
        agent_url = f"http://{settings.HOST}:{settings.PORT}"
        st.session_state.agent_client = AgentClient(base_url=agent_url)
    agent_client: AgentClient = st.session_state.agent_client

    # 初始化 thread
    if "thread_id" not in st.session_state:
        thread_id = st.query_params.get("thread_id") or str(uuid.uuid4())
        try:
            history = agent_client.get_history(thread_id=thread_id)
            messages = history.messages
        except AgentClientError:
            messages = []
        st.session_state.messages = messages
        st.session_state.thread_id = thread_id

    # 侧边栏
    with st.sidebar:
        st.header(f"{APP_ICON} {APP_TITLE}")
        st.write("在一个地方体验所有的AI Agent")
        if st.button(":material/chat: 开启新会话", use_container_width=True):
            # 清空 URL 参数 → 地址栏变干净
            st.query_params.clear()
            for key in [
                "messages",
                "thread_id",
                "pending_interrupt",
                "hitl_decisions",
                "editing_action",
                "final_hitl_feedback",
            ]:
                st.session_state.pop(key, None)
            st.rerun()

        agent_list = [
            agent.agent_id for agent in agent_client.agent_info_metadata.agents
        ]
        agent_idx = agent_list.index(agent_client.agent_info_metadata.default_agent)
        agent_client.agent_id = st.selectbox(
            ":material/tune: 选择Agent",
            options=agent_list,
            index=agent_idx,
        )

        @st.dialog("分享/恢复 聊天")
        def share_chat_dialog() -> None:
            session = st.runtime.get_instance()._session_mgr.list_active_sessions()[0]
            st_base_url = urllib.parse.urlunparse(
                [
                    session.client.request.protocol,
                    session.client.request.host,
                    "",
                    "",
                    "",
                    "",
                ]
            )
            # if it's not localhost, switch to https by default
            if not st_base_url.startswith("https") and "localhost" not in st_base_url:
                st_base_url = st_base_url.replace("http", "https")
            # Include both thread_id and user_id in the URL for sharing to maintain user identity
            chat_url = f"{st_base_url}?thread_id={st.session_state.thread_id}"
            st.info("复制下面的链接即可分享本次聊天记录")
            st.code(f"{chat_url}", wrap_lines=True)

        if st.button(":material/upload: 分享/恢复 聊天", use_container_width=True):
            share_chat_dialog()

    # 显示历史消息
    messages: list[ChatMessage] = st.session_state.messages or []
    if not messages:
        with st.chat_message("ai"):
            st.write("请关注我的微信公众号: PyTorch研习社")

    async def history_iter():
        for m in st.session_state.messages:
            yield m

    await draw_messages(history_iter())  # 关键：不要传 is_new=True

    # ==================== 处理用户新输入 ====================
    if user_input := st.chat_input("请输入您的消息..."):
        user_msg = ChatMessage(type="human", content=user_input)
        st.session_state.messages.append(user_msg)
        with st.chat_message("human"):
            st.write(user_input)

        with st.status("Agent 正在思考...", expanded=True) as status:
            try:
                stream = agent_client.astream(
                    message=user_input,
                    thread_id=st.session_state.thread_id,
                )
                interrupt_occurred = await draw_messages(stream, is_new=True)
                if interrupt_occurred:
                    status.update(label="等待人工审核", state="running")
                else:
                    status.update(label="完成", state="complete")
            except Exception as e:
                st.error(f"Agent 调用异常: {e}")
                status.update(label="错误", state="error")

        st.rerun()  # 刷新以显示可能的弹框

    # ==================== 处理待审核的中断 ====================
    # 只有在有中断、且用户还没有提交最终反馈时，才显示审核弹框
    if (
        "pending_interrupt" in st.session_state
        and "final_hitl_feedback" not in st.session_state
    ):
        hitl_confirm_dialog(st.session_state.pending_interrupt)

    # ==================== 用户已完成审核，恢复执行 ====================
    if "final_hitl_feedback" in st.session_state:
        feedback = st.session_state.final_hitl_feedback

        with st.status("正在恢复 Agent 执行...", expanded=True) as status:
            st.write("提交反馈并继续...")
            try:
                resume_stream = agent_client.astream(
                    message="",
                    resume=feedback,
                    thread_id=st.session_state.thread_id,
                )
                await draw_messages(resume_stream, is_new=True)
                status.update(label="Agent 已恢复并完成执行", state="complete")
            except Exception as e:
                status.update(label="恢复失败", state="error")
                st.error(f"恢复执行失败: {e}")
            finally:
                # 清理状态
                for key in [
                    "pending_interrupt",
                    "final_hitl_feedback",
                    "hitl_decisions",
                    "editing_action",
                ]:
                    st.session_state.pop(key, None)
                st.rerun()


async def draw_messages(
    messages_agen: AsyncGenerator[ChatMessage | str, None],
    is_new: bool = False,
) -> bool:
    """
    统一绘制所有消息，确保历史和实时流显示完全一致
    返回 True 表示发生了 interrupt
    """
    interrupt_occurred = False
    streaming_content = ""
    streaming_placeholder = None
    last_was_ai = False  # 标记上一个是否是 AI 消息块

    # 用于匹配 tool_call_id 的 status 容器
    tool_statuses: dict[str, any] = {}

    try:
        async for msg in messages_agen:
            # 实时 token 流
            if isinstance(msg, str):
                if not streaming_placeholder:
                    # 新建一个 AI 消息容器
                    chat = st.chat_message("ai")
                    st.session_state.last_message = chat
                    streaming_placeholder = chat.empty()
                streaming_content += msg
                streaming_placeholder.write(streaming_content)
                continue

            if not isinstance(msg, ChatMessage):
                continue

            # 新消息加入历史
            if is_new:
                st.session_state.messages.append(msg)

            # ==================== 绘制消息 ====================
            if msg.type == "human":
                with st.chat_message("human"):
                    st.markdown(msg.content)
                last_was_ai = False

            elif msg.type == "ai":
                # AI 消息可能有 content + tool_calls，或只有 content
                if not last_was_ai:
                    chat = st.chat_message("ai")
                    st.session_state.last_message = chat
                    last_was_ai = True
                else:
                    chat = st.session_state.last_message

                with chat:
                    # 显示文本内容
                    if msg.content:
                        if streaming_placeholder:
                            streaming_placeholder.markdown(msg.content)
                            streaming_placeholder = None
                            streaming_content = ""
                        else:
                            st.markdown(msg.content)

                    # 显示工具调用（如果有）
                    if msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            tool_id = tool_call["id"]
                            tool_name = tool_call["name"]
                            label = f"🛠️ 正在调用工具：**{tool_name}**"
                            status = st.status(label, expanded=True)
                            with status:
                                st.write("**输入参数：**")
                                st.json(tool_call["args"])
                            tool_statuses[tool_id] = (status, tool_name)

            elif msg.type == "tool":
                # 查找对应的工具调用 status 元组并更新
                status_tuple = tool_statuses.get(msg.tool_call_id)
                if status_tuple:
                    status, tool_name = status_tuple
                    with status:
                        st.write("**工具执行结果：**")
                        st.markdown(msg.content)
                    status.update(
                        label=f"✅ 已执行工具 {tool_name}",
                        state="complete",
                    )
                else:
                    # 历史消息：无法获取 name 时，保守显示
                    with st.chat_message("assistant", avatar="🛠️"):
                        st.caption("工具执行结果")
                        st.markdown(msg.content)
                last_was_ai = True  # tool 属于 AI 思考过程的一部分

            elif msg.type == "interrupt":
                # 只有新消息中的中断才处理，历史消息中的中断不处理
                if is_new and st.session_state.get("pending_interrupt") is None:
                    st.session_state.pending_interrupt = msg
                    interrupt_occurred = True

                    if is_new:
                        st.session_state.messages.append(msg)
                        with st.chat_message("system"):
                            st.warning("🤖 Agent 请求人工审核，请在弹出的对话框中操作")

            # 清除 streaming 状态
            streaming_placeholder = None
            streaming_content = ""

    except Exception as e:
        st.error(f"绘制消息时出错: {e}")
    finally:
        # 确保所有 status 关闭
        for s in tool_statuses.values():
            try:
                s.update(state="complete")
            except:  # noqa: E722
                pass

    return interrupt_occurred


# ==================== HITL 审核对话框 ===================
@st.dialog("请审核 Agent 操作", width="large")
def hitl_confirm_dialog(interrupt_message: ChatMessage):
    action_requests = getattr(interrupt_message, "action_requests", [])
    review_configs = getattr(interrupt_message, "review_configs", [])

    review_map = {
        cfg["action_name"]: cfg["allowed_decisions"] for cfg in review_configs
    }
    if "hitl_decisions" not in st.session_state:
        st.session_state.hitl_decisions = {}

    st.markdown("### 🤖 Agent 请求执行以下操作，请逐一审核")

    for action in action_requests:
        name = action["name"]
        args = action.get("args", {})
        desc = action.get("description", "")
        allowed = review_map.get(name, ["approve", "reject"])

        st.markdown(f"**工具：{name}**")
        st.info(desc)
        st.json(args, expanded=False)

        cols = st.columns(len(allowed) + (1 if "edit" in allowed else 0))
        i = 0
        if "approve" in allowed:
            with cols[i]:
                if st.button(
                    "✅ 批准",
                    key=f"app_{name}",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state.hitl_decisions[name] = {
                        "decision": "approve",
                        "edited_args": None,
                    }
                    st.rerun()
            i += 1
        if "reject" in allowed:
            with cols[i]:
                if st.button("❌ 拒绝", key=f"rej_{name}", use_container_width=True):
                    st.session_state.hitl_decisions[name] = {
                        "decision": "reject",
                        "edited_args": None,
                    }
                    st.rerun()
            i += 1
        if "edit" in allowed:
            with cols[i]:
                if st.button(
                    "✏️ 编辑参数", key=f"edit_{name}", use_container_width=True
                ):
                    st.session_state.editing_action = name
                    st.rerun()

        st.divider()

    # 编辑表单
    if st.session_state.get("editing_action"):
        name = st.session_state.editing_action
        action = next(a for a in action_requests if a["name"] == name)
        args = action.get("args", {})

        st.markdown(f"### ✏️ 编辑：**{name}** 参数")
        with st.form(key=f"editform_{name}"):
            edited = {}
            for k, v in args.items():
                if isinstance(v, bool):
                    edited[k] = st.checkbox(k, v)
                elif isinstance(v, int):
                    edited[k] = st.number_input(k, v, step=1)
                elif isinstance(v, float):
                    edited[k] = st.number_input(k, v)
                elif isinstance(v, str) and "\n" in v or len(v) > 100:
                    edited[k] = st.text_area(k, v, height=200)
                else:
                    edited[k] = st.text_input(k, str(v))

            c1, c2 = st.columns(2)
            with c1:
                ok = st.form_submit_button("✅ 确认编辑并执行", type="primary")
            with c2:
                cancel = st.form_submit_button("❌ 取消")

            if ok:
                st.session_state.hitl_decisions[name] = {
                    "decision": "edit",
                    "edited_args": edited,
                }
                st.session_state.editing_action = None
                st.rerun()
            if cancel:
                st.session_state.editing_action = None
                st.rerun()

    # 审核进度
    if st.session_state.hitl_decisions:
        st.markdown("### ✅ 审核进度")
        for name, d in st.session_state.hitl_decisions.items():
            icon = {"approve": "✅", "reject": "❌", "edit": "✏️"}.get(
                d["decision"], "?"
            )
            st.write(f"{icon} **{name}** → {d['decision'].upper()}")
            if d.get("edited_args", None):
                st.json(d["edited_args"])

        # 全部审核完成后提交
        if (
            len(st.session_state.hitl_decisions) == len(action_requests)
            and action_requests
        ):
            if st.button(
                "🚀 提交审核结果，继续执行", type="primary", use_container_width=True
            ):
                decisions = []

                for action in action_requests:
                    action_name = action["name"]
                    user_decision = st.session_state.hitl_decisions.get(action_name)

                    if not user_decision:
                        st.error(f"缺失对 {action_name} 的审核决定")
                        st.stop()

                    decision_type = user_decision["decision"]

                    if decision_type == "approve":
                        decisions.append({"type": "approve"})

                    elif decision_type == "reject":
                        decisions.append({"type": "reject"})

                    elif decision_type == "edit":
                        edited_args = user_decision.get("edited_args")
                        decisions.append(
                            {
                                "type": "edit",
                                "edited_action": {
                                    "name": action_name,  # 工具名保持不变
                                    "args": edited_args,  # 用户修改后的参数
                                },
                            }
                        )

                    else:
                        st.error(f"未知决策类型: {decision_type}")
                        st.stop()

                # 构造后端期望的 resume 结构
                resume_payload = {"decisions": decisions}

                # 存入 session_state，供主流程恢复时使用
                st.session_state.final_hitl_feedback = resume_payload

                # 立即删除 pending_interrupt，强制关闭弹框
                st.session_state.pop("pending_interrupt", None)

                # 清空临时状态
                st.session_state.hitl_decisions = {}
                st.session_state.editing_action = None

                st.success("审核结果已提交，正在继续执行 Agent...")
                st.rerun()


if __name__ == "__main__":
    asyncio.run(main())
