"""Run one clean-source LongCat R5 synthesis canary."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.controller_client import ControllerClient
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.evidence_artifact import EvidenceArtifactWriter
from app.services.agent_core.evidence_source import GitSourceStateReader
from app.services.agent_core.prompt_contracts import (
    ControllerContextSnapshot,
    ControllerModelRequest,
)
from app.services.agent_core.publication.contracts import (
    ReceiptEvidenceBundle,
)
from app.services.agent_core.publication.service import TrustedPublisher
from app.services.agent_core.receipt_projector import ReceiptContextProjector
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    PlanReceipt,
    PlannedAction,
)
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.canary import _failure_code
from app.services.model_probe.configuration import resolve_probe_target


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=90)
    return parser.parse_args()


def _fixture() -> tuple[ActionPlan, PlanReceipt]:
    plan = ActionPlan(
        plan_id="r5-live-plan",
        source="controller_proposal",
        route_type="slow_path",
        intent="web_evidence",
        goal="根据已准入证据给出结构化图书推荐",
        response_mode="model",
        actions=[
            PlannedAction(
                action_id="r5-live-action",
                capability="web",
                operation="web_search_v2",
                metadata={"side_effect": False},
            )
        ],
    )
    receipt = PlanReceipt(
        plan_id=plan.plan_id,
        request_id="r5-live-request",
        route_type=plan.route_type,
        intent=plan.intent,
        status="completed",
        actions=[
            ActionReceipt(
                action_id=plan.actions[0].action_id,
                capability="web",
                operation="web_search_v2",
                status="completed",
                admitted=True,
                output={
                    "result_mode": "web_evidence",
                    "status": "ok",
                    "query": "近期好评图书",
                    "sources": [
                        {
                            "title": "科幻阅读观察",
                            "url": "https://example.com/science-fiction",
                            "snippet": "近期科幻作品讨论热度上升。",
                        },
                        {
                            "title": "文学阅读观察",
                            "url": "https://example.com/literature",
                            "snippet": "文学类作品仍保持稳定读者评价。",
                        },
                        {
                            "title": "非虚构阅读观察",
                            "url": "https://example.com/nonfiction",
                            "snippet": "非虚构作品的公共议题关注度较高。",
                        },
                    ],
                },
            )
        ],
    )
    return plan, receipt


async def _main(arguments: argparse.Namespace) -> int:
    writer = EvidenceArtifactWriter()
    writer.require_available(arguments.output)
    source = GitSourceStateReader().require_release_state(
        REPOSITORY_ROOT,
        expected_commit_sha=arguments.commit_sha,
    )
    plan, receipt = _fixture()
    registry = CapabilityRegistry(
        availability=ExternalCapabilityAvailability(web_search=True)
    )
    model_status = "failed"
    model_failure = ""
    provider_model_id = ""
    policy_status = "not_run"
    published_answer = ""

    from app.infra.database import (
        dispose_database,
        get_database,
        init_database_connection,
    )
    from app.infra.llm.manager import get_model_manager
    from app.models.model import Model
    from scripts.init_database import _init_postgres

    model_uuid = uuid.UUID(arguments.model_id)
    _init_postgres()
    await init_database_connection()
    database = get_database()
    try:
        async with database.session() as session:
            model = (
                await session.execute(
                    select(Model).where(
                        Model.id == model_uuid,
                        Model.model_type.in_(("llm", "vlm")),
                        Model.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if model is None:
                raise AssertionError("explicit active chat model was not found")
            provider_model_id = str(model.model_id)
            target = await resolve_probe_target(
                session,
                model_uuid,
                timeout_seconds=arguments.timeout_seconds,
                check_thinking=False,
            )
        await get_model_manager().refresh()
        request = ControllerModelRequest(
            model_name=str(model_uuid),
            current_user_message=(
                "请根据已提供的可信证据给出简洁、分点且带来源链接的"
                "近期好评图书方向建议，不要再次调用工具。"
            ),
            context=ControllerContextSnapshot(
                receipts=ReceiptContextProjector().project(receipt)
            ),
            admission=AgentModeAdmission(
                admitted=True,
                certification_id="candidate-canary-no-release-credit",
                configuration_fingerprint=target.configuration_fingerprint,
                controller_fingerprint=current_controller_fingerprint(
                    registry
                ),
                source_commit_sha=source.commit_sha,
            ),
            timeout_seconds=arguments.timeout_seconds,
        )
        try:
            output = await ControllerClient(registry=registry).decide(request)
            answer = TrustedPublisher().publish_synthesis(
                output,
                evidence=[
                    ReceiptEvidenceBundle(plan=plan, receipt=receipt)
                ],
            )
            published_answer = answer.content
            model_status = "passed"
            policy_status = "passed"
        except Exception as exc:
            model_failure = _failure_code(exc)
            policy_status = "not_run"
    except Exception as exc:
        model_failure = _failure_code(exc)
    finally:
        await dispose_database()

    passed = model_status == "passed" and policy_status == "passed"
    evidence = {
        "evidence_version": "r5-publication-canary-v1",
        "source_commit_sha": source.commit_sha,
        "model_id": str(model_uuid),
        "provider_model_id": provider_model_id,
        "model_phase_status": model_status,
        "model_failure_code": model_failure,
        "publication_policy_status": policy_status,
        "published_answer": published_answer,
        "raw_provider_error_exposed": False,
        "release_gate_credit": passed,
        "status": "passed" if passed else "failed",
    }
    writer.write_json_new(arguments.output, evidence)
    print(
        json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_arguments())))
