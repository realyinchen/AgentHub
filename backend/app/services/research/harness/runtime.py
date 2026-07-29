from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.services.research import ResearchEvidence, ResearchStateResult
from app.services.research.harness.contracts import (
    AggregationResult,
    CandidateClaim,
    FinalizationResult,
    GapFillingResult,
    ObservationBatch,
    ResearchHarnessInput,
    ResearchHarnessResult,
    ResearchHarnessResumeState,
    ResearchObservation,
    ResearchPlan,
    SearchTask,
    StepFieldConfirmation,
    VerificationResult,
    VerifiedClaim,
    confirm_next_step_fields,
    require_next_step_ready,
)
from app.services.research.orchestrator import (
    ResearchOrchestrator,
    get_research_orchestrator,
)
from app.services.research.observation_providers import (
    ObservationProvider,
    ObservationProviderRequest,
    get_default_observation_provider_from_db,
)
from app.services.research.loop import (
    ResearchLoopBudget,
    evaluate_research_evidence_gaps,
)
from app.services.research.source_acquisition import ResearchSourceRecord
from app.services.research.verifier import (
    ClaimForVerification,
    ResearchVerifier,
    VerifierAdmissionInput,
)


class HarnessState(TypedDict, total=False):
    harness_input: ResearchHarnessInput
    run_id: UUID
    plan: ResearchPlan
    search_task: SearchTask
    observation_batch: ObservationBatch
    aggregation: AggregationResult
    gap_filling: GapFillingResult
    verification: VerificationResult
    finalization: FinalizationResult
    field_confirmation: StepFieldConfirmation
    field_confirmations: list[StepFieldConfirmation]
    research_state: ResearchStateResult
    resume_state: ResearchHarnessResumeState


class ResearchHarnessRuntime:
    """Compatibility harness using the canonical research-loop gap policy.

    New chat execution is owned by ``SystemRuntime`` and ``research-loop-v1``.
    This adapter remains for existing harness tools and resume verification.
    """

    def __init__(
        self,
        orchestrator: ResearchOrchestrator | None = None,
        verifier: ResearchVerifier | None = None,
        observation_provider: ObservationProvider | None = None,
    ) -> None:
        self.orchestrator = orchestrator or get_research_orchestrator()
        self.verifier = verifier or ResearchVerifier()
        self.observation_provider = observation_provider
        graph = StateGraph(HarnessState)
        graph.add_node("planner", self._planner_node)
        graph.add_node("search_task_builder", self._search_task_builder_node)
        graph.add_node("source_visitor", self._source_visitor_node)
        graph.add_node("aggregator", self._aggregator_node)
        graph.add_node("gap_filler", self._gap_filler_node)
        graph.add_node("verifier", self._verifier_node)
        graph.add_node("finalizer", self._finalizer_node)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "search_task_builder")
        graph.add_edge("search_task_builder", "source_visitor")
        graph.add_edge("source_visitor", "aggregator")
        graph.add_edge("aggregator", "gap_filler")
        graph.add_edge("gap_filler", "verifier")
        graph.add_edge("verifier", "finalizer")
        graph.add_edge("finalizer", END)
        self.graph = graph.compile()

    async def run(self, harness_input: ResearchHarnessInput | dict[str, Any]) -> ResearchHarnessResult:
        payload = ResearchHarnessInput.model_validate(harness_input)
        state = await self.graph.ainvoke(
            {
                "harness_input": payload,
                "field_confirmations": [],
            }
        )
        return self._result_from_state(state, resumed_from_postgres=False)

    async def resume_from_postgres(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        limit_steps: int = 100,
        limit_evidence: int = 100,
    ) -> ResearchHarnessResumeState:
        research_state = await self.orchestrator.inspect_research_state(
            user_id=user_id,
            run_id=run_id,
            limit_steps=limit_steps,
            limit_evidence=limit_evidence,
        )
        return self._resume_state_from_research_state(research_state)

    async def resume_and_finalize(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
    ) -> ResearchHarnessResult:
        research_state = await self.orchestrator.inspect_research_state(
            user_id=user_id,
            run_id=run_id,
            limit_steps=100,
            limit_evidence=100,
        )
        resume_state = self._resume_state_from_research_state(research_state)
        aggregation = self._aggregation_from_research_state(research_state)
        loop_assessment = evaluate_research_evidence_gaps(
            round_index=1,
            records=[
                ResearchSourceRecord(
                    source_type=item.source_type,
                    source_title=item.source_title,
                    source_url=item.source_url,
                    claim=item.claim,
                    excerpt=item.excerpt,
                    quality=item.quality,
                    relevance=item.relevance,
                    metadata=item.metadata,
                )
                for item in research_state.evidence
            ],
            rejection_reason_codes=[],
            exhausted_queries=research_state.state.exhausted_queries,
            budget=ResearchLoopBudget.model_validate(
                research_state.state.budget or {}
            ),
            search_round_count=1,
        )
        gap_filling = GapFillingResult(
            run_id=run_id,
            blocking_gaps=list(
                dict.fromkeys(
                    [*aggregation.gaps, *loop_assessment.gaps]
                )
            ),
            next_actions=["Verify candidate claims."]
            if aggregation.candidate_claims
            else ["Collect source-backed evidence before finalizing."],
            should_continue=loop_assessment.should_continue,
            metadata={
                "harness": {
                    "node": "gap_filler",
                    "resumed": True,
                    "compatibility_adapter": True,
                },
                "research_loop": loop_assessment.model_dump(mode="json"),
            },
        )
        state: HarnessState = {
            "harness_input": ResearchHarnessInput(
                user_id=user_id,
                thread_id=research_state.run.thread_id,
                objective=research_state.run.objective,
                mode=research_state.run.mode,
                subquestions=research_state.state.subquestions,
                gaps=research_state.state.gaps,
                next_actions=research_state.state.next_actions,
                budget=research_state.state.budget,
                stop_criteria=research_state.state.stop_criteria,
                metadata=research_state.run.metadata,
            ),
            "run_id": run_id,
            "aggregation": aggregation,
            "gap_filling": gap_filling,
            "research_state": research_state,
            "resume_state": resume_state,
            "field_confirmations": [],
        }
        confirmation = confirm_next_step_fields(
            state,
            current_step="gap_filler",
            next_step="verifier",
            metadata={"harness": {"resumed_from_postgres": True}},
        )
        state.update(self._with_confirmation(state, confirmation))
        state.update(await self._verifier_node(state))
        state.update(await self._finalizer_node(state))
        return self._result_from_state(state, resumed_from_postgres=True)

    async def _planner_node(self, state: HarnessState) -> dict[str, Any]:
        payload = ResearchHarnessInput.model_validate(state["harness_input"])
        subquestions = payload.subquestions or [payload.objective]
        gaps = payload.gaps or ["Need source-backed evidence."]
        next_actions = payload.next_actions or ["Build the first source-backed search task."]
        metadata = {
            **payload.metadata,
            "harness": {
                **(payload.metadata.get("harness") or {}),
                "runtime": "langgraph",
                "node": "planner",
            },
        }
        research_state = await self.orchestrator.start_research(
            user_id=payload.user_id,
            thread_id=payload.thread_id,
            objective=payload.objective,
            mode=payload.mode,
            subquestions=subquestions,
            gaps=gaps,
            next_actions=next_actions,
            budget=payload.budget,
            stop_criteria=payload.stop_criteria,
            metadata=metadata,
        )
        run_id = research_state.run.id
        if run_id is None:
            raise ValueError("research run id was not returned")
        plan = ResearchPlan(
            run_id=run_id,
            objective=payload.objective,
            subquestions=subquestions,
            gaps=gaps,
            next_actions=next_actions,
            budget=payload.budget,
            stop_criteria=payload.stop_criteria,
            metadata={"harness": {"node": "planner"}},
        )
        next_state: HarnessState = {
            **state,
            "run_id": run_id,
            "plan": plan,
            "research_state": research_state,
        }
        confirmation = confirm_next_step_fields(
            next_state,
            current_step="planner",
            next_step="search_task_builder",
        )
        return {
            "run_id": run_id,
            "plan": plan,
            "research_state": research_state,
            **self._with_confirmation(next_state, confirmation),
        }

    async def _search_task_builder_node(self, state: HarnessState) -> dict[str, Any]:
        require_next_step_ready(state, next_step="search_task_builder")
        payload = ResearchHarnessInput.model_validate(state["harness_input"])
        plan = ResearchPlan.model_validate(state["plan"])
        subquestion = plan.subquestions[0]
        query = subquestion
        search_task = SearchTask(
            run_id=plan.run_id,
            query=query,
            subquestion=subquestion,
            rationale=f"Search source-backed observations for: {subquestion}",
            metadata={"harness": {"node": "search_task_builder"}},
        )
        research_state = await self.orchestrator.update_research_state(
            user_id=payload.user_id,
            run_id=plan.run_id,
            next_actions=[f"Collect observations for query: {query}"],
            metadata={
                "harness": {
                    "node": "search_task_builder",
                    "next_step": "source_visitor",
                }
            },
        )
        next_state: HarnessState = {
            **state,
            "search_task": search_task,
            "research_state": research_state,
        }
        confirmation = confirm_next_step_fields(
            next_state,
            current_step="search_task_builder",
            next_step="source_visitor",
        )
        return {
            "search_task": search_task,
            "research_state": research_state,
            **self._with_confirmation(next_state, confirmation),
        }

    async def _source_visitor_node(self, state: HarnessState) -> dict[str, Any]:
        require_next_step_ready(state, next_step="source_visitor")
        payload = ResearchHarnessInput.model_validate(state["harness_input"])
        search_task = SearchTask.model_validate(state["search_task"])
        observation_provider = (
            self.observation_provider
            or await get_default_observation_provider_from_db()
        )
        provider_result = await observation_provider.observe(
            ObservationProviderRequest(
                run_id=search_task.run_id,
                query=search_task.query,
                subquestion=search_task.subquestion,
                rationale=search_task.rationale,
                max_results=self._max_provider_results(payload.budget),
                seed_observations=[
                    ResearchObservation.model_validate(item)
                    for item in payload.observations
                ],
                metadata={
                    **payload.metadata,
                    "harness": {"node": "source_visitor"},
                },
            )
        )
        observations = provider_result.observations
        search_status = provider_result.status
        results = [
            {
                "title": item.source_title,
                "url": item.source_url,
                "claim": item.claim,
                "quality": item.quality,
                "metadata": item.metadata,
            }
            for item in observations
        ]
        research_state = await self.orchestrator.search_research(
            user_id=payload.user_id,
            run_id=search_task.run_id,
            query=search_task.query,
            status=search_status,
            rationale=search_task.rationale,
            results=results,
            next_actions=["Visit candidate sources."]
            if observations
            else ["Change the query or stop with uncertainty."],
            duration_ms=provider_result.duration_ms,
            error=provider_result.error,
        )
        for observation in observations:
            if not observation.source_url:
                continue
            research_state = await self.orchestrator.visit_source(
                user_id=payload.user_id,
                run_id=search_task.run_id,
                url=observation.source_url,
                title=observation.source_title,
                summary=observation.excerpt,
                rationale="Inspect provider observation before evidence extraction.",
            )
        observation_batch = ObservationBatch(
            run_id=search_task.run_id,
            query=search_task.query,
            status=search_status,
            observations=observations,
            exhausted_queries=[search_task.query],
            next_actions=["Extract evidence from observations."]
            if observations
            else ["No observations available for aggregation."],
            metadata={
                "harness": {"node": "source_visitor"},
                "provider_result": provider_result.model_dump(mode="json"),
            },
        )
        next_state: HarnessState = {
            **state,
            "observation_batch": observation_batch,
            "research_state": research_state,
        }
        confirmation = confirm_next_step_fields(
            next_state,
            current_step="source_visitor",
            next_step="aggregator",
        )
        return {
            "observation_batch": observation_batch,
            "research_state": research_state,
            **self._with_confirmation(next_state, confirmation),
        }

    def _max_provider_results(self, budget: dict[str, Any]) -> int:
        try:
            value = int(budget.get("max_provider_results") or budget.get("max_sources") or 5)
        except (TypeError, ValueError):
            value = 5
        return max(1, min(value, 20))

    async def _aggregator_node(self, state: HarnessState) -> dict[str, Any]:
        require_next_step_ready(state, next_step="aggregator")
        payload = ResearchHarnessInput.model_validate(state["harness_input"])
        batch = ObservationBatch.model_validate(state["observation_batch"])
        candidate_claims: list[CandidateClaim] = []
        evidence_ids: list[UUID] = []
        research_state = state["research_state"]
        for observation in batch.observations:
            evidence = ResearchEvidence(
                run_id=batch.run_id,
                source_type=observation.source_type,
                source_title=observation.source_title,
                source_url=observation.source_url,
                claim=observation.claim,
                excerpt=observation.excerpt,
                quality=observation.quality,
                relevance=observation.relevance,
                metadata={
                    **observation.metadata,
                    "harness": {"node": "aggregator"},
                },
            )
            research_state = await self.orchestrator.add_evidence(
                user_id=payload.user_id,
                run_id=batch.run_id,
                evidence=evidence,
                known_facts=[observation.claim],
                next_actions=["Aggregate candidate claims."],
            )
            stored = self._find_evidence_id(research_state, observation.claim)
            if stored is None:
                raise ValueError("stored evidence id was not returned")
            evidence_ids.append(stored)
            candidate_claims.append(
                CandidateClaim(
                    claim=observation.claim,
                    evidence_ids=[stored],
                    source_titles=[observation.source_title]
                    if observation.source_title
                    else [],
                    quality=observation.quality,
                    metadata={"harness": {"node": "aggregator"}},
                )
            )

        known_facts = [claim.claim for claim in candidate_claims]
        research_state = await self.orchestrator.update_research_state(
            user_id=payload.user_id,
            run_id=batch.run_id,
            known_facts=known_facts,
            gaps=[],
            conflicts=[],
            next_actions=["Check whether candidate claims are verifiable."],
            metadata={"harness": {"node": "aggregator"}},
            replace=True,
        )
        aggregation = AggregationResult(
            run_id=batch.run_id,
            candidate_claims=candidate_claims,
            known_facts=known_facts,
            gaps=[],
            conflicts=[],
            evidence_ids=evidence_ids,
            next_actions=["Run gap filler before verification."],
            metadata={"harness": {"node": "aggregator"}},
        )
        next_state: HarnessState = {
            **state,
            "aggregation": aggregation,
            "research_state": research_state,
        }
        confirmation = confirm_next_step_fields(
            next_state,
            current_step="aggregator",
            next_step="gap_filler",
        )
        return {
            "aggregation": aggregation,
            "research_state": research_state,
            **self._with_confirmation(next_state, confirmation),
        }

    async def _gap_filler_node(self, state: HarnessState) -> dict[str, Any]:
        require_next_step_ready(state, next_step="gap_filler")
        payload = ResearchHarnessInput.model_validate(state["harness_input"])
        aggregation = AggregationResult.model_validate(state["aggregation"])
        current_state = ResearchStateResult.model_validate(
            state["research_state"]
        )
        loop_budget = ResearchLoopBudget.model_validate(payload.budget or {})
        loop_assessment = evaluate_research_evidence_gaps(
            round_index=1,
            records=[
                ResearchSourceRecord(
                    source_type=item.source_type,
                    source_title=item.source_title,
                    source_url=item.source_url,
                    claim=item.claim,
                    excerpt=item.excerpt,
                    quality=item.quality,
                    relevance=item.relevance,
                    metadata=item.metadata,
                )
                for item in current_state.evidence
            ],
            rejection_reason_codes=[],
            exhausted_queries=current_state.state.exhausted_queries,
            budget=loop_budget,
            search_round_count=1,
            objective=payload.objective,
        )
        blocking_gaps = list(
            dict.fromkeys(
                [
                    *aggregation.gaps,
                    *loop_assessment.gap_descriptions,
                ]
            )
        )
        next_actions = (
            ["Verify candidate claims."]
            if not blocking_gaps
            else ["Resolve blocking gaps before finalization."]
        )
        gap_filling = GapFillingResult(
            run_id=aggregation.run_id,
            blocking_gaps=blocking_gaps,
            next_actions=next_actions,
            should_continue=bool(blocking_gaps),
            metadata={
                "harness": {
                    "node": "gap_filler",
                    "compatibility_adapter": True,
                    "canonical_runtime": "research-loop-v1",
                },
                "research_loop": loop_assessment.model_dump(mode="json"),
            },
        )
        research_state = await self.orchestrator.update_research_state(
            user_id=payload.user_id,
            run_id=aggregation.run_id,
            gaps=blocking_gaps,
            next_actions=next_actions,
            metadata={"harness": {"node": "gap_filler"}},
            replace=True,
        )
        next_state: HarnessState = {
            **state,
            "gap_filling": gap_filling,
            "research_state": research_state,
        }
        confirmation = confirm_next_step_fields(
            next_state,
            current_step="gap_filler",
            next_step="verifier",
        )
        return {
            "gap_filling": gap_filling,
            "research_state": research_state,
            **self._with_confirmation(next_state, confirmation),
        }

    async def _verifier_node(self, state: HarnessState) -> dict[str, Any]:
        require_next_step_ready(state, next_step="verifier")
        payload = ResearchHarnessInput.model_validate(state["harness_input"])
        aggregation = AggregationResult.model_validate(state["aggregation"])
        gap_filling = GapFillingResult.model_validate(state["gap_filling"])
        current_research_state = ResearchStateResult.model_validate(
            state["research_state"]
        )
        admission = self.verifier.verify(
            VerifierAdmissionInput(
                run_id=aggregation.run_id,
                candidate_claims=[
                    ClaimForVerification(
                        claim=candidate.claim,
                        evidence_ids=candidate.evidence_ids,
                        quality=candidate.quality,
                        metadata=candidate.metadata,
                    )
                    for candidate in aggregation.candidate_claims
                ],
                evidence=current_research_state.evidence,
                blocking_gaps=gap_filling.blocking_gaps,
                conflicts=[
                    *aggregation.conflicts,
                    *current_research_state.state.conflicts,
                ],
                exhausted_queries=current_research_state.state.exhausted_queries,
                budget=current_research_state.state.budget or payload.budget,
                stop_criteria=(
                    current_research_state.state.stop_criteria
                    or payload.stop_criteria
                ),
                metadata={"harness": {"node": "verifier"}},
            )
        )
        admitted = [
            self._verified_claim_from_decision(decision)
            for decision in admission.admitted_claims
        ]
        rejected = [
            self._candidate_claim_from_decision(decision)
            for decision in admission.rejected_claims
        ]
        uncertain = [
            self._candidate_claim_from_decision(decision)
            for decision in admission.uncertain_claims
        ]
        verification = VerificationResult(
            run_id=aggregation.run_id,
            admitted_claims=admitted,
            rejected_claims=rejected,
            uncertain_claims=uncertain,
            blocking_gaps=admission.blocking_gaps,
            conflicts=admission.conflicts,
            ready_for_final_answer=admission.ready_for_final_answer,
            metadata={
                "harness": {"node": "verifier"},
                "admission": admission.model_dump(mode="json"),
            },
        )
        research_state = await self.orchestrator.update_research_state(
            user_id=payload.user_id,
            run_id=aggregation.run_id,
            known_facts=[claim.claim for claim in admitted],
            gaps=admission.blocking_gaps,
            conflicts=admission.conflicts,
            next_actions=["Finalize answer."]
            if admission.ready_for_final_answer
            else ["Collect more evidence before finalization."],
            metadata={
                "harness": {
                    "node": "verifier",
                    "admitted_claim_count": len(admitted),
                    "rejected_claim_count": len(rejected),
                    "uncertain_claim_count": len(uncertain),
                    "ready_for_final_answer": admission.ready_for_final_answer,
                },
                "admission": admission.model_dump(mode="json"),
            },
            replace=True,
        )
        next_state: HarnessState = {
            **state,
            "verification": verification,
            "research_state": research_state,
        }
        confirmation = confirm_next_step_fields(
            next_state,
            current_step="verifier",
            next_step="finalizer",
        )
        return {
            "verification": verification,
            "research_state": research_state,
            **self._with_confirmation(next_state, confirmation),
        }

    async def _finalizer_node(self, state: HarnessState) -> dict[str, Any]:
        require_next_step_ready(state, next_step="finalizer")
        payload = ResearchHarnessInput.model_validate(state["harness_input"])
        verification = VerificationResult.model_validate(state["verification"])
        final_answer = self._compose_final_answer(verification)
        finalization = FinalizationResult(
            run_id=verification.run_id,
            final_answer=final_answer,
            verified_claims=verification.admitted_claims,
            remaining_uncertainty=self._remaining_uncertainty(verification),
            status="completed",
            metadata={"harness": {"node": "finalizer"}},
        )
        research_state = await self.orchestrator.finish_research(
            user_id=payload.user_id,
            run_id=verification.run_id,
            conclusion=final_answer,
            status="completed",
            known_facts=[claim.claim for claim in verification.admitted_claims],
            gaps=verification.blocking_gaps,
            conflicts=verification.conflicts,
            metadata={
                "harness": {
                    "node": "finalizer",
                    "verified_claim_count": len(verification.admitted_claims),
                    "uncertain_claim_count": len(verification.uncertain_claims),
                }
            },
        )
        next_state: HarnessState = {
            **state,
            "finalization": finalization,
            "research_state": research_state,
        }
        confirmation = confirm_next_step_fields(
            next_state,
            current_step="finalizer",
            next_step="end",
        )
        return {
            "finalization": finalization,
            "research_state": research_state,
            **self._with_confirmation(next_state, confirmation),
        }

    def _with_confirmation(
        self,
        state: HarnessState,
        confirmation: StepFieldConfirmation,
    ) -> dict[str, Any]:
        confirmations = [
            StepFieldConfirmation.model_validate(item)
            for item in state.get("field_confirmations", [])
        ]
        confirmations.append(confirmation)
        return {
            "field_confirmation": confirmation,
            "field_confirmations": confirmations,
        }

    def _find_evidence_id(
        self,
        research_state: ResearchStateResult,
        claim: str,
    ) -> UUID | None:
        for item in research_state.evidence:
            if item.claim == claim and item.id is not None:
                return item.id
        return None

    def _verified_claim_from_decision(self, decision) -> VerifiedClaim:
        return VerifiedClaim(
            claim=decision.claim,
            evidence_ids=decision.evidence_ids,
            confidence="supported",
            metadata={
                "harness": {"node": "verifier"},
                "admission": decision.model_dump(mode="json"),
            },
        )

    def _candidate_claim_from_decision(self, decision) -> CandidateClaim:
        return CandidateClaim(
            claim=decision.claim,
            evidence_ids=decision.evidence_ids,
            quality=decision.quality,
            metadata={
                "harness": {"node": "verifier"},
                "admission": decision.model_dump(mode="json"),
            },
        )

    def _aggregation_from_research_state(
        self,
        research_state: ResearchStateResult,
    ) -> AggregationResult:
        candidates: list[CandidateClaim] = []
        evidence_ids: list[UUID] = []
        for evidence in research_state.evidence:
            if evidence.id is None:
                continue
            evidence_ids.append(evidence.id)
            candidates.append(
                CandidateClaim(
                    claim=evidence.claim,
                    evidence_ids=[evidence.id],
                    source_titles=[evidence.source_title]
                    if evidence.source_title
                    else [],
                    quality=evidence.quality,
                    metadata={"harness": {"resumed_from_postgres": True}},
                )
            )
        return AggregationResult(
            run_id=research_state.run.id or research_state.state.run_id,
            candidate_claims=candidates,
            known_facts=research_state.state.known_facts
            or [item.claim for item in candidates],
            gaps=research_state.state.gaps,
            conflicts=research_state.state.conflicts,
            evidence_ids=evidence_ids or research_state.state.evidence_ids,
            next_actions=research_state.state.next_actions,
            metadata={"harness": {"resumed_from_postgres": True}},
        )

    def _resume_state_from_research_state(
        self,
        research_state: ResearchStateResult,
    ) -> ResearchHarnessResumeState:
        last_step = research_state.steps[-1].step_type if research_state.steps else ""
        return ResearchHarnessResumeState(
            run_id=research_state.run.id or research_state.state.run_id,
            status=research_state.run.status,
            objective=research_state.run.objective,
            subquestions=research_state.state.subquestions,
            known_facts=research_state.state.known_facts,
            gaps=research_state.state.gaps,
            conflicts=research_state.state.conflicts,
            exhausted_queries=research_state.state.exhausted_queries,
            next_actions=research_state.state.next_actions,
            evidence_ids=research_state.state.evidence_ids,
            evidence_count=len(research_state.evidence),
            last_step_type=last_step,
            metadata=research_state.state.metadata,
        )

    def _compose_final_answer(self, verification: VerificationResult) -> str:
        claims = [claim.claim for claim in verification.admitted_claims]
        uncertainties = self._remaining_uncertainty(verification)
        if len(claims) == 1:
            answer = f"Verified finding: {claims[0]}"
        elif claims:
            answer = "Verified findings: " + "; ".join(claims)
        else:
            answer = "I cannot verify a final finding from the available evidence."
        if uncertainties:
            answer = f"{answer} Remaining uncertainty: {'; '.join(uncertainties)}"
        return answer

    def _remaining_uncertainty(self, verification: VerificationResult) -> list[str]:
        notes = [
            *verification.blocking_gaps,
            *verification.conflicts,
        ]
        for claim in verification.uncertain_claims:
            admission = claim.metadata.get("admission") or {}
            reasons = admission.get("reason_codes") or []
            reason_text = ", ".join(str(reason) for reason in reasons) or "uncertain"
            notes.append(f"Candidate claim remains uncertain ({reason_text}): {claim.claim}")
        return notes

    def _result_from_state(
        self,
        state: dict[str, Any],
        *,
        resumed_from_postgres: bool,
    ) -> ResearchHarnessResult:
        research_state = ResearchStateResult.model_validate(state["research_state"])
        run_id = research_state.run.id or research_state.state.run_id
        resume_state = state.get("resume_state")
        if resume_state is None:
            resume_state = self._resume_state_from_research_state(research_state)
        return ResearchHarnessResult(
            user_id=research_state.run.user_id,
            run_id=run_id,
            status=research_state.run.status,
            finalization=FinalizationResult.model_validate(state["finalization"]),
            field_confirmations=[
                StepFieldConfirmation.model_validate(item)
                for item in state.get("field_confirmations", [])
            ],
            research_state=research_state,
            resume_state=ResearchHarnessResumeState.model_validate(resume_state),
            resumed_from_postgres=resumed_from_postgres,
        )
