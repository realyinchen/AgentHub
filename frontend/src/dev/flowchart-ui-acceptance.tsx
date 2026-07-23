import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "../index.css"

import { ChatMessageItem } from "@/features/chat/components/chat-message-item"
import { I18nProvider } from "@/i18n"
import { ThemeProvider } from "@/hooks/use-theme"
import type { LocalChatMessage, StoredToolCallInfo } from "@/types"

const userId = "00000000-0000-0000-0000-000000000001"
const runId = "flowchart-ui-run"

const routePayload = {
  result_mode: "book_turn_orchestration",
  contract_version: "book-turn-orchestration-v1",
  route: "recommendation_history",
  query: "Why did you not recommend Dune?",
  user_message: "Why did you not recommend Dune?",
  history_mode: "suppression_explanation",
  policy: {
    intent: {
      primary_intent: "recommendation_history",
      intents: ["answer_question", "recommendation_history"],
      confidence: 1,
      explicit: true,
      source: "deterministic_rules",
      signals: ["explicit_recommendation_history_or_suppression_explanation"],
      metadata: { contract_version: "turn-intent-v1" },
    },
    can_answer_question: true,
    can_write_memory: false,
    can_manage_memory: false,
    can_search_memory: true,
    can_search_books: false,
    can_recommend_books: false,
    can_view_recommendation_history: true,
    can_record_recommendation_signal: false,
    can_start_research: false,
    can_use_research_tools: false,
    max_book_search_calls: 0,
    requires_verifier: false,
    allowed_tools: [
      "get_current_time",
      "plan_book_assistant_turn",
      "search_memory",
      "get_recommendation_history",
    ],
    denied_tools: ["search_books"],
    response_boundary: "Answer only with recommendation history or suppression explanation.",
    metadata: { contract_version: "turn-policy-v1" },
  },
  recommended_next_tools: ["get_recommendation_history"],
  denied_tools: ["search_books"],
  response_boundary: "Answer only with recommendation history or suppression explanation.",
  route_steps: [
    {
      name: "get_recommendation_history",
      status: "ready",
      reason: "The user asked for a suppression explanation.",
      required_inputs: ["user_id", "history_mode"],
    },
    {
      name: "search_books",
      status: "blocked_by_route",
      reason: "History mode must not create fresh recommendations.",
      required_inputs: [],
    },
  ],
  personalization_constraints: null,
  recommendation_research_workflow: null,
  metadata: {
    writes_long_term_memory: false,
    writes_recommendation_events: false,
    writes_research_state: false,
    writes_evidence: false,
    external_call: false,
    executes_planned_tools: false,
    uses_app_owned_contracts: true,
  },
}

const historyPayload = {
  status: "ok",
  result_mode: "recommendation_history",
  history_mode: "suppression_explanation",
  user_id: userId,
  query: "Why did you not recommend Dune?",
  book_title: "Dune",
  records: [],
  suppressed_records: [
    {
      record_type: "recommendation_event",
      event_type: "read",
      book_id: null,
      book_title: "Dune",
      reason: "Already read in a previous session.",
      suppression_reasons: ["already_read"],
      signal_polarity: "neutral",
      signal_strength: 1,
      source: "book_feedback",
      thread_id: null,
      request_id: "",
      message_id: "",
      metadata: {},
      created_at: "2026-07-17T09:00:00Z",
    },
  ],
  result_count: 1,
  next_action_hint: "",
  metadata: {
    ordinary_recommendation_candidates: false,
    suppressed_records_are_history_only: true,
  },
}

const verifiedClaim = {
  claim: "Flowchart Fresh Novel is warm and character-driven.",
  status: "admitted",
  evidence_ids: ["evidence-flowchart-1"],
  evidence: [],
  quality: "high",
  reason_codes: ["source_backed"],
  explanation: "The claim is backed by an accepted source fixture.",
  metadata: {},
}

const researchSource = {
  evidence_id: "evidence-flowchart-1",
  source_type: "web",
  source_title: "Flowchart Source Fixture",
  source_url: "https://example.test/flowchart-source",
  quality: "high",
  relevance: 5,
  claim: verifiedClaim.claim,
}

const researchReportPayload = {
  result_mode: "research_report",
  contract_version: "research-report-v1",
  run_id: runId,
  user_id: userId,
  objective: "Find source-backed evidence for a warm character-driven recommendation.",
  run_status: "completed",
  report_status: "ready",
  final_answer: "",
  verified_claims: [verifiedClaim],
  uncertain_claims: [
    {
      claim: "The book is universally loved.",
      status: "uncertain",
      evidence_ids: [],
      evidence: [],
      quality: "unknown",
      reason_codes: ["insufficient_evidence"],
      explanation: "The fixture intentionally keeps this out of final facts.",
      metadata: {},
    },
  ],
  rejected_claims: [],
  sources: [researchSource],
  gaps: ["Need fresh external sources before production research."],
  conflicts: [],
  exhausted_queries: ["warm character driven novel"],
  next_actions: ["Use verified claims only in the final answer."],
  memory_context: {
    memory_ids: ["memory-flowchart-1"],
    constraints: ["prefers warm character-driven fiction"],
  },
  verification: {
    run_id: runId,
    decisions: [verifiedClaim],
    admitted_claims: [verifiedClaim],
    rejected_claims: [],
    uncertain_claims: [],
    blocking_gaps: [],
    conflicts: [],
    ready_for_final_answer: true,
    can_finalize_with_uncertainty: false,
    metadata: {},
  },
  metadata: {
    writes_long_term_memory: false,
    writes_recommendation_events: false,
  },
}

const finalAnswerPayload = {
  result_mode: "research_final_answer",
  contract_version: "research-final-answer-v1",
  user_id: userId,
  run_id: runId,
  objective: researchReportPayload.objective,
  report_status: "ready",
  answer_status: "ready",
  answer: "Flowchart Fresh Novel is supported because the verified source says it is warm and character-driven.",
  verified_claims: [verifiedClaim],
  omitted_uncertain_claims: researchReportPayload.uncertain_claims,
  omitted_rejected_claims: [],
  limitations: ["Only verified claims are used in this answer."],
  sources: [researchSource],
  ready_for_final_answer: true,
  can_finalize_with_uncertainty: false,
  metadata: {},
}

const recommendationResearchPayload = {
  result_mode: "recommendation_research_report",
  contract_version: "recommendation-research-report-v1",
  status: "ready",
  query: "Recommend a warm character-driven novel with evidence.",
  research_run_id: runId,
  research_report_status: "ready",
  research_report_contract_version: "research-report-v1",
  candidates: [],
  recommended_candidates: [
    {
      rank: 1,
      book_id: "book-flowchart-fresh",
      title: "Flowchart Fresh Novel",
      authors: ["Acceptance Author"],
      summary: "A warm, character-driven fixture candidate.",
      rating: 4.6,
      source_name: "book_cache",
      source_url: "https://example.test/flowchart-book",
      recommendation_score: 0.92,
      candidate_source: { source_kind: "book_cache" },
      recommendation_explanation: {},
      personalization_reasons: ["matches warm fiction preference"],
      research_support: [
        {
          claim: verifiedClaim.claim,
          source_title: researchSource.source_title,
          source_url: researchSource.source_url,
          source_type: researchSource.source_type,
          quality: researchSource.quality,
          relevance: researchSource.relevance,
          evidence_ids: ["evidence-flowchart-1"],
          reason: "verified research support",
          metadata: {},
        },
      ],
      limitations: [],
      supported_by_verified_research: true,
      suppressed: false,
      suppression_reasons: [],
      fit_summary: "Matches the user's preference and has verified research support.",
      metadata: {},
    },
  ],
  suppressed_candidates: [
    {
      rank: 0,
      book_id: "book-dune",
      title: "Dune",
      authors: ["Frank Herbert"],
      summary: "Suppressed in this fixture because it was already read.",
      rating: null,
      source_name: "book_cache",
      source_url: "https://example.test/dune",
      recommendation_score: null,
      candidate_source: { source_kind: "book_cache" },
      recommendation_explanation: {},
      personalization_reasons: [],
      research_support: [],
      limitations: [],
      supported_by_verified_research: false,
      suppressed: true,
      suppression_reasons: ["already_read"],
      fit_summary: "",
      metadata: {},
    },
  ],
  unsupported_candidates: [],
  candidate_count: 2,
  supported_count: 1,
  suppressed_count: 1,
  verified_claim_count: 1,
  limitations: ["Suppressed candidates remain history/explanation context only."],
  metadata: {},
}

const toolInfo = [
  {
    name: "plan_book_assistant_turn",
    id: "call-route-history",
    args: { query: routePayload.query },
    output: JSON.stringify(routePayload),
    order: 0,
  },
  {
    name: "get_recommendation_history",
    id: "call-history",
    args: { history_mode: "suppression_explanation", book_title: "Dune" },
    output: JSON.stringify(historyPayload),
    order: 1,
  },
  {
    name: "build_research_report",
    id: "call-research-report",
    args: { run_id: runId },
    output: JSON.stringify(researchReportPayload),
    order: 2,
  },
  {
    name: "finalize_research_answer",
    id: "call-final-answer",
    args: { run_id: runId },
    output: JSON.stringify(finalAnswerPayload),
    order: 3,
  },
  {
    name: "build_recommendation_research_report",
    id: "call-recommendation-research",
    args: { run_id: runId },
    output: JSON.stringify(recommendationResearchPayload),
    order: 4,
  },
] satisfies StoredToolCallInfo[]

const messages: LocalChatMessage[] = [
  {
    type: "human",
    content: "Why did you not recommend Dune, and can you show a researched alternative?",
    tool_calls: [],
    tool_call_id: null,
    run_id: null,
    request_id: null,
    response_metadata: {},
    custom_data: {},
    local_id: "flowchart-user",
  },
  {
    type: "ai",
    content: "Here is the route-first flowchart UI acceptance fixture.",
    tool_calls: [],
    tool_call_id: null,
    run_id: null,
    request_id: "flowchart-ui-acceptance",
    response_metadata: {},
    custom_data: { tool_info: toolInfo },
    local_id: "flowchart-assistant",
  },
]

export function FlowchartUiAcceptance() {
  return (
    <main className="min-h-screen bg-background px-4 py-6 text-foreground">
      <div className="mx-auto max-w-5xl">
        <header className="mb-4 rounded-xl border border-border/70 bg-card p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Local UI acceptance fixture
          </p>
          <h1 className="mt-1 text-2xl font-semibold">Flowchart route panels</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            This page renders real chat message panels from stored tool_info output.
            It does not call the backend, LLM providers, mem0, or gbrain.
          </p>
        </header>

        <div className="space-y-4">
          {messages.map((message, index) => (
            <ChatMessageItem
              key={message.local_id}
              message={message}
              isSelected={index === messages.length - 1}
            />
          ))}
        </div>
      </div>
    </main>
  )
}

export function FlowchartUiAcceptanceApp() {
  return (
    <StrictMode>
      <I18nProvider>
        <ThemeProvider>
          <FlowchartUiAcceptance />
        </ThemeProvider>
      </I18nProvider>
    </StrictMode>
  )
}

if (typeof document !== "undefined") {
  createRoot(document.getElementById("root")!).render(<FlowchartUiAcceptanceApp />)
}
