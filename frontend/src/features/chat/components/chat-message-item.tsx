import {
  BrainIcon,
  CheckIcon,
  ChevronDown,
  CopyIcon,
  HistoryIcon,
  Loader2,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Message, MessageContent } from "@/components/ai/message"
import { cn } from "@/lib/utils"
import type {
  BookTurnIntent,
  BookTurnOrchestrationResult,
  BookTurnOrchestrationStep,
  BookTurnPolicy,
  LocalChatMessage,
  ResearchClaimAdmissionDecision,
  ResearchEvidence,
  ResearchEvidenceAdmissionResult,
  ResearchEvidenceReference,
  ResearchFinalAnswerResult,
  ResearchObservation,
  ResearchObservationBatchResult,
  ResearchPythonAnalysisResult,
  ResearchReportResult,
  ResearchReportSource,
  ResearchScholarSearchResult,
  ResearchSourceDocument,
  ResearchSourceCollectionResult,
  ResearchSourceExtractionResult,
  ResearchSourceRecord,
  ResearchSourceSearchResult,
  ResearchSourceVisitResult,
  ResearchStateResult,
  ResearchStep,
  RejectedResearchSource,
  RecommendationResearchCandidate,
  RecommendationResearchClaimLink,
  RecommendationResearchReportResult,
  RecommendationResearchRunnerResult,
  RecommendationResearchWorkflowResult,
  RecommendationResearchWorkflowStep,
  RecommendationHistoryRecord,
  RecommendationHistoryResult,
  PersonalizedRecommendationConstraints,
  ResearchRuntimeResult,
  StoredToolCallInfo,
  ToolCallInfo,
} from "@/types"
import { MarkdownContent } from "@/components/ui/markdown-content"
import { Separator } from "@/components/ui/separator"
import { useI18n } from "@/i18n"
import {
  extractFollowUpQuestions,
  type FollowUpQuestionOption,
} from "@/features/chat/recommendation-followups"

type ChatMessageItemProps = {
  message: LocalChatMessage
  calledTools?: ToolCallInfo[]
  isAgentThinking?: boolean
  thinkingContent?: string // Accumulated thinking content (streaming)
  isProcessing?: boolean // Processing, no content received yet (kept for backward compatibility, not used)
  isStreaming?: boolean // Whether the current message is streaming
  sessionId?: string | null // session_id for this AI message
  hasSteps?: boolean // Whether this AI message has steps (tool calls or thinking)
  isSelected?: boolean // Whether this message's session is currently selected in sidebar
  onJumpToMessage?: (localId: string) => void // Jump to quoted message
  onToggleSidebarProcess?: () => void // Toggle sidebar process panel visibility
  onSelectSession?: (sessionId: string) => void // Select a specific session to view
  onSelectRequestId?: (requestId: string | null) => void // Select request_id for DAG viewing
  onFollowUpQuestionClick?: (question: FollowUpQuestionOption, message: LocalChatMessage) => void
}

type SourceLink = {
  href: string
  title: string
}

/**
 * Parse quoted content from message.
 * Format: "> quoted content\n\nnew message"
 * Returns { quotedContent, newContent } or null if not a quoted message.
 */
function parseQuotedContent(content: string): { quotedContent: string; newContent: string } | null {
  // Check if message starts with "> "
  if (!content.startsWith("> ")) {
    return null
  }

  // Find the separator "\n\n" after the quoted content
  const separatorIndex = content.indexOf("\n\n")
  if (separatorIndex === -1) {
    return null
  }

  // Extract quoted content (remove "> " prefix)
  const quotedContent = content.slice(2, separatorIndex)
  // Extract new content (after "\n\n")
  const newContent = content.slice(separatorIndex + 2)

  if (!quotedContent.trim() || !newContent.trim()) {
    return null
  }

  return { quotedContent, newContent }
}

function parseSources(message: LocalChatMessage): SourceLink[] {
  const candidates = [
    message.custom_data?.sources,
    message.response_metadata?.sources,
  ]

  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) {
      continue
    }

    const normalized = candidate
      .map((item) => {
        if (!item || typeof item !== "object") {
          return null
        }

        const record = item as Record<string, unknown>
        const href =
          typeof record.href === "string"
            ? record.href
            : typeof record.url === "string"
              ? record.url
              : null

        if (!href) {
          return null
        }

        return {
          href,
          title:
            typeof record.title === "string"
              ? record.title
              : typeof record.name === "string"
                ? record.name
                : href,
        }
      })
      .filter((item): item is SourceLink => Boolean(item))

    if (normalized.length > 0) {
      return normalized
    }
  }

  return []
}

/**
 * Parse thinking content from message.
 * Checks multiple sources for compatibility.
 */
function parseThinkingContent(message: LocalChatMessage): string | null {
  // 1. Check custom_data.thinking (saved from backend)
  const thinkingFromCustomData = message.custom_data?.thinking
  if (typeof thinkingFromCustomData === "string" && thinkingFromCustomData.trim()) {
    return thinkingFromCustomData.trim()
  }

  // 2. Check response_metadata.thinking
  const thinkingFromMetadata = message.response_metadata?.thinking
  if (typeof thinkingFromMetadata === "string" && thinkingFromMetadata.trim()) {
    return thinkingFromMetadata.trim()
  }

  // 3. Check reasoning_content
  const reasoningContent = message.reasoning_content
  if (typeof reasoningContent === "string" && reasoningContent.trim()) {
    return reasoningContent.trim()
  }

  // 4. Check custom_data.reasoning
  const reasoningFromCustomData = message.custom_data?.reasoning
  if (typeof reasoningFromCustomData === "string" && reasoningFromCustomData.trim()) {
    return reasoningFromCustomData.trim()
  }

  return null
}

/**
 * Parse stored tool info from message custom_data.
 * This is used to display tool calls from conversation history.
 */
function parseStoredToolInfo(message: LocalChatMessage): ToolCallInfo[] {
  try {
    const toolInfo = message.custom_data?.tool_info

    if (!Array.isArray(toolInfo) || toolInfo.length === 0) {
      return []
    }

    // Check if all items have order field - if so, sort by order
    // Otherwise, keep original array order (which should be correct from backend)
    const hasOrderField = toolInfo.every(
      (item) => {
        const stored = item as StoredToolCallInfo
        return stored && typeof stored.order === "number"
      }
    )

    const sortedInfo = hasOrderField
      ? [...toolInfo].sort((a, b) => {
        const orderA = (a as StoredToolCallInfo).order as number
        const orderB = (b as StoredToolCallInfo).order as number
        return orderA - orderB
      })
      : toolInfo

    return sortedInfo.map((info, index): ToolCallInfo => {
      const stored = info as StoredToolCallInfo
      return {
        name: (stored?.name as string) || "unknown",
        id: (stored?.id as string) || `tool-${index}-${Date.now()}`,
        args: (stored?.args as Record<string, unknown>) || {},
        output: (stored?.output as string | undefined) || undefined,
        status: "completed" as const,
      }
    })
  } catch {
    // Ignore parsing errors for malformed tool info
    return []
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

function cleanString(value: unknown): string {
  return String(value ?? "").trim()
}

function parseJsonObject(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "string" || !value.trim()) {
    return null
  }

  try {
    return asRecord(JSON.parse(value))
  } catch {
    return null
  }
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map(cleanString).filter(Boolean)
}

function asBoolean(value: unknown): boolean {
  return value === true || value === "true"
}

function asNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null
  }
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function researchQuality(value: unknown): ResearchReportSource["quality"] {
  const quality = cleanString(value)
  if (quality === "high" || quality === "medium" || quality === "low" || quality === "unknown") {
    return quality
  }
  return "unknown"
}

function researchClaimStatus(value: unknown): ResearchClaimAdmissionDecision["status"] {
  const status = cleanString(value)
  if (status === "admitted" || status === "rejected" || status === "uncertain") {
    return status
  }
  return "uncertain"
}

function normalizeHistoryRecord(value: unknown): RecommendationHistoryRecord | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const bookTitle = cleanString(record.book_title)
  const eventType = cleanString(record.event_type)
  if (!bookTitle && !eventType) {
    return null
  }

  return {
    record_type: cleanString(record.record_type) || "recommendation_event",
    event_type: (eventType || "suppressed") as RecommendationHistoryRecord["event_type"],
    book_id: cleanString(record.book_id) || null,
    book_title: bookTitle || "Untitled book",
    reason: cleanString(record.reason),
    suppression_reasons: asStringArray(record.suppression_reasons),
    signal_polarity: (cleanString(record.signal_polarity) || "neutral") as RecommendationHistoryRecord["signal_polarity"],
    signal_strength: Number(record.signal_strength ?? 0),
    source: cleanString(record.source),
    thread_id: cleanString(record.thread_id) || null,
    request_id: cleanString(record.request_id),
    message_id: cleanString(record.message_id),
    metadata: asRecord(record.metadata) ?? {},
    created_at: cleanString(record.created_at) || null,
  }
}

function normalizeHistoryResult(value: unknown): RecommendationHistoryResult | null {
  const payload = asRecord(value)
  if (!payload || payload.result_mode !== "recommendation_history") {
    return null
  }

  const records = Array.isArray(payload.records)
    ? payload.records
      .map(normalizeHistoryRecord)
      .filter((item): item is RecommendationHistoryRecord => Boolean(item))
    : []
  const suppressedRecords = Array.isArray(payload.suppressed_records)
    ? payload.suppressed_records
      .map(normalizeHistoryRecord)
      .filter((item): item is RecommendationHistoryRecord => Boolean(item))
    : []

  return {
    status: (cleanString(payload.status) || "empty_result") as RecommendationHistoryResult["status"],
    result_mode: "recommendation_history",
    history_mode: (cleanString(payload.history_mode) || "all") as RecommendationHistoryResult["history_mode"],
    user_id: cleanString(payload.user_id),
    query: cleanString(payload.query),
    book_title: cleanString(payload.book_title),
    records,
    suppressed_records: suppressedRecords,
    result_count: Number(payload.result_count ?? records.length),
    next_action_hint: cleanString(payload.next_action_hint),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function parseRecommendationHistoryResults(tools: ToolCallInfo[]): RecommendationHistoryResult[] {
  const results: RecommendationHistoryResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result = normalizeHistoryResult(payload)
    if (!result) {
      continue
    }

    const key = [
      result.history_mode,
      result.query,
      result.book_title,
      result.records.map((record) => `${record.event_type}:${record.book_title}`).join("|"),
    ].join(":")
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function normalizeEvidenceReference(value: unknown): ResearchEvidenceReference | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const id = cleanString(record.id)
  if (!id) {
    return null
  }

  return {
    id,
    source_type: cleanString(record.source_type) || "web",
    source_title: cleanString(record.source_title),
    source_url: cleanString(record.source_url),
    quality: researchQuality(record.quality),
    relevance: Number(record.relevance ?? 3),
  }
}

function normalizeResearchClaim(value: unknown): ResearchClaimAdmissionDecision | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const claim = cleanString(record.claim)
  if (!claim) {
    return null
  }

  return {
    claim,
    status: researchClaimStatus(record.status),
    evidence_ids: asStringArray(record.evidence_ids),
    evidence: Array.isArray(record.evidence)
      ? record.evidence
        .map(normalizeEvidenceReference)
        .filter((item): item is ResearchEvidenceReference => Boolean(item))
      : [],
    quality: researchQuality(record.quality),
    reason_codes: asStringArray(record.reason_codes),
    explanation: cleanString(record.explanation),
    metadata: asRecord(record.metadata) ?? {},
  }
}

function normalizeResearchSource(value: unknown): ResearchReportSource | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const evidenceId = cleanString(record.evidence_id)
  const claim = cleanString(record.claim)
  if (!evidenceId && !claim) {
    return null
  }

  return {
    evidence_id: evidenceId,
    source_type: cleanString(record.source_type) || "web",
    source_title: cleanString(record.source_title) || "Untitled source",
    source_url: cleanString(record.source_url),
    quality: researchQuality(record.quality),
    relevance: Number(record.relevance ?? 3),
    claim,
  }
}

function normalizeResearchClaims(value: unknown): ResearchClaimAdmissionDecision[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map(normalizeResearchClaim)
    .filter((item): item is ResearchClaimAdmissionDecision => Boolean(item))
}

function normalizeResearchReport(value: unknown): ResearchReportResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_report"
    || payload.contract_version !== "research-report-v1"
  ) {
    return null
  }

  const verifiedClaims = normalizeResearchClaims(payload.verified_claims)
  const uncertainClaims = normalizeResearchClaims(payload.uncertain_claims)
  const rejectedClaims = normalizeResearchClaims(payload.rejected_claims)
  const verification = asRecord(payload.verification) ?? {}
  const memoryContext = asRecord(payload.memory_context) ?? {}

  return {
    result_mode: "research_report",
    contract_version: "research-report-v1",
    run_id: cleanString(payload.run_id),
    user_id: cleanString(payload.user_id),
    objective: cleanString(payload.objective),
    run_status: cleanString(payload.run_status) || "active",
    report_status: cleanString(payload.report_status) || "needs_more_research",
    final_answer: cleanString(payload.final_answer),
    verified_claims: verifiedClaims,
    uncertain_claims: uncertainClaims,
    rejected_claims: rejectedClaims,
    sources: Array.isArray(payload.sources)
      ? payload.sources
        .map(normalizeResearchSource)
        .filter((item): item is ResearchReportSource => Boolean(item))
      : [],
    gaps: asStringArray(payload.gaps),
    conflicts: asStringArray(payload.conflicts),
    exhausted_queries: asStringArray(payload.exhausted_queries),
    next_actions: asStringArray(payload.next_actions),
    memory_context: {
      memory_ids: asStringArray(memoryContext.memory_ids),
      constraints: asStringArray(memoryContext.constraints),
    },
    verification: {
      run_id: cleanString(verification.run_id) || cleanString(payload.run_id),
      decisions: normalizeResearchClaims(verification.decisions),
      admitted_claims: normalizeResearchClaims(verification.admitted_claims),
      rejected_claims: normalizeResearchClaims(verification.rejected_claims),
      uncertain_claims: normalizeResearchClaims(verification.uncertain_claims),
      blocking_gaps: asStringArray(verification.blocking_gaps),
      conflicts: asStringArray(verification.conflicts),
      ready_for_final_answer: asBoolean(verification.ready_for_final_answer),
      can_finalize_with_uncertainty: asBoolean(verification.can_finalize_with_uncertainty),
      metadata: asRecord(verification.metadata) ?? {},
    },
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function normalizeResearchRuntime(value: unknown): ResearchRuntimeResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_runtime"
    || payload.contract_version !== "research-runtime-v1"
  ) {
    return null
  }

  const report = normalizeResearchReport(payload.report)
  if (!report) {
    return null
  }

  return {
    result_mode: "research_runtime",
    contract_version: "research-runtime-v1",
    user_id: cleanString(payload.user_id),
    run_id: cleanString(payload.run_id),
    status: cleanString(payload.status) || "unknown",
    harness: asRecord(payload.harness) ?? {},
    report,
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function normalizeResearchFinalAnswer(value: unknown): ResearchFinalAnswerResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_final_answer"
    || payload.contract_version !== "research-final-answer-v1"
  ) {
    return null
  }

  return {
    result_mode: "research_final_answer",
    contract_version: "research-final-answer-v1",
    user_id: cleanString(payload.user_id),
    run_id: cleanString(payload.run_id),
    objective: cleanString(payload.objective),
    report_status: cleanString(payload.report_status),
    answer_status: cleanString(payload.answer_status),
    answer: cleanString(payload.answer),
    verified_claims: normalizeResearchClaims(payload.verified_claims),
    omitted_uncertain_claims: normalizeResearchClaims(payload.omitted_uncertain_claims),
    omitted_rejected_claims: normalizeResearchClaims(payload.omitted_rejected_claims),
    limitations: asStringArray(payload.limitations),
    sources: Array.isArray(payload.sources)
      ? payload.sources
        .map(normalizeResearchSource)
        .filter((item): item is ResearchReportSource => Boolean(item))
      : [],
    ready_for_final_answer: asBoolean(payload.ready_for_final_answer),
    can_finalize_with_uncertainty: asBoolean(payload.can_finalize_with_uncertainty),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function parseResearchFinalAnswerResults(tools: ToolCallInfo[]): ResearchFinalAnswerResult[] {
  const results: ResearchFinalAnswerResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result = normalizeResearchFinalAnswer(payload)
    if (!result) {
      continue
    }
    const key = `${result.run_id}:${result.answer_status}:${result.answer}`
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function parseResearchReportResults(tools: ToolCallInfo[]): ResearchReportResult[] {
  const results: ResearchReportResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const runtimePayload = asRecord(payload?.runtime)
    const candidates = [
      normalizeResearchReport(payload),
      payload?.result_mode === "research_runtime"
        ? normalizeResearchReport(asRecord(payload.report))
        : null,
      payload?.result_mode === "recommendation_research_runner"
        ? normalizeResearchReport(asRecord(payload.research_report))
        : null,
      payload?.result_mode === "recommendation_research_runner" && runtimePayload
        ? normalizeResearchReport(asRecord(runtimePayload.report))
        : null,
    ].filter((item): item is ResearchReportResult => Boolean(item))

    for (const result of candidates) {
      const key = [
        result.run_id,
        result.report_status,
        result.verified_claims.map((claim) => claim.claim).join("|"),
        result.uncertain_claims.map((claim) => claim.claim).join("|"),
      ].join(":")
      if (seen.has(key)) {
        continue
      }
      seen.add(key)
      results.push(result)
    }
  }

  return results
}

function normalizeResearchSourceRecord(value: unknown): ResearchSourceRecord | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const claim = cleanString(record.claim)
  const excerpt = cleanString(record.excerpt)
  const sourceTitle = cleanString(record.source_title)
  const sourceUrl = cleanString(record.source_url)
  if (!claim && !excerpt && !sourceTitle && !sourceUrl) {
    return null
  }

  return {
    source_type: cleanString(record.source_type) || "web",
    source_title: sourceTitle,
    source_url: sourceUrl,
    claim,
    excerpt,
    quality: researchQuality(record.quality),
    relevance: Number(record.relevance ?? 3),
    metadata: asRecord(record.metadata) ?? {},
  }
}

function normalizeResearchSourceRecords(value: unknown): ResearchSourceRecord[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map(normalizeResearchSourceRecord)
    .filter((item): item is ResearchSourceRecord => Boolean(item))
}

function normalizeResearchSourceDocument(value: unknown): ResearchSourceDocument | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const sourceTitle = cleanString(record.source_title)
  const sourceUrl = cleanString(record.source_url)
  const content = cleanString(record.content)
  if (!sourceTitle && !sourceUrl && !content) {
    return null
  }

  return {
    source_type: cleanString(record.source_type) || "web",
    source_title: sourceTitle,
    source_url: sourceUrl,
    content,
    quality: researchQuality(record.quality),
    relevance: Number(record.relevance ?? 3),
    metadata: asRecord(record.metadata) ?? {},
  }
}

function normalizeResearchSourceDocuments(value: unknown): ResearchSourceDocument[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map(normalizeResearchSourceDocument)
    .filter((item): item is ResearchSourceDocument => Boolean(item))
}

function normalizeRejectedResearchSource(value: unknown): RejectedResearchSource | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const sourceTitle = cleanString(record.source_title)
  const sourceUrl = cleanString(record.source_url)
  const reasonCodes = asStringArray(record.reason_codes)
  if (!sourceTitle && !sourceUrl && reasonCodes.length === 0) {
    return null
  }

  return {
    source_type: cleanString(record.source_type) || "web",
    source_title: sourceTitle,
    source_url: sourceUrl,
    reason_codes: reasonCodes,
    metadata: asRecord(record.metadata) ?? {},
  }
}

function normalizeResearchObservation(value: unknown): ResearchObservation | null {
  const record = normalizeResearchSourceRecord(value)
  if (!record) {
    return null
  }
  return record
}

function normalizeResearchObservationBatch(
  value: unknown
): ResearchObservationBatchResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_observation_batch"
    || payload.contract_version !== "research-observation-batch-v1"
  ) {
    return null
  }

  return {
    result_mode: "research_observation_batch",
    contract_version: "research-observation-batch-v1",
    status: cleanString(payload.status) || "empty_result",
    query: cleanString(payload.query),
    subquestion: cleanString(payload.subquestion),
    observations: Array.isArray(payload.observations)
      ? payload.observations
        .map(normalizeResearchObservation)
        .filter((item): item is ResearchObservation => Boolean(item))
      : [],
    rejected_sources: Array.isArray(payload.rejected_sources)
      ? payload.rejected_sources
        .map(normalizeRejectedResearchSource)
        .filter((item): item is RejectedResearchSource => Boolean(item))
      : [],
    source_count: Number(payload.source_count ?? 0),
    observation_count: Number(payload.observation_count ?? 0),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function normalizeResearchSourceExtraction(
  value: unknown
): ResearchSourceExtractionResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_source_extraction"
    || payload.contract_version !== "research-source-extraction-v1"
  ) {
    return null
  }

  const sourceRecords = normalizeResearchSourceRecords(payload.source_records)

  return {
    result_mode: "research_source_extraction",
    contract_version: "research-source-extraction-v1",
    status: cleanString(payload.status) || "empty_result",
    query: cleanString(payload.query),
    subquestion: cleanString(payload.subquestion),
    source_records: sourceRecords,
    observation_batch: normalizeResearchObservationBatch(payload.observation_batch),
    rejected_documents: Array.isArray(payload.rejected_documents)
      ? payload.rejected_documents
        .map(normalizeRejectedResearchSource)
        .filter((item): item is RejectedResearchSource => Boolean(item))
      : [],
    document_count: Number(payload.document_count ?? 0),
    extracted_count: Number(payload.extracted_count ?? sourceRecords.length),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function normalizeResearchEvidence(value: unknown): ResearchEvidence | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const claim = cleanString(record.claim)
  if (!claim && !cleanString(record.source_title) && !cleanString(record.source_url)) {
    return null
  }

  return {
    id: cleanString(record.id) || null,
    run_id: cleanString(record.run_id),
    step_id: cleanString(record.step_id) || null,
    source_type: cleanString(record.source_type) || "web",
    source_title: cleanString(record.source_title),
    source_url: cleanString(record.source_url),
    claim,
    excerpt: cleanString(record.excerpt),
    quality: researchQuality(record.quality),
    relevance: Number(record.relevance ?? 3),
    metadata: asRecord(record.metadata) ?? {},
    created_at: cleanString(record.created_at) || null,
    updated_at: cleanString(record.updated_at) || null,
  }
}

function normalizeResearchStep(value: unknown): ResearchStep | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const stepType = cleanString(record.step_type)
  if (!stepType) {
    return null
  }

  return {
    id: cleanString(record.id) || null,
    run_id: cleanString(record.run_id),
    step_type: stepType as ResearchStep["step_type"],
    status: (cleanString(record.status) || "completed") as ResearchStep["status"],
    title: cleanString(record.title),
    query: cleanString(record.query),
    url: cleanString(record.url),
    rationale: cleanString(record.rationale),
    input: asRecord(record.input) ?? {},
    output: asRecord(record.output) ?? {},
    error: cleanString(record.error) || null,
    duration_ms: Number(record.duration_ms ?? 0),
    created_at: cleanString(record.created_at) || null,
    updated_at: cleanString(record.updated_at) || null,
  }
}

function normalizeResearchStateResult(value: unknown): ResearchStateResult | null {
  const payload = asRecord(value)
  const run = asRecord(payload?.run)
  const state = asRecord(payload?.state)
  if (!payload || !run || !state) {
    return null
  }

  const steps = Array.isArray(payload.steps)
    ? payload.steps
      .map(normalizeResearchStep)
      .filter((item): item is ResearchStep => Boolean(item))
    : []
  const evidence = Array.isArray(payload.evidence)
    ? payload.evidence
      .map(normalizeResearchEvidence)
      .filter((item): item is ResearchEvidence => Boolean(item))
    : []

  return {
    run: {
      id: cleanString(run.id) || null,
      user_id: cleanString(run.user_id),
      thread_id: cleanString(run.thread_id) || null,
      objective: cleanString(run.objective),
      status: (cleanString(run.status) || "active") as ResearchStateResult["run"]["status"],
      mode: (cleanString(run.mode) || "deep_search") as ResearchStateResult["run"]["mode"],
      budget: asRecord(run.budget) ?? {},
      stop_criteria: asStringArray(run.stop_criteria),
      metadata: asRecord(run.metadata) ?? {},
      started_at: cleanString(run.started_at) || null,
      finished_at: cleanString(run.finished_at) || null,
      created_at: cleanString(run.created_at) || null,
      updated_at: cleanString(run.updated_at) || null,
    },
    state: {
      id: cleanString(state.id) || null,
      run_id: cleanString(state.run_id),
      step_id: cleanString(state.step_id) || null,
      objective: cleanString(state.objective),
      status: (cleanString(state.status) || "active") as ResearchStateResult["state"]["status"],
      subquestions: asStringArray(state.subquestions),
      known_facts: asStringArray(state.known_facts),
      gaps: asStringArray(state.gaps),
      conflicts: asStringArray(state.conflicts),
      exhausted_queries: asStringArray(state.exhausted_queries),
      next_actions: asStringArray(state.next_actions),
      evidence_ids: asStringArray(state.evidence_ids),
      budget: asRecord(state.budget) ?? {},
      stop_criteria: asStringArray(state.stop_criteria),
      metadata: asRecord(state.metadata) ?? {},
      created_at: cleanString(state.created_at) || null,
    },
    steps,
    evidence,
    provider_sources: asStringArray(payload.provider_sources),
  }
}

function normalizeResearchEvidenceAdmission(
  value: unknown
): ResearchEvidenceAdmissionResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_evidence_admission"
    || payload.contract_version !== "research-evidence-admission-v1"
  ) {
    return null
  }

  const evidence = normalizeResearchEvidence(payload.evidence)
  if (!evidence) {
    return null
  }

  return {
    result_mode: "research_evidence_admission",
    contract_version: "research-evidence-admission-v1",
    status: cleanString(payload.status) || "rejected",
    allowed: asBoolean(payload.allowed),
    reason_codes: asStringArray(payload.reason_codes),
    warning_codes: asStringArray(payload.warning_codes),
    evidence,
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function normalizeResearchSourceCollection(
  value: unknown
): ResearchSourceCollectionResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_source_collection"
    || payload.contract_version !== "research-source-collection-v1"
  ) {
    return null
  }

  return {
    result_mode: "research_source_collection",
    contract_version: "research-source-collection-v1",
    user_id: cleanString(payload.user_id),
    run_id: cleanString(payload.run_id),
    query: cleanString(payload.query),
    status: cleanString(payload.status) || "empty_result",
    observation_batch: normalizeResearchObservationBatch(payload.observation_batch),
    research_state: normalizeResearchStateResult(payload.research_state),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function latestEvidenceAdmissionFromState(
  value: unknown
): ResearchEvidenceAdmissionResult | null {
  const result = normalizeResearchStateResult(value)
  if (!result) {
    return null
  }

  for (const step of [...result.steps].reverse()) {
    if (step.step_type !== "add_evidence") {
      continue
    }
    const admission = normalizeResearchEvidenceAdmission(step.output.evidence_admission)
    if (admission) {
      return admission
    }
  }

  for (const evidence of [...result.evidence].reverse()) {
    const admission = normalizeResearchEvidenceAdmission(
      asRecord(evidence.metadata)?.evidence_admission
    )
    if (admission) {
      return admission
    }
  }

  return null
}

function parseResearchSourceCollectionResults(
  tools: ToolCallInfo[]
): ResearchSourceCollectionResult[] {
  const results: ResearchSourceCollectionResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result = normalizeResearchSourceCollection(payload)
    if (!result) {
      continue
    }

    const key = `${result.run_id}:${result.status}:${result.query}`
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function parseResearchEvidenceAdmissionResults(
  tools: ToolCallInfo[]
): ResearchEvidenceAdmissionResult[] {
  const results: ResearchEvidenceAdmissionResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result =
      normalizeResearchEvidenceAdmission(payload)
      ?? latestEvidenceAdmissionFromState(payload)
    if (!result) {
      continue
    }

    const key = [
      result.status,
      result.allowed,
      result.evidence.source_url,
      result.evidence.claim,
    ].join(":")
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function parseResearchStateResults(tools: ToolCallInfo[]): ResearchStateResult[] {
  const results: ResearchStateResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result = normalizeResearchStateResult(payload)
    if (!result) {
      continue
    }

    const key = [
      result.run.id,
      result.run.status,
      result.steps.map((step) => `${step.step_type}:${step.status}`).join("|"),
      result.evidence.map((evidence) => evidence.id || evidence.claim).join("|"),
    ].join(":")
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function normalizeResearchPythonAnalysis(
  value: unknown
): ResearchPythonAnalysisResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_python_analysis"
    || payload.contract_version !== "research-python-analysis-v1"
  ) {
    return null
  }

  const findings = normalizeResearchSourceRecords(payload.findings)

  return {
    result_mode: "research_python_analysis",
    contract_version: "research-python-analysis-v1",
    status: cleanString(payload.status) || "empty_result",
    query: cleanString(payload.query),
    subquestion: cleanString(payload.subquestion),
    analysis_type: cleanString(payload.analysis_type) || "structured_records",
    source_title: cleanString(payload.source_title),
    source_url: cleanString(payload.source_url),
    record_count: Number(payload.record_count ?? 0),
    analyzed_record_count: Number(payload.analyzed_record_count ?? 0),
    rejected_record_count: Number(payload.rejected_record_count ?? 0),
    findings,
    observation_batch: normalizeResearchObservationBatch(payload.observation_batch),
    finding_count: Number(payload.finding_count ?? findings.length),
    error: cleanString(payload.error) || null,
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function parseResearchPythonAnalysisResults(
  tools: ToolCallInfo[]
): ResearchPythonAnalysisResult[] {
  const results: ResearchPythonAnalysisResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result = normalizeResearchPythonAnalysis(payload)
    if (!result) {
      continue
    }

    const key = [
      result.query,
      result.subquestion,
      result.source_title,
      result.status,
      result.findings.map((finding) => finding.claim).join("|"),
    ].join(":")
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function normalizeResearchSourceSearch(value: unknown): ResearchSourceSearchResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_source_search"
    || payload.contract_version !== "research-source-search-v1"
  ) {
    return null
  }

  const documents = normalizeResearchSourceDocuments(payload.source_documents)

  return {
    result_mode: "research_source_search",
    contract_version: "research-source-search-v1",
    status: cleanString(payload.status) || "empty_result",
    query: cleanString(payload.query),
    subquestion: cleanString(payload.subquestion),
    provider_name: cleanString(payload.provider_name),
    provider_query: cleanString(payload.provider_query),
    source_documents: documents,
    extraction: normalizeResearchSourceExtraction(payload.extraction),
    document_count: Number(payload.document_count ?? documents.length),
    extracted_count: Number(payload.extracted_count ?? 0),
    error: cleanString(payload.error) || null,
    duration_ms: Number(payload.duration_ms ?? 0),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function normalizeResearchScholarSearch(value: unknown): ResearchScholarSearchResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_scholar_search"
    || payload.contract_version !== "research-scholar-search-v1"
  ) {
    return null
  }

  const documents = normalizeResearchSourceDocuments(payload.source_documents)

  return {
    result_mode: "research_scholar_search",
    contract_version: "research-scholar-search-v1",
    status: cleanString(payload.status) || "empty_result",
    query: cleanString(payload.query),
    subquestion: cleanString(payload.subquestion),
    provider_name: cleanString(payload.provider_name),
    provider_query: cleanString(payload.provider_query),
    source_documents: documents,
    extraction: normalizeResearchSourceExtraction(payload.extraction),
    document_count: Number(payload.document_count ?? documents.length),
    extracted_count: Number(payload.extracted_count ?? 0),
    error: cleanString(payload.error) || null,
    duration_ms: Number(payload.duration_ms ?? 0),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function normalizeResearchSourceVisit(value: unknown): ResearchSourceVisitResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "research_source_visit"
    || payload.contract_version !== "research-source-visit-v1"
  ) {
    return null
  }

  return {
    result_mode: "research_source_visit",
    contract_version: "research-source-visit-v1",
    status: cleanString(payload.status) || "empty_result",
    url: cleanString(payload.url),
    final_url: cleanString(payload.final_url),
    query: cleanString(payload.query),
    subquestion: cleanString(payload.subquestion),
    source_document: normalizeResearchSourceDocument(payload.source_document),
    extraction: normalizeResearchSourceExtraction(payload.extraction),
    extracted_count: Number(payload.extracted_count ?? 0),
    error: cleanString(payload.error) || null,
    duration_ms: Number(payload.duration_ms ?? 0),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

type ResearchSourceToolResult =
  | ResearchSourceSearchResult
  | ResearchScholarSearchResult
  | ResearchSourceVisitResult

function parseResearchSourceToolResults(tools: ToolCallInfo[]): ResearchSourceToolResult[] {
  const results: ResearchSourceToolResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result =
      normalizeResearchSourceSearch(payload)
      ?? normalizeResearchScholarSearch(payload)
      ?? normalizeResearchSourceVisit(payload)
    if (!result) {
      continue
    }

    const key = [
      result.result_mode,
      result.status,
      "source_documents" in result
        ? result.source_documents.map((document) => document.source_url || document.source_title).join("|")
        : result.source_document?.source_url || result.url,
    ].join(":")
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function normalizeRecommendationResearchClaimLink(
  value: unknown
): RecommendationResearchClaimLink | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const claim = cleanString(record.claim)
  if (!claim) {
    return null
  }

  return {
    claim,
    source_title: cleanString(record.source_title),
    source_url: cleanString(record.source_url),
    source_type: cleanString(record.source_type),
    quality: researchQuality(record.quality),
    relevance: Number(record.relevance ?? 3),
    evidence_ids: asStringArray(record.evidence_ids),
    reason: cleanString(record.reason),
    metadata: asRecord(record.metadata) ?? {},
  }
}

function normalizeRecommendationResearchCandidate(
  value: unknown
): RecommendationResearchCandidate | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  const title = cleanString(record.title)
  if (!title) {
    return null
  }

  return {
    rank: Number(record.rank ?? 0),
    book_id: cleanString(record.book_id),
    title,
    authors: asStringArray(record.authors),
    summary: cleanString(record.summary),
    rating: asNullableNumber(record.rating),
    source_name: cleanString(record.source_name),
    source_url: cleanString(record.source_url),
    recommendation_score: asNullableNumber(record.recommendation_score),
    candidate_source: asRecord(record.candidate_source) ?? {},
    recommendation_explanation: asRecord(record.recommendation_explanation) ?? {},
    personalization_reasons: asStringArray(record.personalization_reasons),
    research_support: Array.isArray(record.research_support)
      ? record.research_support
        .map(normalizeRecommendationResearchClaimLink)
        .filter((item): item is RecommendationResearchClaimLink => Boolean(item))
      : [],
    limitations: asStringArray(record.limitations),
    supported_by_verified_research: asBoolean(record.supported_by_verified_research),
    suppressed: asBoolean(record.suppressed),
    suppression_reasons: asStringArray(record.suppression_reasons),
    fit_summary: cleanString(record.fit_summary),
    metadata: asRecord(record.metadata) ?? {},
  }
}

function normalizeRecommendationResearchCandidates(
  value: unknown
): RecommendationResearchCandidate[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map(normalizeRecommendationResearchCandidate)
    .filter((item): item is RecommendationResearchCandidate => Boolean(item))
}

function normalizeRecommendationResearchReport(
  value: unknown
): RecommendationResearchReportResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "recommendation_research_report"
    || payload.contract_version !== "recommendation-research-report-v1"
  ) {
    return null
  }

  const candidates = normalizeRecommendationResearchCandidates(payload.candidates)
  const recommendedCandidates = normalizeRecommendationResearchCandidates(
    payload.recommended_candidates
  )
  const suppressedCandidates = normalizeRecommendationResearchCandidates(
    payload.suppressed_candidates
  )
  const unsupportedCandidates = normalizeRecommendationResearchCandidates(
    payload.unsupported_candidates
  )

  return {
    result_mode: "recommendation_research_report",
    contract_version: "recommendation-research-report-v1",
    status: cleanString(payload.status) || "empty_result",
    query: cleanString(payload.query),
    research_run_id: cleanString(payload.research_run_id),
    research_report_status: cleanString(payload.research_report_status),
    research_report_contract_version: cleanString(payload.research_report_contract_version),
    candidates,
    recommended_candidates: recommendedCandidates,
    suppressed_candidates: suppressedCandidates,
    unsupported_candidates: unsupportedCandidates,
    candidate_count: Number(payload.candidate_count ?? candidates.length),
    supported_count: Number(payload.supported_count ?? recommendedCandidates.length),
    suppressed_count: Number(payload.suppressed_count ?? suppressedCandidates.length),
    verified_claim_count: Number(payload.verified_claim_count ?? 0),
    limitations: asStringArray(payload.limitations),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function parseRecommendationResearchReportResults(
  tools: ToolCallInfo[]
): RecommendationResearchReportResult[] {
  const results: RecommendationResearchReportResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const candidates = [
      normalizeRecommendationResearchReport(payload),
      payload?.result_mode === "recommendation_research_runner"
        ? normalizeRecommendationResearchReport(asRecord(payload.recommendation_report))
        : null,
    ].filter((item): item is RecommendationResearchReportResult => Boolean(item))

    for (const result of candidates) {
      const key = [
        result.research_run_id,
        result.status,
        result.recommended_candidates.map((candidate) => candidate.title).join("|"),
        result.unsupported_candidates.map((candidate) => candidate.title).join("|"),
        result.suppressed_candidates.map((candidate) => candidate.title).join("|"),
      ].join(":")
      if (seen.has(key)) {
        continue
      }
      seen.add(key)
      results.push(result)
    }
  }

  return results
}

function normalizePersonalizedRecommendationConstraints(
  value: unknown
): PersonalizedRecommendationConstraints | null {
  const payload = asRecord(value)
  if (!payload) {
    return null
  }

  return {
    user_id: cleanString(payload.user_id),
    original_query: cleanString(payload.original_query),
    effective_query: cleanString(payload.effective_query),
    preferred_terms: asStringArray(payload.preferred_terms),
    avoided_terms: asStringArray(payload.avoided_terms),
    favorite_authors: asStringArray(payload.favorite_authors),
    disliked_authors: asStringArray(payload.disliked_authors),
    source_memory_ids: asStringArray(payload.source_memory_ids),
    search_terms_added: asStringArray(payload.search_terms_added),
    applied_to_search: asBoolean(payload.applied_to_search),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function normalizeRecommendationResearchWorkflowStep(
  value: unknown
): RecommendationResearchWorkflowStep | null {
  const payload = asRecord(value)
  if (!payload) {
    return null
  }

  const name = cleanString(payload.name)
  if (!name) {
    return null
  }

  return {
    name,
    status: cleanString(payload.status) || "unknown",
    reason: cleanString(payload.reason),
    required_inputs: asStringArray(payload.required_inputs),
  }
}

function normalizeRecommendationResearchWorkflow(
  value: unknown
): RecommendationResearchWorkflowResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "recommendation_research_workflow"
    || payload.contract_version !== "recommendation-research-workflow-v1"
  ) {
    return null
  }

  const workflowSteps = Array.isArray(payload.workflow_steps)
    ? payload.workflow_steps
      .map(normalizeRecommendationResearchWorkflowStep)
      .filter((item): item is RecommendationResearchWorkflowStep => Boolean(item))
    : []

  return {
    result_mode: "recommendation_research_workflow",
    contract_version: "recommendation-research-workflow-v1",
    status: cleanString(payload.status) || "blocked_by_missing_input",
    query: cleanString(payload.query),
    ready_to_fuse: asBoolean(payload.ready_to_fuse),
    candidate_count: Number(payload.candidate_count ?? 0),
    fresh_candidate_count: Number(payload.fresh_candidate_count ?? 0),
    suppressed_candidate_count: Number(payload.suppressed_candidate_count ?? 0),
    research_run_id: cleanString(payload.research_run_id),
    research_report_status: cleanString(payload.research_report_status),
    research_report_contract_version: cleanString(payload.research_report_contract_version),
    verified_claim_count: Number(payload.verified_claim_count ?? 0),
    missing_inputs: asStringArray(payload.missing_inputs),
    recommended_next_tools: asStringArray(payload.recommended_next_tools),
    next_action_hint: cleanString(payload.next_action_hint),
    workflow_steps: workflowSteps,
    personalization_constraints: normalizePersonalizedRecommendationConstraints(
      payload.personalization_constraints
    ),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function parseRecommendationResearchWorkflowResults(
  tools: ToolCallInfo[]
): RecommendationResearchWorkflowResult[] {
  const results: RecommendationResearchWorkflowResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result = normalizeRecommendationResearchWorkflow(payload)
    if (!result) {
      continue
    }

    const key = [
      result.query,
      result.status,
      result.ready_to_fuse ? "ready" : "not-ready",
      result.recommended_next_tools.join("|"),
      result.workflow_steps.map((step) => `${step.name}:${step.status}`).join("|"),
    ].join(":")
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function fallbackRecommendationResearchWorkflow(
  status: string,
  query: string
): RecommendationResearchWorkflowResult {
  return {
    result_mode: "recommendation_research_workflow",
    contract_version: "recommendation-research-workflow-v1",
    status,
    query,
    ready_to_fuse: false,
    candidate_count: 0,
    fresh_candidate_count: 0,
    suppressed_candidate_count: 0,
    research_run_id: "",
    research_report_status: "",
    research_report_contract_version: "",
    verified_claim_count: 0,
    missing_inputs: [],
    recommended_next_tools: [],
    next_action_hint: "",
    workflow_steps: [],
    personalization_constraints: null,
    metadata: {},
  }
}

function booleanField(
  payload: Record<string, unknown> | null,
  key: string,
  fallback = false
): boolean {
  if (!payload || payload[key] === undefined || payload[key] === null) {
    return fallback
  }
  return asBoolean(payload[key])
}

function numberField(
  payload: Record<string, unknown> | null,
  key: string,
  fallback = 0
): number {
  if (!payload || payload[key] === undefined || payload[key] === null) {
    return fallback
  }
  const numeric = Number(payload[key])
  return Number.isFinite(numeric) ? numeric : fallback
}

function normalizeBookTurnIntent(value: unknown): BookTurnIntent {
  const payload = asRecord(value)
  return {
    primary_intent: cleanString(payload?.primary_intent) || "answer_question",
    intents: asStringArray(payload?.intents),
    confidence: numberField(payload, "confidence", 0),
    explicit: booleanField(payload, "explicit", false),
    source: cleanString(payload?.source) || "unknown",
    signals: asStringArray(payload?.signals),
    metadata: asRecord(payload?.metadata) ?? {},
  }
}

function normalizeBookTurnPolicy(value: unknown): BookTurnPolicy {
  const payload = asRecord(value)
  return {
    intent: normalizeBookTurnIntent(payload?.intent),
    can_answer_question: booleanField(payload, "can_answer_question", true),
    can_write_memory: booleanField(payload, "can_write_memory"),
    can_manage_memory: booleanField(payload, "can_manage_memory"),
    can_search_memory: booleanField(payload, "can_search_memory"),
    can_search_books: booleanField(payload, "can_search_books"),
    can_recommend_books: booleanField(payload, "can_recommend_books"),
    can_view_recommendation_history: booleanField(
      payload,
      "can_view_recommendation_history"
    ),
    can_record_recommendation_signal: booleanField(
      payload,
      "can_record_recommendation_signal"
    ),
    can_start_research: booleanField(payload, "can_start_research"),
    can_use_research_tools: booleanField(payload, "can_use_research_tools"),
    can_use_web_search: booleanField(payload, "can_use_web_search"),
    max_book_search_calls: numberField(payload, "max_book_search_calls", 0),
    requires_verifier: booleanField(payload, "requires_verifier"),
    allowed_tools: asStringArray(payload?.allowed_tools),
    denied_tools: asStringArray(payload?.denied_tools),
    response_boundary: cleanString(payload?.response_boundary),
    metadata: asRecord(payload?.metadata) ?? {},
  }
}

function normalizeBookTurnOrchestrationStep(
  value: unknown
): BookTurnOrchestrationStep | null {
  const payload = asRecord(value)
  if (!payload) {
    return null
  }

  const name = cleanString(payload.name)
  if (!name) {
    return null
  }

  return {
    name,
    status: cleanString(payload.status) || "unknown",
    reason: cleanString(payload.reason),
    required_inputs: asStringArray(payload.required_inputs),
  }
}

function normalizeBookTurnOrchestration(
  value: unknown
): BookTurnOrchestrationResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "book_turn_orchestration"
    || payload.contract_version !== "book-turn-orchestration-v1"
  ) {
    return null
  }

  const route = cleanString(payload.route)
  if (!route) {
    return null
  }

  const routeSteps = Array.isArray(payload.route_steps)
    ? payload.route_steps
      .map(normalizeBookTurnOrchestrationStep)
      .filter((item): item is BookTurnOrchestrationStep => Boolean(item))
    : []

  return {
    result_mode: "book_turn_orchestration",
    contract_version: "book-turn-orchestration-v1",
    route,
    query: cleanString(payload.query),
    user_message: cleanString(payload.user_message),
    history_mode: cleanString(payload.history_mode),
    policy: normalizeBookTurnPolicy(payload.policy),
    recommended_next_tools: asStringArray(payload.recommended_next_tools),
    denied_tools: asStringArray(payload.denied_tools),
    response_boundary: cleanString(payload.response_boundary),
    route_steps: routeSteps,
    personalization_constraints: normalizePersonalizedRecommendationConstraints(
      payload.personalization_constraints
    ),
    recommendation_research_workflow: normalizeRecommendationResearchWorkflow(
      payload.recommendation_research_workflow
    ),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function parseBookTurnOrchestrationResults(
  tools: ToolCallInfo[]
): BookTurnOrchestrationResult[] {
  const results: BookTurnOrchestrationResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result = normalizeBookTurnOrchestration(payload)
    if (!result) {
      continue
    }

    const key = [
      result.route,
      result.query,
      result.history_mode,
      result.recommended_next_tools.join("|"),
      result.route_steps.map((step) => `${step.name}:${step.status}`).join("|"),
    ].join(":")
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function normalizeRecommendationResearchRunner(
  value: unknown
): RecommendationResearchRunnerResult | null {
  const payload = asRecord(value)
  if (
    !payload
    || payload.result_mode !== "recommendation_research_runner"
    || payload.contract_version !== "recommendation-research-runner-v1"
  ) {
    return null
  }

  const status = cleanString(payload.status) || "unknown"
  const query = cleanString(payload.query)
  const workflowBefore =
    normalizeRecommendationResearchWorkflow(payload.workflow_before)
    ?? fallbackRecommendationResearchWorkflow(status, query)
  const workflowAfter =
    normalizeRecommendationResearchWorkflow(payload.workflow_after)
    ?? fallbackRecommendationResearchWorkflow(status, query)

  return {
    result_mode: "recommendation_research_runner",
    contract_version: "recommendation-research-runner-v1",
    status,
    query,
    workflow_before: workflowBefore,
    workflow_after: workflowAfter,
    runtime: normalizeResearchRuntime(payload.runtime),
    research_report: normalizeResearchReport(payload.research_report),
    recommendation_report: normalizeRecommendationResearchReport(
      payload.recommendation_report
    ),
    metadata: asRecord(payload.metadata) ?? {},
  }
}

function parseRecommendationResearchRunnerResults(
  tools: ToolCallInfo[]
): RecommendationResearchRunnerResult[] {
  const results: RecommendationResearchRunnerResult[] = []
  const seen = new Set<string>()

  for (const tool of tools) {
    const payload = parseJsonObject(tool.output)
    const result = normalizeRecommendationResearchRunner(payload)
    if (!result) {
      continue
    }

    const key = [
      result.query,
      result.status,
      result.workflow_before.status,
      result.workflow_after.status,
      result.runtime?.run_id ?? "",
      result.recommendation_report?.status ?? "",
    ].join(":")
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    results.push(result)
  }

  return results
}

function historyTitle(mode: RecommendationHistoryResult["history_mode"]): string {
  if (mode === "reading_history") {
    return "Reading history"
  }
  if (mode === "rejection_history") {
    return "Rejected books"
  }
  if (mode === "suppression_explanation") {
    return "Suppression explanation"
  }
  return "Recommendation history"
}

function eventLabel(eventType: string): string {
  if (eventType === "read") {
    return "already read"
  }
  if (eventType === "disliked") {
    return "disliked"
  }
  if (eventType === "not_interested") {
    return "not interested"
  }
  if (eventType === "suppressed") {
    return "suppressed"
  }
  return eventType.replaceAll("_", " ")
}

function reasonLabel(reason: string): string {
  if (reason === "already_read") {
    return "already read"
  }
  if (reason === "negative_recommendation_signal") {
    return "negative feedback"
  }
  if (reason === "suppressed_by_system") {
    return "system suppressed"
  }
  return reason.replaceAll("_", " ")
}

function formatHistoryDate(value: string | null): string {
  if (!value) {
    return ""
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ""
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function RecommendationHistoryPanel({
  result,
}: {
  result: RecommendationHistoryResult
}) {
  const allRecords = [...result.records, ...result.suppressed_records]
  const records = allRecords.slice(0, 8)
  const totalRecordCount = Math.max(result.result_count, allRecords.length)

  return (
    <section className="mt-3 rounded-xl border border-amber-500/30 bg-amber-50/70 p-3 text-sm text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
      <div className="flex flex-wrap items-center gap-2">
        <HistoryIcon className="size-4 text-amber-600 dark:text-amber-300" />
        <span className="font-semibold">{historyTitle(result.history_mode)}</span>
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-900/60 dark:text-amber-100">
          {totalRecordCount} records
        </span>
        <span className="rounded-full border border-amber-400/50 px-2 py-0.5 text-[11px] text-amber-700 dark:text-amber-200">
          history only
        </span>
      </div>

      <p className="mt-2 text-xs leading-5 text-amber-800/90 dark:text-amber-100/80">
        These records explain prior reading or rejection state. They remain excluded
        from ordinary recommendation candidates unless you explicitly ask about history.
      </p>

      {records.length > 0 ? (
        <div className="mt-3 space-y-2">
          {records.map((record, index) => {
            const when = formatHistoryDate(record.created_at)
            return (
              <article
                key={`${record.event_type}-${record.book_title}-${index}`}
                className="rounded-lg border border-amber-400/30 bg-background/70 p-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-foreground">{record.book_title}</span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                    {eventLabel(record.event_type)}
                  </span>
                  {when ? (
                    <span className="ml-auto text-[11px] text-muted-foreground">{when}</span>
                  ) : null}
                </div>
                {record.reason ? (
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">{record.reason}</p>
                ) : null}
                {record.suppression_reasons.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {record.suppression_reasons.map((reason) => (
                      <span
                        key={`${record.book_title}-${reason}`}
                        className="rounded-md border border-border/70 px-1.5 py-0.5 text-[11px] text-muted-foreground"
                      >
                        {reasonLabel(reason)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </article>
            )
          })}
        </div>
      ) : (
        <p className="mt-3 rounded-lg border border-amber-400/30 bg-background/60 p-2 text-xs text-muted-foreground">
          No matching recommendation-history records were found.
        </p>
      )}

      {allRecords.length > records.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Showing {records.length} of {allRecords.length} records.
        </p>
      ) : null}
    </section>
  )
}

function researchStatusLabel(value: string): string {
  return value.replaceAll("_", " ")
}

function researchReasonLabel(value: string): string {
  return value.replaceAll("_", " ")
}

function ResearchSourceRecordList({
  title,
  records,
  emptyText,
}: {
  title: string
  records: ResearchSourceRecord[]
  emptyText?: string
}) {
  const visible = records.slice(0, 5)

  if (visible.length === 0) {
    return emptyText ? (
      <p className="mt-2 rounded-lg border border-border/60 bg-background/60 p-2 text-xs text-muted-foreground">
        {emptyText}
      </p>
    ) : null
  }

  return (
    <div className="mt-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="mt-2 space-y-2">
        {visible.map((record, index) => (
          <article
            key={`${record.claim}-${record.source_title}-${index}`}
            className="rounded-lg border border-border/70 bg-background/70 p-2 text-xs"
          >
            <div className="flex flex-wrap items-center gap-2">
              {record.source_url ? (
                <a
                  href={record.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-primary hover:underline"
                >
                  {record.source_title || record.source_url}
                </a>
              ) : (
                <span className="font-medium text-foreground">
                  {record.source_title || "Supplied research data"}
                </span>
              )}
              <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {record.quality}
              </span>
              <span className="rounded-full border border-border/70 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                relevance {record.relevance}
              </span>
            </div>
            {record.claim ? (
              <p className="mt-1 leading-5 text-foreground">{record.claim}</p>
            ) : null}
            {record.excerpt ? (
              <p className="mt-1 leading-5 text-muted-foreground">{record.excerpt}</p>
            ) : null}
          </article>
        ))}
      </div>
      {records.length > visible.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Showing {visible.length} of {records.length} records.
        </p>
      ) : null}
    </div>
  )
}

function ResearchPythonAnalysisPanel({
  result,
}: {
  result: ResearchPythonAnalysisResult
}) {
  const observationBatch = result.observation_batch
  const safetyFlags = [
    ["executes code", asBoolean(result.metadata.executes_user_code)],
    ["reads files", asBoolean(result.metadata.reads_files)],
    ["network access", asBoolean(result.metadata.network_access)],
  ] as const

  return (
    <section className="mt-3 rounded-xl border border-teal-500/30 bg-teal-50/70 p-3 text-sm text-teal-950 dark:bg-teal-950/20 dark:text-teal-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-teal-700 dark:text-teal-300" />
        <span className="font-semibold">Research Python analysis</span>
        <span className="rounded-full bg-teal-100 px-2 py-0.5 text-[11px] font-medium text-teal-800 dark:bg-teal-900/60 dark:text-teal-100">
          {researchStatusLabel(result.status)}
        </span>
        <span className="rounded-full border border-teal-400/50 px-2 py-0.5 text-[11px] text-teal-700 dark:text-teal-200">
          {result.contract_version}
        </span>
        <span className="rounded-full border border-teal-400/50 px-2 py-0.5 text-[11px] text-teal-700 dark:text-teal-200">
          {result.analyzed_record_count}/{result.record_count} analyzed
        </span>
        {result.rejected_record_count > 0 ? (
          <span className="rounded-full border border-teal-400/50 px-2 py-0.5 text-[11px] text-teal-700 dark:text-teal-200">
            {result.rejected_record_count} rejected
          </span>
        ) : null}
      </div>

      {result.query || result.subquestion ? (
        <p className="mt-2 text-xs leading-5 text-teal-900/90 dark:text-teal-100/85">
          {result.subquestion || result.query}
        </p>
      ) : null}

      {result.source_title || result.source_url ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Dataset:{" "}
          {result.source_url ? (
            <a
              href={result.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-primary hover:underline"
            >
              {result.source_title || result.source_url}
            </a>
          ) : (
            <span>{result.source_title}</span>
          )}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="rounded-md border border-teal-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
          {researchReasonLabel(result.analysis_type)}
        </span>
        {safetyFlags.map(([label, enabled]) => (
          <span
            key={label}
            className="rounded-md border border-teal-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground"
          >
            {label}: {enabled ? "yes" : "no"}
          </span>
        ))}
      </div>

      {result.error ? (
        <p className="mt-3 rounded-lg border border-destructive/40 bg-background/70 p-2 text-xs text-destructive">
          {result.error}
        </p>
      ) : null}

      <ResearchSourceRecordList
        title="Derived findings"
        records={result.findings}
        emptyText="No deterministic findings were derived from the supplied records."
      />

      {observationBatch ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Observation projection
            </span>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
              {researchStatusLabel(observationBatch.status)}
            </span>
            <span className="rounded-full border border-border/70 px-2 py-0.5 text-[11px] text-muted-foreground">
              {observationBatch.observation_count}/{observationBatch.source_count} observations
            </span>
          </div>
          <ResearchSourceRecordList
            title="Observation candidates"
            records={observationBatch.observations}
          />
          {observationBatch.rejected_sources.length > 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              {observationBatch.rejected_sources.length} source records were rejected before observation projection.
            </p>
          ) : null}
        </div>
      ) : (
        <p className="mt-3 rounded-lg border border-border/60 bg-background/60 p-2 text-xs text-muted-foreground">
          No observation batch was included with this analysis result.
        </p>
      )}
    </section>
  )
}

function previewText(value: string, maxLength = 280): string {
  if (value.length <= maxLength) {
    return value
  }
  return `${value.slice(0, maxLength).trim()}...`
}

function ResearchSourceDocumentList({
  documents,
}: {
  documents: ResearchSourceDocument[]
}) {
  const visible = documents.slice(0, 5)

  if (visible.length === 0) {
    return (
      <p className="mt-2 rounded-lg border border-border/60 bg-background/60 p-2 text-xs text-muted-foreground">
        No source documents were returned.
      </p>
    )
  }

  return (
    <div className="mt-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Source documents
      </div>
      <div className="mt-2 space-y-2">
        {visible.map((document, index) => (
          <article
            key={`${document.source_url}-${document.source_title}-${index}`}
            className="rounded-lg border border-border/70 bg-background/70 p-2 text-xs"
          >
            <div className="flex flex-wrap items-center gap-2">
              {document.source_url ? (
                <a
                  href={document.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-primary hover:underline"
                >
                  {document.source_title || document.source_url}
                </a>
              ) : (
                <span className="font-medium text-foreground">
                  {document.source_title || "Untitled source"}
                </span>
              )}
              <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {document.source_type}
              </span>
              <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {document.quality}
              </span>
              <span className="rounded-full border border-border/70 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                relevance {document.relevance}
              </span>
            </div>
            {document.content ? (
              <p className="mt-1 leading-5 text-muted-foreground">
                {previewText(document.content)}
              </p>
            ) : null}
          </article>
        ))}
      </div>
      {documents.length > visible.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Showing {visible.length} of {documents.length} documents.
        </p>
      ) : null}
    </div>
  )
}

function ResearchSourceExtractionSummary({
  extraction,
}: {
  extraction: ResearchSourceExtractionResult | null
}) {
  if (!extraction) {
    return (
      <p className="mt-3 rounded-lg border border-border/60 bg-background/60 p-2 text-xs text-muted-foreground">
        No source extraction result was included.
      </p>
    )
  }

  const observationBatch = extraction.observation_batch

  return (
    <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Source extraction
        </span>
        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
          {researchStatusLabel(extraction.status)}
        </span>
        <span className="rounded-full border border-border/70 px-2 py-0.5 text-[11px] text-muted-foreground">
          {extraction.extracted_count}/{extraction.document_count} extracted
        </span>
        {extraction.rejected_documents.length > 0 ? (
          <span className="rounded-full border border-border/70 px-2 py-0.5 text-[11px] text-muted-foreground">
            {extraction.rejected_documents.length} rejected
          </span>
        ) : null}
      </div>

      <ResearchSourceRecordList
        title="Extracted source records"
        records={extraction.source_records}
      />

      {observationBatch ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Observation projection: {observationBatch.observation_count}/
          {observationBatch.source_count} observations, status{" "}
          {researchStatusLabel(observationBatch.status)}.
        </p>
      ) : null}

      {extraction.rejected_documents.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {extraction.rejected_documents.slice(0, 4).flatMap((document, index) =>
            document.reason_codes.map((reason) => (
              <span
                key={`${document.source_title}-${reason}-${index}`}
                className="rounded-md border border-border/70 px-1.5 py-0.5 text-[11px] text-muted-foreground"
              >
                {researchReasonLabel(reason)}
              </span>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}

function sourceToolTitle(result: ResearchSourceToolResult): string {
  if (result.result_mode === "research_scholar_search") {
    return "Research scholar search"
  }
  if (result.result_mode === "research_source_visit") {
    return "Research source visit"
  }
  return "Research source search"
}

function sourceToolDocuments(result: ResearchSourceToolResult): ResearchSourceDocument[] {
  if (result.result_mode === "research_source_visit") {
    return result.source_document ? [result.source_document] : []
  }
  return result.source_documents
}

function ResearchSourceToolPanel({
  result,
}: {
  result: ResearchSourceToolResult
}) {
  const documents = sourceToolDocuments(result)
  const providerName =
    result.result_mode === "research_source_visit" ? "source_visit" : result.provider_name
  const providerQuery =
    result.result_mode === "research_source_visit"
      ? result.final_url || result.url
      : result.provider_query
  const externalCall = asBoolean(result.metadata.external_call)

  return (
    <section className="mt-3 rounded-xl border border-blue-500/30 bg-blue-50/70 p-3 text-sm text-blue-950 dark:bg-blue-950/20 dark:text-blue-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-blue-700 dark:text-blue-300" />
        <span className="font-semibold">{sourceToolTitle(result)}</span>
        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-800 dark:bg-blue-900/60 dark:text-blue-100">
          {researchStatusLabel(result.status)}
        </span>
        <span className="rounded-full border border-blue-400/50 px-2 py-0.5 text-[11px] text-blue-700 dark:text-blue-200">
          {result.contract_version}
        </span>
        <span className="rounded-full border border-blue-400/50 px-2 py-0.5 text-[11px] text-blue-700 dark:text-blue-200">
          {documents.length} documents
        </span>
        <span className="rounded-full border border-blue-400/50 px-2 py-0.5 text-[11px] text-blue-700 dark:text-blue-200">
          {result.extracted_count} extracted
        </span>
      </div>

      {result.query || result.subquestion ? (
        <p className="mt-2 text-xs leading-5 text-blue-900/90 dark:text-blue-100/85">
          {result.subquestion || result.query}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-1.5">
        {providerName ? (
          <span className="rounded-md border border-blue-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
            provider: {providerName}
          </span>
        ) : null}
        {providerQuery ? (
          <span className="max-w-full rounded-md border border-blue-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
            query: {previewText(providerQuery, 120)}
          </span>
        ) : null}
        <span className="rounded-md border border-blue-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
          external call: {externalCall ? "yes" : "no"}
        </span>
        {result.duration_ms > 0 ? (
          <span className="rounded-md border border-blue-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
            {result.duration_ms} ms
          </span>
        ) : null}
      </div>

      {result.error ? (
        <p className="mt-3 rounded-lg border border-destructive/40 bg-background/70 p-2 text-xs text-destructive">
          {result.error}
        </p>
      ) : null}

      <ResearchSourceDocumentList documents={documents} />
      <ResearchSourceExtractionSummary extraction={result.extraction} />

      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        Source documents and extracted records are observation material only;
        evidence admission and verifier approval still happen in later steps.
      </p>
    </section>
  )
}

function ResearchSourceCollectionPanel({
  result,
}: {
  result: ResearchSourceCollectionResult
}) {
  const batch = result.observation_batch
  const state = result.research_state
  const writesResearchState = asBoolean(result.metadata.writes_research_state)
  const writesEvidence = asBoolean(result.metadata.writes_evidence)

  return (
    <section className="mt-3 rounded-xl border border-indigo-500/30 bg-indigo-50/70 p-3 text-sm text-indigo-950 dark:bg-indigo-950/20 dark:text-indigo-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-indigo-700 dark:text-indigo-300" />
        <span className="font-semibold">Research source collection</span>
        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-800 dark:bg-indigo-900/60 dark:text-indigo-100">
          {researchStatusLabel(result.status)}
        </span>
        <span className="rounded-full border border-indigo-400/50 px-2 py-0.5 text-[11px] text-indigo-700 dark:text-indigo-200">
          {result.contract_version}
        </span>
        {batch ? (
          <span className="rounded-full border border-indigo-400/50 px-2 py-0.5 text-[11px] text-indigo-700 dark:text-indigo-200">
            {batch.observation_count}/{batch.source_count} observations
          </span>
        ) : null}
      </div>

      {result.query ? (
        <p className="mt-2 text-xs leading-5 text-indigo-900/90 dark:text-indigo-100/85">
          {result.query}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="rounded-md border border-indigo-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
          writes research state: {writesResearchState ? "yes" : "no"}
        </span>
        <span className="rounded-md border border-indigo-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
          writes evidence: {writesEvidence ? "yes" : "no"}
        </span>
        {state ? (
          <span className="rounded-md border border-indigo-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
            state steps: {state.steps.length}
          </span>
        ) : null}
      </div>

      {batch ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Observation batch
            </span>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
              {researchStatusLabel(batch.status)}
            </span>
            {batch.rejected_sources.length > 0 ? (
              <span className="rounded-full border border-border/70 px-2 py-0.5 text-[11px] text-muted-foreground">
                {batch.rejected_sources.length} rejected
              </span>
            ) : null}
          </div>
          <ResearchSourceRecordList
            title="Accepted observations"
            records={batch.observations}
          />
          {batch.rejected_sources.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {batch.rejected_sources.slice(0, 4).flatMap((source, index) =>
                source.reason_codes.map((reason) => (
                  <span
                    key={`${source.source_title}-${reason}-${index}`}
                    className="rounded-md border border-border/70 px-1.5 py-0.5 text-[11px] text-muted-foreground"
                  >
                    {researchReasonLabel(reason)}
                  </span>
                ))
              )}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="mt-3 rounded-lg border border-border/60 bg-background/60 p-2 text-xs text-muted-foreground">
          No observation batch was included with this collection result.
        </p>
      )}

      {state?.state.next_actions.length ? (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          Next: {state.state.next_actions.slice(0, 3).join("; ")}
        </p>
      ) : null}
    </section>
  )
}

function ResearchEvidenceAdmissionPanel({
  result,
}: {
  result: ResearchEvidenceAdmissionResult
}) {
  const writesEvidence = asBoolean(result.metadata.writes_evidence)

  return (
    <section className="mt-3 rounded-xl border border-rose-500/30 bg-rose-50/70 p-3 text-sm text-rose-950 dark:bg-rose-950/20 dark:text-rose-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-rose-700 dark:text-rose-300" />
        <span className="font-semibold">Research evidence admission</span>
        <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-medium text-rose-800 dark:bg-rose-900/60 dark:text-rose-100">
          {researchStatusLabel(result.status)}
        </span>
        <span className="rounded-full border border-rose-400/50 px-2 py-0.5 text-[11px] text-rose-700 dark:text-rose-200">
          {result.contract_version}
        </span>
        <span className="rounded-full border border-rose-400/50 px-2 py-0.5 text-[11px] text-rose-700 dark:text-rose-200">
          allowed: {result.allowed ? "yes" : "no"}
        </span>
        <span className="rounded-full border border-rose-400/50 px-2 py-0.5 text-[11px] text-rose-700 dark:text-rose-200">
          writes evidence: {writesEvidence ? "yes" : "no"}
        </span>
      </div>

      <article className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          {result.evidence.source_url ? (
            <a
              href={result.evidence.source_url}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-primary hover:underline"
            >
              {result.evidence.source_title || result.evidence.source_url}
            </a>
          ) : (
            <span className="font-medium text-foreground">
              {result.evidence.source_title || "Evidence source"}
            </span>
          )}
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {result.evidence.quality}
          </span>
          <span className="rounded-full border border-border/70 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            relevance {result.evidence.relevance}
          </span>
        </div>
        {result.evidence.claim ? (
          <p className="mt-1 leading-5 text-foreground">{result.evidence.claim}</p>
        ) : null}
        {result.evidence.excerpt ? (
          <p className="mt-1 leading-5 text-muted-foreground">
            {result.evidence.excerpt}
          </p>
        ) : null}
      </article>

      {result.reason_codes.length > 0 || result.warning_codes.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {result.reason_codes.map((reason) => (
            <span
              key={`reason-${reason}`}
              className="rounded-md border border-rose-400/40 px-1.5 py-0.5 text-[11px] text-rose-800 dark:text-rose-100"
            >
              {researchReasonLabel(reason)}
            </span>
          ))}
          {result.warning_codes.map((warning) => (
            <span
              key={`warning-${warning}`}
              className="rounded-md border border-amber-400/40 px-1.5 py-0.5 text-[11px] text-amber-800 dark:text-amber-100"
            >
              {researchReasonLabel(warning)}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function ResearchStateTimelinePanel({
  result,
}: {
  result: ResearchStateResult
}) {
  const visibleSteps = result.steps.slice(-8)
  const visibleEvidence = result.evidence.slice(0, 5)

  return (
    <section className="mt-3 rounded-xl border border-slate-500/30 bg-slate-50/80 p-3 text-sm text-slate-950 dark:bg-slate-950/30 dark:text-slate-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-slate-700 dark:text-slate-300" />
        <span className="font-semibold">Research state timeline</span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-800 dark:bg-slate-900/60 dark:text-slate-100">
          {researchStatusLabel(result.run.status)}
        </span>
        <span className="rounded-full border border-slate-400/50 px-2 py-0.5 text-[11px] text-slate-700 dark:text-slate-200">
          {researchReasonLabel(result.run.mode)}
        </span>
        <span className="rounded-full border border-slate-400/50 px-2 py-0.5 text-[11px] text-slate-700 dark:text-slate-200">
          {result.steps.length} steps
        </span>
        <span className="rounded-full border border-slate-400/50 px-2 py-0.5 text-[11px] text-slate-700 dark:text-slate-200">
          {result.evidence.length} evidence
        </span>
      </div>

      {result.run.objective ? (
        <p className="mt-2 text-xs leading-5 text-slate-900/90 dark:text-slate-100/85">
          {result.run.objective}
        </p>
      ) : null}

      {result.state.known_facts.length > 0 || result.state.gaps.length > 0 || result.state.conflicts.length > 0 ? (
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          {result.state.known_facts.length > 0 ? (
            <div className="rounded-lg border border-border/70 bg-background/70 p-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Known facts
              </div>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                {result.state.known_facts.slice(0, 4).map((fact) => (
                  <li key={fact}>{fact}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {result.state.gaps.length > 0 ? (
            <div className="rounded-lg border border-border/70 bg-background/70 p-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Gaps
              </div>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                {result.state.gaps.slice(0, 4).map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {result.state.conflicts.length > 0 ? (
            <div className="rounded-lg border border-border/70 bg-background/70 p-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Conflicts
              </div>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                {result.state.conflicts.slice(0, 4).map((conflict) => (
                  <li key={conflict}>{conflict}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {visibleSteps.length > 0 ? (
        <div className="mt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Recent steps
          </div>
          <div className="mt-2 space-y-2">
            {visibleSteps.map((step, index) => (
              <article
                key={`${step.id || index}-${step.step_type}-${step.status}`}
                className="rounded-lg border border-border/70 bg-background/70 p-2 text-xs"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-foreground">
                    {researchReasonLabel(step.step_type)}
                  </span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                    {researchStatusLabel(step.status)}
                  </span>
                  {step.duration_ms > 0 ? (
                    <span className="rounded-full border border-border/70 px-2 py-0.5 text-[11px] text-muted-foreground">
                      {step.duration_ms} ms
                    </span>
                  ) : null}
                </div>
                {step.title || step.query || step.url ? (
                  <p className="mt-1 leading-5 text-muted-foreground">
                    {step.title || step.query || step.url}
                  </p>
                ) : null}
                {step.rationale ? (
                  <p className="mt-1 leading-5 text-muted-foreground">
                    {step.rationale}
                  </p>
                ) : null}
                {step.error ? (
                  <p className="mt-1 leading-5 text-destructive">{step.error}</p>
                ) : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {visibleEvidence.length > 0 ? (
        <div className="mt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Evidence store
          </div>
          <div className="mt-2 space-y-2">
            {visibleEvidence.map((evidence, index) => (
              <article
                key={`${evidence.id || index}-${evidence.claim}`}
                className="rounded-lg border border-border/70 bg-background/70 p-2 text-xs"
              >
                <div className="flex flex-wrap items-center gap-2">
                  {evidence.source_url ? (
                    <a
                      href={evidence.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium text-primary hover:underline"
                    >
                      {evidence.source_title || evidence.source_url}
                    </a>
                  ) : (
                    <span className="font-medium text-foreground">
                      {evidence.source_title || "Evidence source"}
                    </span>
                  )}
                  <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {evidence.quality}
                  </span>
                  <span className="rounded-full border border-border/70 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    relevance {evidence.relevance}
                  </span>
                </div>
                <p className="mt-1 leading-5 text-foreground">{evidence.claim}</p>
                {evidence.excerpt ? (
                  <p className="mt-1 leading-5 text-muted-foreground">
                    {evidence.excerpt}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {result.state.next_actions.length > 0 ? (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          Next: {result.state.next_actions.slice(0, 3).join("; ")}
        </p>
      ) : null}
    </section>
  )
}

function RecommendationResearchCandidateCard({
  candidate,
  label,
}: {
  candidate: RecommendationResearchCandidate
  label: string
}) {
  const support = candidate.research_support.slice(0, 3)
  const reasons = candidate.personalization_reasons.slice(0, 4)
  const limitations = candidate.limitations.slice(0, 4)
  const suppressionReasons = candidate.suppression_reasons.slice(0, 4)

  return (
    <article className="rounded-lg border border-border/70 bg-background/70 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-foreground">
          {candidate.rank > 0 ? `#${candidate.rank} ` : null}
          {candidate.title}
        </span>
        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
          {label}
        </span>
        {candidate.recommendation_score !== null ? (
          <span className="rounded-full border border-border/70 px-2 py-0.5 text-[11px] text-muted-foreground">
            score {candidate.recommendation_score.toFixed(2)}
          </span>
        ) : null}
      </div>

      {candidate.authors.length > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          {candidate.authors.join(", ")}
        </p>
      ) : null}

      {candidate.fit_summary || candidate.summary ? (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          {candidate.fit_summary || candidate.summary}
        </p>
      ) : null}

      {candidate.source_url || candidate.source_name ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Source:{" "}
          {candidate.source_url ? (
            <a
              href={candidate.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-primary hover:underline"
            >
              {candidate.source_name || candidate.source_url}
            </a>
          ) : (
            <span>{candidate.source_name}</span>
          )}
        </p>
      ) : null}

      {reasons.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {reasons.map((reason) => (
            <span
              key={`${candidate.title}-${reason}`}
              className="rounded-md border border-sky-400/40 bg-sky-50/50 px-1.5 py-0.5 text-[11px] text-sky-800 dark:bg-sky-950/20 dark:text-sky-100"
            >
              {reason}
            </span>
          ))}
        </div>
      ) : null}

      {support.length > 0 ? (
        <div className="mt-2 space-y-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Verified research support
          </div>
          {support.map((item, index) => (
            <div
              key={`${candidate.title}-${item.claim}-${index}`}
              className="rounded-md border border-border/70 bg-background/60 p-2 text-xs"
            >
              <div className="flex flex-wrap items-center gap-1.5">
                {item.source_url ? (
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-primary hover:underline"
                  >
                    {item.source_title || item.source_url}
                  </a>
                ) : (
                  <span className="font-medium text-foreground">
                    {item.source_title || "Verified claim"}
                  </span>
                )}
                <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {item.quality}
                </span>
              </div>
              <p className="mt-1 leading-5 text-muted-foreground">{item.claim}</p>
            </div>
          ))}
        </div>
      ) : null}

      {limitations.length > 0 || suppressionReasons.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {limitations.map((limitation) => (
            <span
              key={`${candidate.title}-${limitation}`}
              className="rounded-md border border-border/70 px-1.5 py-0.5 text-[11px] text-muted-foreground"
            >
              {researchReasonLabel(limitation)}
            </span>
          ))}
          {suppressionReasons.map((reason) => (
            <span
              key={`${candidate.title}-${reason}`}
              className="rounded-md border border-amber-400/40 px-1.5 py-0.5 text-[11px] text-amber-800 dark:text-amber-100"
            >
              {reasonLabel(reason)}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  )
}

function RecommendationResearchCandidateSection({
  title,
  candidates,
  label,
  emptyText,
}: {
  title: string
  candidates: RecommendationResearchCandidate[]
  label: string
  emptyText?: string
}) {
  const visible = candidates.slice(0, 4)

  if (visible.length === 0) {
    return emptyText ? (
      <p className="mt-2 rounded-lg border border-border/60 bg-background/60 p-2 text-xs text-muted-foreground">
        {emptyText}
      </p>
    ) : null
  }

  return (
    <div className="mt-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="mt-2 space-y-2">
        {visible.map((candidate, index) => (
          <RecommendationResearchCandidateCard
            key={`${title}-${candidate.title}-${index}`}
            candidate={candidate}
            label={label}
          />
        ))}
      </div>
      {candidates.length > visible.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Showing {visible.length} of {candidates.length} candidates.
        </p>
      ) : null}
    </div>
  )
}

function bookTurnRouteLabel(route: string): string {
  if (route === "ordinary_recommendation") {
    return "ordinary recommendation"
  }
  if (route === "researched_recommendation") {
    return "researched recommendation"
  }
  if (route === "recommendation_history") {
    return "history / explanation"
  }
  if (route === "memory_update") {
    return "memory update"
  }
  if (route === "memory_management") {
    return "memory management"
  }
  if (route === "deep_research") {
    return "deep research"
  }
  if (route === "research_report") {
    return "research report"
  }
  return researchReasonLabel(route)
}

function BookTurnOrchestrationPanel({
  result,
}: {
  result: BookTurnOrchestrationResult
}) {
  const visibleSteps = result.route_steps.slice(0, 7)
  const deniedTools =
    result.denied_tools.length > 0 ? result.denied_tools : result.policy.denied_tools
  const responseBoundary = result.response_boundary || result.policy.response_boundary
  const constraints = result.personalization_constraints
  const workflow = result.recommendation_research_workflow
  const sideEffects = [
    {
      label: "memory",
      value: asBoolean(result.metadata.writes_long_term_memory),
    },
    {
      label: "recommendation events",
      value: asBoolean(result.metadata.writes_recommendation_events),
    },
    {
      label: "research state",
      value: asBoolean(result.metadata.writes_research_state),
    },
    {
      label: "evidence",
      value: asBoolean(result.metadata.writes_evidence),
    },
  ]
  const enabledSideEffects = sideEffects.filter((item) => item.value)
  const policyFlags = [
    { label: "answer", value: result.policy.can_answer_question },
    { label: "memory search", value: result.policy.can_search_memory },
    { label: "memory write", value: result.policy.can_write_memory },
    { label: "book search", value: result.policy.can_search_books },
    { label: "history", value: result.policy.can_view_recommendation_history },
    { label: "research", value: result.policy.can_start_research },
    { label: "research tools", value: result.policy.can_use_research_tools },
  ]
  const hasConstraintTerms = Boolean(
    constraints
    && (
      constraints.preferred_terms.length > 0
      || constraints.avoided_terms.length > 0
      || constraints.favorite_authors.length > 0
      || constraints.disliked_authors.length > 0
      || constraints.search_terms_added.length > 0
    )
  )

  return (
    <section className="mt-3 rounded-xl border border-sky-500/30 bg-sky-50/70 p-3 text-sm text-sky-950 dark:bg-sky-950/20 dark:text-sky-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-sky-700 dark:text-sky-300" />
        <span className="font-semibold">Book turn orchestration</span>
        <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-800 dark:bg-sky-900/60 dark:text-sky-100">
          {bookTurnRouteLabel(result.route)}
        </span>
        <span className="rounded-full border border-sky-400/50 px-2 py-0.5 text-[11px] text-sky-700 dark:text-sky-200">
          {result.contract_version}
        </span>
        {result.history_mode ? (
          <span className="rounded-full border border-sky-400/50 px-2 py-0.5 text-[11px] text-sky-700 dark:text-sky-200">
            {researchReasonLabel(result.history_mode)}
          </span>
        ) : null}
      </div>

      {result.query ? (
        <p className="mt-2 text-xs leading-5 text-sky-900/90 dark:text-sky-100/85">
          {result.query}
        </p>
      ) : null}

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Intent
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {researchReasonLabel(result.policy.intent.primary_intent)}
            {result.policy.intent.intents.length > 1
              ? ` + ${result.policy.intent.intents.length - 1}`
              : ""}
          </p>
        </div>
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Boundary
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {responseBoundary || "default assistant response"}
          </p>
        </div>
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Side effects
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {enabledSideEffects.length > 0
              ? enabledSideEffects.map((item) => item.label).join(", ")
              : "read-only plan"}
            {asBoolean(result.metadata.external_call) ? " + external call" : ""}
            {asBoolean(result.metadata.executes_planned_tools) ? " + executes tools" : ""}
          </p>
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Next tools
          </div>
          {result.recommended_next_tools.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {result.recommended_next_tools.slice(0, 8).map((tool) => (
                <span
                  key={tool}
                  className="rounded-md border border-sky-400/40 px-1.5 py-0.5 text-[11px] text-sky-700 dark:text-sky-200"
                >
                  {tool}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">No tool suggested.</p>
          )}
        </div>

        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Denied tools
          </div>
          {deniedTools.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {deniedTools.slice(0, 8).map((tool) => (
                <span
                  key={tool}
                  className="rounded-md border border-amber-400/50 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800 dark:bg-amber-950/30 dark:text-amber-100"
                >
                  {tool}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">No denied tool.</p>
          )}
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Policy gates
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {policyFlags.map((flag) => (
            <span
              key={flag.label}
              className={cn(
                "rounded-md border px-1.5 py-0.5 text-[11px]",
                flag.value
                  ? "border-emerald-400/50 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-100"
                  : "border-border/70 text-muted-foreground"
              )}
            >
              {flag.value ? "allow" : "block"} {flag.label}
            </span>
          ))}
        </div>
      </div>

      {visibleSteps.length > 0 ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Route steps
          </div>
          <div className="mt-2 space-y-2">
            {visibleSteps.map((step, index) => (
              <article
                key={`${step.name}-${step.status}-${index}`}
                className="rounded-lg border border-border/60 bg-background/60 p-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-foreground">{step.name}</span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                    {researchStatusLabel(step.status)}
                  </span>
                </div>
                {step.reason ? (
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    {step.reason}
                  </p>
                ) : null}
                {step.required_inputs.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {step.required_inputs.map((input) => (
                      <span
                        key={`${step.name}-${input}`}
                        className="rounded-md border border-border/70 px-1.5 py-0.5 text-[11px] text-muted-foreground"
                      >
                        {researchReasonLabel(input)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
          {result.route_steps.length > visibleSteps.length ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Showing {visibleSteps.length} of {result.route_steps.length} steps.
            </p>
          ) : null}
        </div>
      ) : null}

      {constraints && hasConstraintTerms ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Personalization constraints
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {constraints.preferred_terms.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Preferred: {constraints.preferred_terms.slice(0, 5).join(", ")}
              </p>
            ) : null}
            {constraints.avoided_terms.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Avoided: {constraints.avoided_terms.slice(0, 5).join(", ")}
              </p>
            ) : null}
            {constraints.favorite_authors.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Authors: {constraints.favorite_authors.slice(0, 5).join(", ")}
              </p>
            ) : null}
            {constraints.disliked_authors.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Avoid authors: {constraints.disliked_authors.slice(0, 5).join(", ")}
              </p>
            ) : null}
            {constraints.search_terms_added.length > 0 ? (
              <p className="text-xs text-muted-foreground sm:col-span-2">
                Search terms added: {constraints.search_terms_added.join(", ")}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      {workflow ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Nested research workflow
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="rounded-md border border-sky-400/40 px-1.5 py-0.5 text-[11px] text-sky-700 dark:text-sky-200">
              {researchStatusLabel(workflow.status)}
            </span>
            <span className="rounded-md border border-sky-400/40 px-1.5 py-0.5 text-[11px] text-sky-700 dark:text-sky-200">
              {workflow.ready_to_fuse ? "ready to fuse" : "not ready"}
            </span>
            <span className="rounded-md border border-sky-400/40 px-1.5 py-0.5 text-[11px] text-sky-700 dark:text-sky-200">
              {workflow.fresh_candidate_count}/{workflow.candidate_count} fresh
            </span>
            <span className="rounded-md border border-sky-400/40 px-1.5 py-0.5 text-[11px] text-sky-700 dark:text-sky-200">
              {workflow.verified_claim_count} verified claims
            </span>
          </div>
          {workflow.next_action_hint ? (
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {workflow.next_action_hint}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

function RecommendationResearchWorkflowPanel({
  result,
}: {
  result: RecommendationResearchWorkflowResult
}) {
  const visibleSteps = result.workflow_steps.slice(0, 7)
  const constraints = result.personalization_constraints
  const hasConstraintTerms = Boolean(
    constraints
    && (
      constraints.preferred_terms.length > 0
      || constraints.avoided_terms.length > 0
      || constraints.favorite_authors.length > 0
      || constraints.disliked_authors.length > 0
      || constraints.search_terms_added.length > 0
    )
  )

  return (
    <section className="mt-3 rounded-xl border border-indigo-500/30 bg-indigo-50/70 p-3 text-sm text-indigo-950 dark:bg-indigo-950/20 dark:text-indigo-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-indigo-700 dark:text-indigo-300" />
        <span className="font-semibold">Recommendation research workflow</span>
        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-800 dark:bg-indigo-900/60 dark:text-indigo-100">
          {researchStatusLabel(result.status)}
        </span>
        <span className="rounded-full border border-indigo-400/50 px-2 py-0.5 text-[11px] text-indigo-700 dark:text-indigo-200">
          {result.ready_to_fuse ? "ready to fuse" : "not ready"}
        </span>
        <span className="rounded-full border border-indigo-400/50 px-2 py-0.5 text-[11px] text-indigo-700 dark:text-indigo-200">
          {result.fresh_candidate_count}/{result.candidate_count} fresh
        </span>
        <span className="rounded-full border border-indigo-400/50 px-2 py-0.5 text-[11px] text-indigo-700 dark:text-indigo-200">
          {result.verified_claim_count} verified claims
        </span>
      </div>

      {result.query ? (
        <p className="mt-2 text-xs leading-5 text-indigo-900/90 dark:text-indigo-100/85">
          {result.query}
        </p>
      ) : null}

      {result.next_action_hint ? (
        <p className="mt-2 rounded-lg border border-indigo-400/30 bg-background/70 p-2 text-xs leading-5 text-muted-foreground">
          {result.next_action_hint}
        </p>
      ) : null}

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Next tools
          </div>
          {result.recommended_next_tools.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {result.recommended_next_tools.slice(0, 6).map((tool) => (
                <span
                  key={tool}
                  className="rounded-md border border-indigo-400/40 px-1.5 py-0.5 text-[11px] text-indigo-700 dark:text-indigo-200"
                >
                  {tool}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">No next tool suggested.</p>
          )}
        </div>

        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Missing inputs
          </div>
          {result.missing_inputs.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {result.missing_inputs.map((input) => (
                <span
                  key={input}
                  className="rounded-md border border-amber-400/50 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800 dark:bg-amber-950/30 dark:text-amber-100"
                >
                  {researchReasonLabel(input)}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">All required inputs are present.</p>
          )}
        </div>
      </div>

      {visibleSteps.length > 0 ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Workflow steps
          </div>
          <div className="mt-2 space-y-2">
            {visibleSteps.map((step, index) => (
              <article
                key={`${step.name}-${step.status}-${index}`}
                className="rounded-lg border border-border/60 bg-background/60 p-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-foreground">{step.name}</span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                    {researchStatusLabel(step.status)}
                  </span>
                </div>
                {step.reason ? (
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    {step.reason}
                  </p>
                ) : null}
                {step.required_inputs.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {step.required_inputs.map((input) => (
                      <span
                        key={`${step.name}-${input}`}
                        className="rounded-md border border-border/70 px-1.5 py-0.5 text-[11px] text-muted-foreground"
                      >
                        {researchReasonLabel(input)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
          {result.workflow_steps.length > visibleSteps.length ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Showing {visibleSteps.length} of {result.workflow_steps.length} steps.
            </p>
          ) : null}
        </div>
      ) : null}

      {constraints && hasConstraintTerms ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Personalization constraints
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {constraints.preferred_terms.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Preferred: {constraints.preferred_terms.slice(0, 5).join(", ")}
              </p>
            ) : null}
            {constraints.avoided_terms.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Avoided: {constraints.avoided_terms.slice(0, 5).join(", ")}
              </p>
            ) : null}
            {constraints.favorite_authors.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Authors: {constraints.favorite_authors.slice(0, 5).join(", ")}
              </p>
            ) : null}
            {constraints.disliked_authors.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Avoid authors: {constraints.disliked_authors.slice(0, 5).join(", ")}
              </p>
            ) : null}
            {constraints.search_terms_added.length > 0 ? (
              <p className="text-xs text-muted-foreground sm:col-span-2">
                Search terms added: {constraints.search_terms_added.join(", ")}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}

function RecommendationResearchRunnerPanel({
  result,
}: {
  result: RecommendationResearchRunnerResult
}) {
  const runtimeExecuted = asBoolean(result.metadata.runtime_executed)
  const fusionExecuted = asBoolean(result.metadata.fusion_executed)
  const writesResearchState = asBoolean(result.metadata.writes_research_state)
  const writesEvidence = asBoolean(result.metadata.writes_evidence)
  const observationCount = Number(result.metadata.observation_count ?? 0)
  const candidateCount = Number(result.metadata.candidate_count ?? result.workflow_after.candidate_count)

  return (
    <section className="mt-3 rounded-xl border border-violet-500/30 bg-violet-50/70 p-3 text-sm text-violet-950 dark:bg-violet-950/20 dark:text-violet-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-violet-700 dark:text-violet-300" />
        <span className="font-semibold">Recommendation research runner</span>
        <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-medium text-violet-800 dark:bg-violet-900/60 dark:text-violet-100">
          {researchStatusLabel(result.status)}
        </span>
        <span className="rounded-full border border-violet-400/50 px-2 py-0.5 text-[11px] text-violet-700 dark:text-violet-200">
          {runtimeExecuted ? "runtime executed" : "runtime skipped"}
        </span>
        <span className="rounded-full border border-violet-400/50 px-2 py-0.5 text-[11px] text-violet-700 dark:text-violet-200">
          {fusionExecuted ? "fusion executed" : "fusion pending"}
        </span>
        <span className="rounded-full border border-violet-400/50 px-2 py-0.5 text-[11px] text-violet-700 dark:text-violet-200">
          {result.contract_version}
        </span>
      </div>

      {result.query ? (
        <p className="mt-2 text-xs leading-5 text-violet-900/90 dark:text-violet-100/85">
          {result.query}
        </p>
      ) : null}

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Candidates
          </div>
          <p className="mt-1 text-sm font-medium text-foreground">{candidateCount}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Observations
          </div>
          <p className="mt-1 text-sm font-medium text-foreground">{observationCount}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Research writes
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {writesResearchState ? "state" : "no state"}
            {writesEvidence ? " + evidence" : ""}
          </p>
        </div>
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Output
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {result.recommendation_report
              ? `${result.recommendation_report.supported_count}/${result.recommendation_report.candidate_count} supported`
              : "no fused report"}
          </p>
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Before
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="rounded-md border border-violet-400/40 px-1.5 py-0.5 text-[11px] text-violet-700 dark:text-violet-200">
              {researchStatusLabel(result.workflow_before.status)}
            </span>
            <span className="rounded-md border border-violet-400/40 px-1.5 py-0.5 text-[11px] text-violet-700 dark:text-violet-200">
              {result.workflow_before.ready_to_fuse ? "ready" : "not ready"}
            </span>
          </div>
          {result.workflow_before.next_action_hint ? (
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {result.workflow_before.next_action_hint}
            </p>
          ) : null}
        </div>

        <div className="rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            After
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="rounded-md border border-violet-400/40 px-1.5 py-0.5 text-[11px] text-violet-700 dark:text-violet-200">
              {researchStatusLabel(result.workflow_after.status)}
            </span>
            <span className="rounded-md border border-violet-400/40 px-1.5 py-0.5 text-[11px] text-violet-700 dark:text-violet-200">
              {result.workflow_after.ready_to_fuse ? "ready" : "not ready"}
            </span>
          </div>
          {result.workflow_after.next_action_hint ? (
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {result.workflow_after.next_action_hint}
            </p>
          ) : null}
        </div>
      </div>

      {result.runtime ? (
        <p className="mt-3 rounded-lg border border-violet-400/30 bg-background/70 p-2 text-xs text-muted-foreground">
          Local research runtime: {researchStatusLabel(result.runtime.status)}
          {result.runtime.run_id ? ` (${result.runtime.run_id})` : null}
        </p>
      ) : null}
    </section>
  )
}

function RecommendationResearchReportPanel({
  result,
}: {
  result: RecommendationResearchReportResult
}) {
  return (
    <section className="mt-3 rounded-xl border border-sky-500/30 bg-sky-50/70 p-3 text-sm text-sky-950 dark:bg-sky-950/20 dark:text-sky-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-sky-700 dark:text-sky-300" />
        <span className="font-semibold">Recommendation research report</span>
        <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-800 dark:bg-sky-900/60 dark:text-sky-100">
          {researchStatusLabel(result.status)}
        </span>
        <span className="rounded-full border border-sky-400/50 px-2 py-0.5 text-[11px] text-sky-700 dark:text-sky-200">
          {result.contract_version}
        </span>
        <span className="rounded-full border border-sky-400/50 px-2 py-0.5 text-[11px] text-sky-700 dark:text-sky-200">
          {result.supported_count}/{result.candidate_count} supported
        </span>
        {result.verified_claim_count > 0 ? (
          <span className="rounded-full border border-sky-400/50 px-2 py-0.5 text-[11px] text-sky-700 dark:text-sky-200">
            {result.verified_claim_count} verified claims
          </span>
        ) : null}
      </div>

      {result.query ? (
        <p className="mt-2 text-xs leading-5 text-sky-900/90 dark:text-sky-100/85">
          {result.query}
        </p>
      ) : null}

      {result.research_report_status || result.research_report_contract_version ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Research report: {researchStatusLabel(result.research_report_status || "unknown")}
          {result.research_report_contract_version
            ? ` (${result.research_report_contract_version})`
            : null}
        </p>
      ) : null}

      <RecommendationResearchCandidateSection
        title="Recommended with verified research"
        candidates={result.recommended_candidates}
        label="supported"
        emptyText="No candidates are supported by verified research claims yet."
      />

      <RecommendationResearchCandidateSection
        title="Candidates without verified support"
        candidates={result.unsupported_candidates}
        label="unsupported"
      />

      <RecommendationResearchCandidateSection
        title="Suppressed candidates"
        candidates={result.suppressed_candidates}
        label="suppressed"
      />

      {result.limitations.length > 0 ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Limitations
          </div>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {result.limitations.slice(0, 5).map((limitation) => (
              <li key={limitation}>{researchReasonLabel(limitation)}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}

function ResearchClaimList({
  title,
  claims,
  emptyText,
}: {
  title: string
  claims: ResearchClaimAdmissionDecision[]
  emptyText?: string
}) {
  const visible = claims.slice(0, 5)

  if (visible.length === 0) {
    return emptyText ? (
      <p className="mt-2 rounded-lg border border-border/60 bg-background/60 p-2 text-xs text-muted-foreground">
        {emptyText}
      </p>
    ) : null
  }

  return (
    <div className="mt-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="mt-2 space-y-2">
        {visible.map((claim, index) => (
          <article
            key={`${claim.status}-${claim.claim}-${index}`}
            className="rounded-lg border border-border/70 bg-background/70 p-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-foreground">{claim.claim}</span>
              <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                {claim.quality}
              </span>
            </div>
            {claim.explanation ? (
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {claim.explanation}
              </p>
            ) : null}
            {claim.reason_codes.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {claim.reason_codes.map((reason) => (
                  <span
                    key={`${claim.claim}-${reason}`}
                    className="rounded-md border border-border/70 px-1.5 py-0.5 text-[11px] text-muted-foreground"
                  >
                    {researchReasonLabel(reason)}
                  </span>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
      {claims.length > visible.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Showing {visible.length} of {claims.length} claims.
        </p>
      ) : null}
    </div>
  )
}

function ResearchFinalAnswerPanel({
  result,
}: {
  result: ResearchFinalAnswerResult
}) {
  const sources = result.sources.slice(0, 5)
  const omittedCount =
    result.omitted_uncertain_claims.length + result.omitted_rejected_claims.length

  return (
    <section className="mt-3 rounded-xl border border-emerald-500/30 bg-emerald-50/70 p-3 text-sm text-emerald-950 dark:bg-emerald-950/20 dark:text-emerald-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-emerald-700 dark:text-emerald-300" />
        <span className="font-semibold">Research final answer</span>
        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-100">
          {researchStatusLabel(result.answer_status)}
        </span>
        <span className="rounded-full border border-emerald-400/50 px-2 py-0.5 text-[11px] text-emerald-700 dark:text-emerald-200">
          {result.contract_version}
        </span>
        {omittedCount > 0 ? (
          <span className="rounded-full border border-emerald-400/50 px-2 py-0.5 text-[11px] text-emerald-700 dark:text-emerald-200">
            {omittedCount} omitted
          </span>
        ) : null}
      </div>

      {result.objective ? (
        <p className="mt-2 text-xs leading-5 text-emerald-900/90 dark:text-emerald-100/85">
          {result.objective}
        </p>
      ) : null}

      {result.answer ? (
        <div className="mt-3 whitespace-pre-wrap rounded-lg border border-emerald-400/30 bg-background/70 p-3 text-sm leading-6 text-foreground">
          {result.answer}
        </div>
      ) : null}

      <ResearchClaimList
        title="Verified facts used"
        claims={result.verified_claims}
        emptyText="No verified facts were used in the final answer."
      />
      <ResearchClaimList
        title="Omitted uncertainty"
        claims={result.omitted_uncertain_claims}
      />
      <ResearchClaimList
        title="Omitted rejected claims"
        claims={result.omitted_rejected_claims}
      />

      {result.limitations.length > 0 ? (
        <div className="mt-3 rounded-lg border border-border/70 bg-background/70 p-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Limitations
          </div>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {result.limitations.slice(0, 5).map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {sources.length > 0 ? (
        <div className="mt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Sources used
          </div>
          <div className="mt-2 space-y-1.5">
            {sources.map((source) => (
              <div
                key={source.evidence_id || `${source.source_title}-${source.claim}`}
                className="rounded-lg border border-border/70 bg-background/70 p-2 text-xs"
              >
                {source.source_url ? (
                  <a
                    href={source.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-primary hover:underline"
                  >
                    {source.source_title || source.source_url}
                  </a>
                ) : (
                  <span className="font-medium text-foreground">{source.source_title}</span>
                )}
                <span className="ml-2 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {source.quality}
                </span>
                {source.claim ? (
                  <p className="mt-1 leading-5 text-muted-foreground">{source.claim}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}

function ResearchReportPanel({
  result,
}: {
  result: ResearchReportResult
}) {
  const sources = result.sources.slice(0, 5)
  const contextConstraints = result.memory_context.constraints.slice(0, 4)

  return (
    <section className="mt-3 rounded-xl border border-cyan-500/30 bg-cyan-50/70 p-3 text-sm text-cyan-950 dark:bg-cyan-950/20 dark:text-cyan-100">
      <div className="flex flex-wrap items-center gap-2">
        <BrainIcon className="size-4 text-cyan-700 dark:text-cyan-300" />
        <span className="font-semibold">Research report</span>
        <span className="rounded-full bg-cyan-100 px-2 py-0.5 text-[11px] font-medium text-cyan-800 dark:bg-cyan-900/60 dark:text-cyan-100">
          {researchStatusLabel(result.report_status)}
        </span>
        <span className="rounded-full border border-cyan-400/50 px-2 py-0.5 text-[11px] text-cyan-700 dark:text-cyan-200">
          {result.contract_version}
        </span>
      </div>

      {result.objective ? (
        <p className="mt-2 text-xs leading-5 text-cyan-900/90 dark:text-cyan-100/85">
          {result.objective}
        </p>
      ) : null}

      {contextConstraints.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {contextConstraints.map((constraint) => (
            <span
              key={constraint}
              className="rounded-md border border-cyan-400/40 bg-background/60 px-1.5 py-0.5 text-[11px] text-muted-foreground"
              title="CurrentMemory context, not research evidence"
            >
              {constraint}
            </span>
          ))}
        </div>
      ) : null}

      <ResearchClaimList
        title="Verified findings"
        claims={result.verified_claims}
        emptyText="No verified findings are ready yet."
      />
      <ResearchClaimList
        title="Uncertainty"
        claims={result.uncertain_claims}
      />
      <ResearchClaimList
        title="Rejected claims"
        claims={result.rejected_claims}
      />

      {result.gaps.length > 0 || result.conflicts.length > 0 ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {result.gaps.length > 0 ? (
            <div className="rounded-lg border border-border/70 bg-background/70 p-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Open gaps
              </div>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                {result.gaps.slice(0, 4).map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {result.conflicts.length > 0 ? (
            <div className="rounded-lg border border-border/70 bg-background/70 p-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Conflicts
              </div>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                {result.conflicts.slice(0, 4).map((conflict) => (
                  <li key={conflict}>{conflict}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {sources.length > 0 ? (
        <div className="mt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Sources
          </div>
          <div className="mt-2 space-y-1.5">
            {sources.map((source) => (
              <div
                key={source.evidence_id || `${source.source_title}-${source.claim}`}
                className="rounded-lg border border-border/70 bg-background/70 p-2 text-xs"
              >
                {source.source_url ? (
                  <a
                    href={source.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-primary hover:underline"
                  >
                    {source.source_title || source.source_url}
                  </a>
                ) : (
                  <span className="font-medium text-foreground">{source.source_title}</span>
                )}
                <span className="ml-2 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {source.quality}
                </span>
                {source.claim ? (
                  <p className="mt-1 leading-5 text-muted-foreground">{source.claim}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {result.next_actions.length > 0 ? (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          Next: {result.next_actions.slice(0, 3).join("; ")}
        </p>
      ) : null}
    </section>
  )
}

export function ChatMessageItem({
  message,
  calledTools = [],
  thinkingContent = "",
  isStreaming = false,
  isSelected = false,
  onJumpToMessage,
  onSelectRequestId,
  onFollowUpQuestionClick,
}: ChatMessageItemProps) {
  const { t } = useI18n()
  const isUser = message.type === "human"
  const isAI = message.type === "ai"
  const isTool = message.type === "tool"
  const sources = parseSources(message)
  const [copied, setCopied] = useState(false)

  // Parse thinking content from message (for history) or use streaming content
  const historicalThinking = parseThinkingContent(message)
  const displayThinkingContent = thinkingContent || historicalThinking || ""
  const hasThinkingContent = Boolean(displayThinkingContent)

  // Ref for thinking content container - auto-scroll during streaming
  const thinkingContentRef = useRef<HTMLDivElement>(null)

  // Auto-scroll thinking content to bottom when content grows during streaming
  useEffect(() => {
    if (isStreaming && thinkingContent && thinkingContentRef.current) {
      thinkingContentRef.current.scrollTop = thinkingContentRef.current.scrollHeight
    }
  }, [isStreaming, thinkingContent])

  // Merge calledTools from streaming with stored tool_info from history
  // For streaming messages, use calledTools; for history messages, use stored tool_info
  const allTools = calledTools.length > 0 ? calledTools : parseStoredToolInfo(message)
  const hasToolCalls = allTools.length > 0
  const researchFinalAnswerResults =
    isAI && !isStreaming ? parseResearchFinalAnswerResults(allTools) : []
  const researchReportResults =
    isAI && !isStreaming ? parseResearchReportResults(allTools) : []
  const researchSourceToolResults =
    isAI && !isStreaming ? parseResearchSourceToolResults(allTools) : []
  const researchSourceCollectionResults =
    isAI && !isStreaming ? parseResearchSourceCollectionResults(allTools) : []
  const researchEvidenceAdmissionResults =
    isAI && !isStreaming ? parseResearchEvidenceAdmissionResults(allTools) : []
  const researchStateResults =
    isAI && !isStreaming ? parseResearchStateResults(allTools) : []
  const researchPythonAnalysisResults =
    isAI && !isStreaming ? parseResearchPythonAnalysisResults(allTools) : []
  const bookTurnOrchestrationResults =
    isAI && !isStreaming ? parseBookTurnOrchestrationResults(allTools) : []
  const recommendationResearchRunnerResults =
    isAI && !isStreaming ? parseRecommendationResearchRunnerResults(allTools) : []
  const recommendationResearchWorkflowResults =
    isAI && !isStreaming ? parseRecommendationResearchWorkflowResults(allTools) : []
  const recommendationResearchReportResults =
    isAI && !isStreaming ? parseRecommendationResearchReportResults(allTools) : []
  const recommendationHistoryResults =
    isAI && !isStreaming ? parseRecommendationHistoryResults(allTools) : []
  const followUpQuestions =
    isAI && !isStreaming
      ? extractFollowUpQuestions(message, calledTools)
      : []

  useEffect(() => {
    if (!copied) {
      return
    }

    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  const handleCopy = async () => {
    if (!message.content.trim()) {
      return
    }

    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
    } catch {
      // Ignore clipboard failures in unsupported environments.
    }
  }

  // Determine what to show in the action bar
  // Show brain icon if this AI message has request_id (for DAG viewing)
  const hasRequestId = Boolean(message.request_id)
  const showBrainIcon = hasRequestId

  // Get quoted message ID and user content from custom_data
  const quotedMessageId = message.custom_data?.quoted_message_id as string | undefined
  const userContent = message.custom_data?.user_content as string | undefined

  // Check if this is a quoted message (has quoted_message_id and user_content)
  const isQuotedMessage = isUser && quotedMessageId && userContent

  // Parse quoted content from message content for display
  // Format: "> quoted content\n\nuser message"
  const quotedParts = isQuotedMessage ? parseQuotedContent(message.content) : null

  // Truncate quoted content to 100 chars with underscore
  const getTruncatedQuote = (content: string) => {
    if (content.length > 100) {
      return `${content.slice(0, 100)}_`
    }
    return content
  }

  // Don't render tool type messages (tool call results)
  if (isTool) {
    return null
  }

  // For AI messages, don't render if there's no content, thinking content, or tool calls
  // This avoids empty bubbles
  // But during streaming with processing state, show the loader even without content
  if (isAI && !isStreaming && !message.content.trim() && !hasThinkingContent && !hasToolCalls) {
    return null
  }

  // During streaming, if there's no content, thinking, or tools, return null
  // The center loader (in chat-main-panel.tsx) will show instead
  if (isAI && isStreaming && !message.content.trim() && !hasThinkingContent && !hasToolCalls) {
    return null
  }

  return (
    <article
      id={`message-${message.local_id}`}
      className={cn("flex w-full items-center gap-2", isUser ? "flex-row-reverse justify-start" : "justify-start")}
    >
      <Message
        from={isUser ? "user" : "assistant"}
        className={cn(
          "min-w-0 shrink-0 transition-all duration-300",
          isUser
            ? "w-auto max-w-[72%] items-end ml-0"
            : "w-full max-w-[85%]",
          isAI && isSelected && "scale-[1.01]"
        )}
      >
        <MessageContent
          className={cn(
            "max-w-full overflow-visible rounded-3xl px-5 py-3.5 text-[15px] leading-relaxed transition-all duration-300",
            isUser
              ? "w-fit mr-3 bg-user-bubble text-user-bubble-foreground"
              : "w-full bg-ai-bubble text-foreground border border-border/50",
            // Add selected highlight for AI messages
            isAI && isSelected && [
              "border-primary/40 shadow-[0_0_0_1px_rgba(var(--primary),0.2),0_0_20px_rgba(var(--primary),0.15)]",
              "dark:shadow-[0_0_0_1px_rgba(var(--primary),0.3),0_0_30px_rgba(var(--primary),0.2)]"
            ],
          )}
        >
          {/* Sources */}
          {sources.length > 0 ? (
            <details className="rounded-lg border border-border/80 bg-background/70 p-2 text-xs mb-2">
              <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground">
                <ChevronDown className="size-3" />
                {t("message.sources", { count: sources.length })}
              </summary>
              <div className="mt-2 space-y-1">
                {sources.map((source) => (
                  <a
                    key={source.href}
                    href={source.href}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate text-primary hover:underline"
                  >
                    {source.title}
                  </a>
                ))}
              </div>
            </details>
          ) : null}


          {/* Thinking content display - show live reasoning and preserved history. */}
          {isAI && hasThinkingContent ? (
            <div className="rounded-lg border border-border/60 bg-muted/30 p-3 text-xs mb-2">
              <div className="flex items-center gap-2 mb-2">
                <BrainIcon className={cn("size-3.5 text-primary", isStreaming && "animate-pulse")} />
                <span className="font-medium text-muted-foreground">
                  {t("message.thinking") || "Thinking..."}
                </span>
              </div>
              <div ref={thinkingContentRef} className="whitespace-pre-wrap break-words text-muted-foreground max-h-48 overflow-y-auto">
                {displayThinkingContent}
              </div>
            </div>
          ) : null}

          {/* Tool calls display - ChatGPT style scrolling list */}
          {isAI && allTools.length > 0 && (isStreaming || !message.content.trim()) ? (
            <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-xs mb-2 max-h-32 overflow-y-auto">
              <div className="space-y-1.5">
                {allTools.map((tool, toolIndex) => {
                  const isCalling = tool.status === "calling"
                  const isCompleted = tool.status === "completed"
                  return (
                    <div
                      key={tool.id || `tool-${toolIndex}`}
                      className={cn(
                        "flex items-center gap-2 animate-in slide-in-from-left-2 duration-200",
                        toolIndex === allTools.length - 1 && isCalling && "bg-primary/5 -mx-1 px-1 rounded"
                      )}
                    >
                      {isCalling ? (
                        <Loader2 className="size-3 animate-spin text-primary" />
                      ) : isCompleted ? (
                        <CheckIcon className="size-3 text-green-500" />
                      ) : null}
                      <span className={cn(
                        "font-medium",
                        isCalling ? "text-foreground" : "text-muted-foreground"
                      )}>
                        {tool.name}
                      </span>
                      {isCalling && (
                        <span className="text-muted-foreground text-[10px] animate-pulse">
                          {t("message.toolRunning")}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}

          {/* Main message content */}
          {isAI ? (
            message.content ? (
              <MarkdownContent content={message.content} isStreaming={isStreaming} />
            ) : null
          ) : isQuotedMessage ? (
            // Render quoted message with separator - use user_content for display
            <div className="space-y-2">
              {/* Quoted content - clickable to jump to original, truncated to 100 chars */}
              <button
                type="button"
                onClick={() => {
                  if (quotedMessageId && onJumpToMessage) {
                    onJumpToMessage(quotedMessageId)
                  }
                }}
                disabled={!quotedMessageId || !onJumpToMessage}
                className={cn(
                  "text-sm text-user-bubble-foreground/70 whitespace-pre-wrap break-words text-left w-full",
                  quotedMessageId && onJumpToMessage && "cursor-pointer hover:text-user-bubble-foreground/90 underline underline-offset-2"
                )}
                title={quotedMessageId && onJumpToMessage ? t("message.jumpToOriginal") : undefined}
              >
                {quotedParts ? getTruncatedQuote(quotedParts.quotedContent) : "引用消息"}
              </button>
              {/* Separator line */}
              <Separator className="bg-user-bubble-foreground/30" />
              {/* User content - use user_content from custom_data */}
              <p className="whitespace-pre-wrap break-words text-sm leading-6">
                {userContent}
              </p>
            </div>
          ) : (
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {message.content}
            </p>
          )}

          {isAI && bookTurnOrchestrationResults.length > 0 ? (
            <div className="space-y-3">
              {bookTurnOrchestrationResults.map((result, index) => (
                <BookTurnOrchestrationPanel
                  key={`${result.route}-${result.query}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && recommendationResearchRunnerResults.length > 0 ? (
            <div className="space-y-3">
              {recommendationResearchRunnerResults.map((result, index) => (
                <RecommendationResearchRunnerPanel
                  key={`${result.query}-${result.status}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && recommendationResearchWorkflowResults.length > 0 ? (
            <div className="space-y-3">
              {recommendationResearchWorkflowResults.map((result, index) => (
                <RecommendationResearchWorkflowPanel
                  key={`${result.query}-${result.status}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && recommendationResearchReportResults.length > 0 ? (
            <div className="space-y-3">
              {recommendationResearchReportResults.map((result, index) => (
                <RecommendationResearchReportPanel
                  key={`${result.research_run_id}-${result.status}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && researchFinalAnswerResults.length > 0 ? (
            <div className="space-y-3">
              {researchFinalAnswerResults.map((result, index) => (
                <ResearchFinalAnswerPanel
                  key={`${result.run_id}-${result.answer_status}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && researchReportResults.length > 0 ? (
            <div className="space-y-3">
              {researchReportResults.map((result, index) => (
                <ResearchReportPanel
                  key={`${result.run_id}-${result.report_status}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && researchSourceToolResults.length > 0 ? (
            <div className="space-y-3">
              {researchSourceToolResults.map((result, index) => (
                <ResearchSourceToolPanel
                  key={`${result.result_mode}-${result.status}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && researchSourceCollectionResults.length > 0 ? (
            <div className="space-y-3">
              {researchSourceCollectionResults.map((result, index) => (
                <ResearchSourceCollectionPanel
                  key={`${result.run_id}-${result.status}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && researchEvidenceAdmissionResults.length > 0 ? (
            <div className="space-y-3">
              {researchEvidenceAdmissionResults.map((result, index) => (
                <ResearchEvidenceAdmissionPanel
                  key={`${result.status}-${result.evidence.claim}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && researchStateResults.length > 0 ? (
            <div className="space-y-3">
              {researchStateResults.map((result, index) => (
                <ResearchStateTimelinePanel
                  key={`${result.run.id}-${result.run.status}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && researchPythonAnalysisResults.length > 0 ? (
            <div className="space-y-3">
              {researchPythonAnalysisResults.map((result, index) => (
                <ResearchPythonAnalysisPanel
                  key={`${result.query}-${result.source_title}-${result.status}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && recommendationHistoryResults.length > 0 ? (
            <div className="space-y-3">
              {recommendationHistoryResults.map((result, index) => (
                <RecommendationHistoryPanel
                  key={`${result.history_mode}-${result.query}-${index}`}
                  result={result}
                />
              ))}
            </div>
          ) : null}

          {isAI && followUpQuestions.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2 border-t border-border/60 pt-3">
              {followUpQuestions.map((question) => (
                <button
                  key={`${question.toolCallId}-${question.id}`}
                  type="button"
                  onClick={() => onFollowUpQuestionClick?.(question, message)}
                  className="max-w-full rounded-lg border border-border/70 bg-background/70 px-3 py-1.5 text-left text-xs leading-5 text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
                  disabled={!onFollowUpQuestionClick}
                  title={question.reason || undefined}
                >
                  {question.question}
                </button>
              ))}
            </div>
          ) : null}
        </MessageContent>

        {/* AI message actions: copy, DAG view - below the bubble */}
        {isAI && !isStreaming ? (
          <div className="flex flex-col items-start">
            <div className="pt-1 flex items-center gap-1 justify-start">
              <button
                onClick={() => void handleCopy()}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
                title={copied ? t("common.copied") : t("common.copy")}
              >
                {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
              </button>

              {/* DAG icon - click to show this request's execution DAG */}
              {showBrainIcon && message.request_id ? (
                <button
                  type="button"
                  onClick={() => {
                    // Select this request_id to show its DAG
                    if (onSelectRequestId) {
                      onSelectRequestId(message.request_id || null)
                    }
                  }}
                  className={cn(
                    "p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer",
                    isSelected && "text-primary hover:text-primary"
                  )}
                  title={t("process.showProcess")}
                >
                  <BrainIcon className="size-4" />
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
      </Message>

      {/* User message: copy button on the left, vertically centered */}
      {isUser && (
        <button
          onClick={() => void handleCopy()}
          className="p-1.5 rounded-md text-muted-foreground/60 hover:text-foreground hover:bg-background/80 transition-colors cursor-pointer self-center shrink-0 opacity-60 hover:opacity-100"
          title={copied ? t("common.copied") : t("common.copy")}
        >
          {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
        </button>
      )}
    </article>
  )
}
