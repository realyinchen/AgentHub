from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from app.schemas.chat import UserInput
from app.services.agent_core.contracts import PublishedAnswer
from app.services.agent_core.publication.graph import (
    project_public_execution_graph,
)
from app.services.agent_core.publication.stream import TrustedStreamSequencer
from app.utils.sse import sse, sse_error


logger = logging.getLogger(__name__)


class TrustedControllerStream:
    """Run the admitted Controller and expose only committed public events."""

    def __init__(
        self,
        *,
        entry=None,
        committer=None,
        database_factory=None,
        journal=None,
        model_resolver=None,
        model_cache_refresher=None,
    ) -> None:
        self._entry = entry
        self._committer = committer
        self._database_factory = database_factory
        self._journal = journal
        self._model_resolver = model_resolver
        self._model_cache_refresher = model_cache_refresher

    async def generate(
        self,
        user_input: UserInput,
    ) -> AsyncGenerator[str, None]:
        sequencer = TrustedStreamSequencer(
            request_id=user_input.request_id
        )
        yield sse(sequencer.turn_started().model_dump(mode="json"))

        try:
            (
                database,
                journal,
                entry_service,
                committer,
                model_resolver,
                model_cache_refresher,
            ) = self._dependencies()
        except Exception:
            logger.exception(
                "Trusted stream dependencies are unavailable"
            )
            yield sse_error(
                "本轮未能安全开始，请稍后重试。",
                error_type="turn_start_failed",
            )
            yield "data: [DONE]\n\n"
            return
        try:
            async with database.session() as session:
                user_event = await journal.record_user_message(
                    session,
                    user_input,
                )
        except Exception:
            logger.exception(
                "Trusted stream could not commit the user Journal event"
            )
            yield sse_error(
                "本轮未能安全开始，请稍后重试。",
                error_type="turn_start_failed",
            )
            yield "data: [DONE]\n\n"
            return

        requested_model = (
            user_input.model_uuid or user_input.model_name
        )
        try:
            model_name = model_resolver(requested_model)
            if requested_model and model_name:
                await model_cache_refresher(model_name)
        except Exception:
            logger.exception(
                "Trusted stream model resolution failed"
            )
            async for event in self._publish_failure(
                sequencer=sequencer,
                user_input=user_input,
                message="当前模型暂不可用，请稍后重试。",
                model_name="",
                database=database,
                committer=committer,
            ):
                yield event
            return
        if not model_name:
            async for event in self._publish_failure(
                sequencer=sequencer,
                user_input=user_input,
                message="当前没有可用的模型，请检查模型配置。",
                model_name="",
                database=database,
                committer=committer,
            ):
                yield event
            return
        if user_input.model_name != model_name:
            user_input = user_input.model_copy(
                update={"model_name": model_name}
            )

        try:
            async with database.session() as session:
                entry = await entry_service.run(
                    session,
                    user_input=user_input,
                    model_name=model_name,
                    mode="live",
                    journal_sequence_watermark=user_event.sequence_no,
                )
            if (
                not entry.handled
                or entry.message is None
                or entry.answer is None
            ):
                raise RuntimeError(
                    "trusted Controller returned no publishable answer"
                )
        except Exception:
            logger.exception(
                "Trusted Controller stream failed before publication"
            )
            async for event in self._publish_failure(
                sequencer=sequencer,
                user_input=user_input,
                message="本轮未能形成可信回答，请稍后重试。",
                model_name=model_name,
                database=database,
                committer=committer,
            ):
                yield event
            return

        turn = entry.attempt.turn
        graph = (
            self._committer_graph(turn, user_input.request_id)
        )
        yield sse(
            sequencer.graph_snapshot(
                project_public_execution_graph(graph)
            ).model_dump(mode="json")
        )
        try:
            async with database.session() as session:
                committed = await committer.commit(
                    session,
                    user_input=user_input,
                    answer=entry.answer,
                    turn=turn,
                    model_name=model_name,
                    agent_mode=str(
                        entry.message.custom_data.get(
                            "agent_mode", "controller_v1"
                        )
                    ),
                )
        except Exception:
            logger.exception(
                "Trusted stream publication transaction failed"
            )
            yield sse_error(
                "回答未能安全提交，因此本轮不会显示未提交结果。",
                error_type="publication_commit_failed",
            )
            yield "data: [DONE]\n\n"
            return

        if entry.answer.status == "completed":
            terminal = sequencer.answer_completed(
                answer=entry.answer,
                committed=committed,
            )
        elif entry.answer.status == "clarification_required":
            terminal = sequencer.clarification_required(
                answer=entry.answer,
                committed=committed,
            )
        else:
            terminal = sequencer.turn_failed(
                committed=committed,
                message="本轮未能安全完成，请稍后重试。",
            )
        yield sse(terminal.model_dump(mode="json"))
        yield "data: [DONE]\n\n"

    async def _publish_failure(
        self,
        *,
        sequencer: TrustedStreamSequencer,
        user_input: UserInput,
        message: str,
        model_name: str,
        database,
        committer,
    ) -> AsyncGenerator[str, None]:
        answer = PublishedAnswer(
            status="failed",
            content=message,
            receipt_backed=False,
            publication_mode="direct",
        )
        try:
            async with database.session() as session:
                committed = await committer.commit(
                    session,
                    user_input=user_input,
                    answer=answer,
                    turn=None,
                    model_name=model_name,
                )
        except Exception:
            logger.exception(
                "Trusted stream could not commit the failure lifecycle"
            )
            yield sse_error(
                "本轮未能安全完成，请稍后重试。",
                error_type="turn_failed",
            )
            yield "data: [DONE]\n\n"
            return
        yield sse(
            sequencer.graph_snapshot(
                project_public_execution_graph(
                    committed.execution_graph
                )
            ).model_dump(mode="json")
        )
        yield sse(
            sequencer.turn_failed(
                committed=committed,
                message=message,
            ).model_dump(mode="json")
        )
        yield "data: [DONE]\n\n"

    def _dependencies(self):
        from app.infra.database import get_database
        from app.infra.llm import resolve_model_name
        from app.infra.llm.resolver import refresh_model_cache_if_missing
        from app.services.agent_core.chat_entry import AgentChatEntry
        from app.services.agent_core.publication.commit import (
            TurnPublicationCommitter,
        )
        from app.services.conversation import ConversationJournalService

        return (
            (
                self._database_factory or get_database
            )(),
            self._journal or ConversationJournalService(),
            self._entry or AgentChatEntry(),
            self._committer or TurnPublicationCommitter(),
            self._model_resolver or resolve_model_name,
            (
                self._model_cache_refresher
                or refresh_model_cache_if_missing
            ),
        )

    @staticmethod
    def _committer_graph(turn, request_id: str):
        from app.services.agent_core.publication.graph import (
            build_turn_execution_graph,
        )

        return build_turn_execution_graph(
            turn,
            request_id=request_id,
        )


__all__ = ["TrustedControllerStream"]
