export type MessageType = "human" | "ai" | "tool" | "custom"

export type ToolCall = {
  id: string
  name: string
  args: Record<string, unknown>
  type?: string
}

export type ChatMessage = {
  type: MessageType
  content: string
  tool_calls: ToolCall[]
  tool_call_id: string | null
  run_id: string | null
  request_id?: string | null  // Request ID for viewing DAG of this specific turn
  response_metadata: Record<string, unknown>
  custom_data: Record<string, unknown>
  reasoning_content?: string | null  // Reasoning/thinking content (for reasoning models)
}

export type LocalChatMessage = ChatMessage & {
  local_id: string
  is_streaming?: boolean
}

export type ChatHistory = {
  messages: ChatMessage[]
  message_sequence: MessageStep[]
}

// ==================== Message Step Types ====================

/**
 * Single step in the agent execution sequence.
 * Each message from the conversation is represented as a step.
 * 
 * Types:
 * - human: User input message
 * - ai: AI response with content and optional thinking
 * - tool: Tool execution with name, args, and output (merged call + result)
 */
export type MessageStep = {
  session_id: string  // UUID that groups steps from the same conversation turn
  step_number: number
  message_type: "human" | "ai" | "tool"
  content: string | null
  tool_name: string | null
  tool_args: Record<string, unknown> | null
  tool_output: string | null
  tool_call_id: string | null  // Tool call ID for matching
  thinking: string | null
  tool_calls: ToolCall[] | null  // Tool calls from AI message
  model_name: string | null  // Model name for AI messages
}

export type UserInfo = {
  id: string
  name: string
  gender: "male" | "female"
  avatar?: string  // Optional avatar (emoji or URL)
}

export type ConversationInDB = {
  thread_id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
  is_deleted: boolean
  // Token usage statistics (cumulative for all messages in conversation)
  input_tokens: number
  cache_read: number
  output_tokens: number
  reasoning: number
  total_tokens: number
}

export type UserInput = {
  content: string
  user_id: string
  thread_id: string
  request_id: string
  model_name?: string | null
  model_uuid?: string | null
  thinking_mode?: boolean
  timezone?: string
  custom_data?: Record<string, unknown> | null
}

// ==================== Memory Types ====================

export type MemoryEvent = {
  id: string | null
  type: string
  subject: string
  value: string
  polarity: string
  confidence: number
  user_id: string
  thread_id: string | null
  source: string
  metadata: Record<string, unknown>
  state_category: "profile" | "preference" | "relation" | "feedback" | "short_term" | null
  state_key: string
  state_status: "pending" | "active" | "needs_confirmation" | "superseded" | "expired" | "forgotten"
  raw_text: string
  state_value: Record<string, unknown>
  relation: Record<string, unknown>
  use_when: string[]
  valid_until: string | null
  confirmation_question: string
  revision_of: string | null
  superseded_by: string | null
  forgotten: boolean
  created_at: string | null
  updated_at: string | null
}

export type UserStateConfirmRequest = {
  user_id: string
  accept: boolean
  category?: MemoryEvent["state_category"]
  state_key?: string
  summary?: string
  state_value?: Record<string, unknown>
  relation?: Record<string, unknown>
  use_when?: string[]
}

export type CurrentMemoryListResult = {
  user_id: string
  memories: MemoryEvent[]
  total: number
  limit: number
  offset: number
  provider_sources: string[]
}

export type MemoryForgetRequest = {
  user_id: string
  memory_id?: string | null
  subject?: string
  value?: string
  memory_type?: string
  thread_id?: string | null
  reason?: string
}

export type MemoryForgetResult = {
  user_id: string
  forgotten_count: number
  forgotten_event_ids: string[]
  provider_sources: string[]
}

// ==================== Recommendation Signal Types ====================

export type RecommendationEventType =
  | "candidate_retrieved"
  | "recommended"
  | "followup_suggested"
  | "followup_clicked"
  | "followup_matched"
  | "detail_requested"
  | "want_to_read"
  | "read"
  | "liked"
  | "disliked"
  | "not_interested"
  | "suppressed"

export type RecommendationSignalPolarity = "positive" | "negative" | "neutral"
export type RecommendationSignalSource =
  | "agent_tool"
  | "book_feedback"
  | "followup_question"
  | "api"
  | "system"

export type RecommendationSignal = {
  id: string
  user_id: string
  event_type: RecommendationEventType
  signal_polarity: RecommendationSignalPolarity
  signal_strength: number
  book_id: string | null
  book_title: string
  thread_id: string | null
  request_id: string
  message_id: string
  source: RecommendationSignalSource
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type RecommendationSignalCreate = {
  user_id: string
  event_type: RecommendationEventType
  signal_polarity?: RecommendationSignalPolarity
  signal_strength?: number
  book_id?: string | null
  book_title?: string
  thread_id?: string | null
  request_id?: string
  message_id?: string
  source?: RecommendationSignalSource
  metadata?: Record<string, unknown>
}

export type RecommendationHistoryMode =
  | "all"
  | "reading_history"
  | "rejection_history"
  | "suppression_explanation"

export type RecommendationHistoryStatus = "ok" | "empty_result" | "tool_blocked"

export type RecommendationHistoryRecord = {
  record_type: string
  event_type: RecommendationEventType | "suppressed"
  book_id: string | null
  book_title: string
  reason: string
  suppression_reasons: string[]
  signal_polarity: RecommendationSignalPolarity
  signal_strength: number
  source: RecommendationSignalSource | string
  thread_id: string | null
  request_id: string
  message_id: string
  metadata: Record<string, unknown>
  created_at: string | null
}

export type RecommendationHistoryResult = {
  status: RecommendationHistoryStatus
  result_mode: "recommendation_history"
  history_mode: RecommendationHistoryMode
  user_id: string
  query: string
  book_title: string
  records: RecommendationHistoryRecord[]
  suppressed_records: RecommendationHistoryRecord[]
  result_count: number
  next_action_hint: string
  metadata: Record<string, unknown>
}

// ==================== Research Types ====================

export type ResearchRunStatus = "active" | "completed" | "cancelled" | "failed"
export type ResearchMode = "deep_search" | "deep_research"
export type ResearchStepType =
  | "plan"
  | "search"
  | "visit"
  | "add_evidence"
  | "update_state"
  | "finish"
export type ResearchStepStatus =
  | "planned"
  | "running"
  | "completed"
  | "empty_result"
  | "timeout"
  | "failed"
  | "skipped"
export type ResearchEvidenceQuality = "high" | "medium" | "low" | "unknown"

export type ResearchRun = {
  id: string | null
  user_id: string
  thread_id: string | null
  objective: string
  status: ResearchRunStatus
  mode: ResearchMode
  budget: Record<string, unknown>
  stop_criteria: string[]
  metadata: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  created_at: string | null
  updated_at: string | null
}

export type ResearchStep = {
  id: string | null
  run_id: string
  step_type: ResearchStepType
  status: ResearchStepStatus
  title: string
  query: string
  url: string
  rationale: string
  input: Record<string, unknown>
  output: Record<string, unknown>
  error: string | null
  duration_ms: number
  created_at: string | null
  updated_at: string | null
}

export type ResearchEvidence = {
  id: string | null
  run_id: string
  step_id: string | null
  source_type: string
  source_title: string
  source_url: string
  claim: string
  excerpt: string
  quality: ResearchEvidenceQuality
  relevance: number
  metadata: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export type ResearchStateSnapshot = {
  id: string | null
  run_id: string
  step_id: string | null
  objective: string
  status: ResearchRunStatus
  subquestions: string[]
  known_facts: string[]
  gaps: string[]
  conflicts: string[]
  exhausted_queries: string[]
  next_actions: string[]
  evidence_ids: string[]
  budget: Record<string, unknown>
  stop_criteria: string[]
  metadata: Record<string, unknown>
  created_at: string | null
}

export type ResearchStateResult = {
  run: ResearchRun
  state: ResearchStateSnapshot
  steps: ResearchStep[]
  evidence: ResearchEvidence[]
  provider_sources: string[]
}

export type ResearchRunListResult = {
  user_id: string
  runs: ResearchRun[]
  total: number
  limit: number
  offset: number
  provider_sources: string[]
}

export type ResearchFinishRequest = {
  user_id: string
  run_id: string
  conclusion: string
  status?: ResearchRunStatus
  known_facts?: string[]
  gaps?: string[]
  conflicts?: string[]
  metadata?: Record<string, unknown>
}

export type ResearchClaimAdmissionStatus = "admitted" | "rejected" | "uncertain"

export type ResearchEvidenceReference = {
  id: string
  source_type: string
  source_title: string
  source_url: string
  quality: ResearchEvidenceQuality
  relevance: number
}

export type ResearchClaimAdmissionDecision = {
  claim: string
  status: ResearchClaimAdmissionStatus
  evidence_ids: string[]
  evidence: ResearchEvidenceReference[]
  quality: ResearchEvidenceQuality
  reason_codes: string[]
  explanation: string
  metadata: Record<string, unknown>
}

export type ResearchVerifierAdmissionResult = {
  run_id: string
  decisions: ResearchClaimAdmissionDecision[]
  admitted_claims: ResearchClaimAdmissionDecision[]
  rejected_claims: ResearchClaimAdmissionDecision[]
  uncertain_claims: ResearchClaimAdmissionDecision[]
  blocking_gaps: string[]
  conflicts: string[]
  ready_for_final_answer: boolean
  can_finalize_with_uncertainty: boolean
  metadata: Record<string, unknown>
}

export type ResearchReportSource = {
  evidence_id: string
  source_type: string
  source_title: string
  source_url: string
  quality: ResearchEvidenceQuality
  relevance: number
  claim: string
}

export type ResearchReportMemoryContext = {
  memory_ids: string[]
  constraints: string[]
}

export type ResearchReportResult = {
  result_mode: "research_report"
  contract_version: "research-report-v1"
  run_id: string
  user_id: string
  objective: string
  run_status: ResearchRunStatus | string
  report_status: string
  final_answer: string
  verified_claims: ResearchClaimAdmissionDecision[]
  uncertain_claims: ResearchClaimAdmissionDecision[]
  rejected_claims: ResearchClaimAdmissionDecision[]
  sources: ResearchReportSource[]
  gaps: string[]
  conflicts: string[]
  exhausted_queries: string[]
  next_actions: string[]
  memory_context: ResearchReportMemoryContext
  verification: ResearchVerifierAdmissionResult
  metadata: Record<string, unknown>
}

export type ResearchRuntimeResult = {
  result_mode: "research_runtime"
  contract_version: "research-runtime-v1"
  user_id: string
  run_id: string
  status: string
  harness: Record<string, unknown>
  report: ResearchReportResult
  metadata: Record<string, unknown>
}

export type ResearchFinalAnswerResult = {
  result_mode: "research_final_answer"
  contract_version: "research-final-answer-v1"
  user_id: string
  run_id: string
  objective: string
  report_status: string
  answer_status: string
  answer: string
  verified_claims: ResearchClaimAdmissionDecision[]
  omitted_uncertain_claims: ResearchClaimAdmissionDecision[]
  omitted_rejected_claims: ResearchClaimAdmissionDecision[]
  limitations: string[]
  sources: ResearchReportSource[]
  ready_for_final_answer: boolean
  can_finalize_with_uncertainty: boolean
  metadata: Record<string, unknown>
}

export type ResearchSourceRecord = {
  source_type: string
  source_title: string
  source_url: string
  claim: string
  excerpt: string
  quality: ResearchEvidenceQuality | string
  relevance: number
  metadata: Record<string, unknown>
}

export type ResearchSourceDocument = {
  source_type: string
  source_title: string
  source_url: string
  content: string
  quality: ResearchEvidenceQuality | string
  relevance: number
  metadata: Record<string, unknown>
}

export type RejectedResearchSource = {
  source_type: string
  source_title: string
  source_url: string
  reason_codes: string[]
  metadata: Record<string, unknown>
}

export type ResearchObservation = {
  source_type: string
  source_title: string
  source_url: string
  claim: string
  excerpt: string
  quality: ResearchEvidenceQuality | string
  relevance: number
  metadata: Record<string, unknown>
}

export type ResearchObservationBatchResult = {
  result_mode: "research_observation_batch"
  contract_version: "research-observation-batch-v1"
  status: string
  query: string
  subquestion: string
  observations: ResearchObservation[]
  rejected_sources: RejectedResearchSource[]
  source_count: number
  observation_count: number
  metadata: Record<string, unknown>
}

export type ResearchSourceExtractionResult = {
  result_mode: "research_source_extraction"
  contract_version: "research-source-extraction-v1"
  status: string
  query: string
  subquestion: string
  source_records: ResearchSourceRecord[]
  observation_batch: ResearchObservationBatchResult | null
  rejected_documents: RejectedResearchSource[]
  document_count: number
  extracted_count: number
  metadata: Record<string, unknown>
}

export type ResearchSourceCollectionResult = {
  result_mode: "research_source_collection"
  contract_version: "research-source-collection-v1"
  user_id: string
  run_id: string
  query: string
  status: string
  observation_batch: ResearchObservationBatchResult | null
  research_state: ResearchStateResult | null
  metadata: Record<string, unknown>
}

export type ResearchEvidenceAdmissionResult = {
  result_mode: "research_evidence_admission"
  contract_version: "research-evidence-admission-v1"
  status: string
  allowed: boolean
  reason_codes: string[]
  warning_codes: string[]
  evidence: ResearchEvidence
  metadata: Record<string, unknown>
}

export type ResearchPythonAnalysisResult = {
  result_mode: "research_python_analysis"
  contract_version: "research-python-analysis-v1"
  status: string
  query: string
  subquestion: string
  analysis_type: string
  source_title: string
  source_url: string
  record_count: number
  analyzed_record_count: number
  rejected_record_count: number
  findings: ResearchSourceRecord[]
  observation_batch: ResearchObservationBatchResult | null
  finding_count: number
  error: string | null
  metadata: Record<string, unknown>
}

export type ResearchSourceSearchResult = {
  result_mode: "research_source_search"
  contract_version: "research-source-search-v1"
  status: string
  query: string
  subquestion: string
  provider_name: string
  provider_query: string
  source_documents: ResearchSourceDocument[]
  extraction: ResearchSourceExtractionResult | null
  document_count: number
  extracted_count: number
  error: string | null
  duration_ms: number
  metadata: Record<string, unknown>
}

export type ResearchScholarSearchResult = {
  result_mode: "research_scholar_search"
  contract_version: "research-scholar-search-v1"
  status: string
  query: string
  subquestion: string
  provider_name: string
  provider_query: string
  source_documents: ResearchSourceDocument[]
  extraction: ResearchSourceExtractionResult | null
  document_count: number
  extracted_count: number
  error: string | null
  duration_ms: number
  metadata: Record<string, unknown>
}

export type ResearchSourceVisitResult = {
  result_mode: "research_source_visit"
  contract_version: "research-source-visit-v1"
  status: string
  url: string
  final_url: string
  query: string
  subquestion: string
  source_document: ResearchSourceDocument | null
  extraction: ResearchSourceExtractionResult | null
  extracted_count: number
  error: string | null
  duration_ms: number
  metadata: Record<string, unknown>
}

export type RecommendationResearchClaimLink = {
  claim: string
  source_title: string
  source_url: string
  source_type: string
  quality: ResearchEvidenceQuality | string
  relevance: number
  evidence_ids: string[]
  reason: string
  metadata: Record<string, unknown>
}

export type RecommendationResearchCandidate = {
  rank: number
  book_id: string
  title: string
  authors: string[]
  summary: string
  rating: number | null
  source_name: string
  source_url: string
  recommendation_score: number | null
  candidate_source: Record<string, unknown>
  recommendation_explanation: Record<string, unknown>
  personalization_reasons: string[]
  research_support: RecommendationResearchClaimLink[]
  limitations: string[]
  supported_by_verified_research: boolean
  suppressed: boolean
  suppression_reasons: string[]
  fit_summary: string
  metadata: Record<string, unknown>
}

export type RecommendationResearchReportResult = {
  result_mode: "recommendation_research_report"
  contract_version: "recommendation-research-report-v1"
  status: string
  query: string
  research_run_id: string
  research_report_status: string
  research_report_contract_version: string
  candidates: RecommendationResearchCandidate[]
  recommended_candidates: RecommendationResearchCandidate[]
  suppressed_candidates: RecommendationResearchCandidate[]
  unsupported_candidates: RecommendationResearchCandidate[]
  candidate_count: number
  supported_count: number
  suppressed_count: number
  verified_claim_count: number
  limitations: string[]
  metadata: Record<string, unknown>
}

export type PersonalizedRecommendationConstraints = {
  user_id: string
  original_query: string
  effective_query: string
  preferred_terms: string[]
  avoided_terms: string[]
  favorite_authors: string[]
  disliked_authors: string[]
  source_memory_ids: string[]
  search_terms_added: string[]
  applied_to_search: boolean
  metadata: Record<string, unknown>
}

export type RecommendationResearchWorkflowStep = {
  name: string
  status: string
  reason: string
  required_inputs: string[]
}

export type RecommendationResearchWorkflowResult = {
  result_mode: "recommendation_research_workflow"
  contract_version: "recommendation-research-workflow-v1"
  status: string
  query: string
  ready_to_fuse: boolean
  candidate_count: number
  fresh_candidate_count: number
  suppressed_candidate_count: number
  research_run_id: string
  research_report_status: string
  research_report_contract_version: string
  verified_claim_count: number
  missing_inputs: string[]
  recommended_next_tools: string[]
  next_action_hint: string
  workflow_steps: RecommendationResearchWorkflowStep[]
  personalization_constraints: PersonalizedRecommendationConstraints | null
  metadata: Record<string, unknown>
}

export type RecommendationResearchRunnerResult = {
  result_mode: "recommendation_research_runner"
  contract_version: "recommendation-research-runner-v1"
  status: string
  query: string
  workflow_before: RecommendationResearchWorkflowResult
  workflow_after: RecommendationResearchWorkflowResult
  runtime: ResearchRuntimeResult | null
  research_report: ResearchReportResult | null
  recommendation_report: RecommendationResearchReportResult | null
  metadata: Record<string, unknown>
}

export type BookTurnRoute =
  | "answer_question"
  | "memory_update"
  | "memory_management"
  | "recommendation_history"
  | "ordinary_recommendation"
  | "researched_recommendation"
  | "deep_research"
  | "research_report"

export type BookTurnIntent = {
  primary_intent: string
  intents: string[]
  confidence: number
  explicit: boolean
  source: string
  signals: string[]
  metadata: Record<string, unknown>
}

export type BookTurnPolicy = {
  intent: BookTurnIntent
  can_answer_question: boolean
  can_write_memory: boolean
  can_manage_memory: boolean
  can_search_memory: boolean
  can_search_books: boolean
  can_recommend_books: boolean
  can_view_recommendation_history: boolean
  can_record_recommendation_signal: boolean
  can_start_research: boolean
  can_use_research_tools: boolean
  can_use_web_search: boolean
  max_book_search_calls: number
  requires_verifier: boolean
  allowed_tools: string[]
  denied_tools: string[]
  response_boundary: string
  metadata: Record<string, unknown>
}

export type BookTurnOrchestrationStep = {
  name: string
  status: string
  reason: string
  required_inputs: string[]
}

export type BookTurnOrchestrationResult = {
  result_mode: "book_turn_orchestration"
  contract_version: "book-turn-orchestration-v1"
  route: BookTurnRoute | string
  query: string
  user_message: string
  history_mode: string
  policy: BookTurnPolicy
  recommended_next_tools: string[]
  denied_tools: string[]
  response_boundary: string
  route_steps: BookTurnOrchestrationStep[]
  personalization_constraints: PersonalizedRecommendationConstraints | null
  recommendation_research_workflow: RecommendationResearchWorkflowResult | null
  metadata: Record<string, unknown>
}

// ==================== App Provider Config Types ====================

export type AppProviderType = "memory" | "research_observation" | "web_search"
export type AppProviderScope = "global" | "workspace" | "user"
export type AppProviderCapability =
  | "memory_recall"
  | "research_observation"
  | "web_search"
  | "source_visit"
  | "semantic_search"
export type AppProviderCredentialStatus = "none" | "configured" | "missing"
export type AppProviderHealthStatus =
  | "unknown"
  | "disabled"
  | "ok"
  | "missing_credentials"
  | "timeout"
  | "failed"

export type AppProviderHealth = {
  status: AppProviderHealthStatus
  error_type: string
  error: string
  duration_ms: number
  checked_at: string | null
  metadata: Record<string, unknown>
}

export type AppProviderConfig = {
  provider_key: string
  provider_type: AppProviderType
  scope: AppProviderScope
  enabled: boolean
  display_name: string
  capabilities: AppProviderCapability[]
  settings: Record<string, unknown>
  credentials_ref: string
  credential_status: AppProviderCredentialStatus
  health: AppProviderHealth
  metadata: Record<string, unknown>
}

export type AppProviderConfigList = {
  contract_version: string
  providers: AppProviderConfig[]
}

export type AppProviderConfigUpdate = {
  enabled?: boolean | null
  scope?: AppProviderScope | null
  display_name?: string | null
  capabilities?: AppProviderCapability[] | null
  settings?: Record<string, unknown> | null
  credentials_ref?: string | null
  api_key?: string | null
  clear_credentials?: boolean
  metadata?: Record<string, unknown> | null
}

// ==================== Model Types ====================

// ==================== Provider Types ====================

export type ProviderInfo = {
  provider: string  // e.g. "dashscope", "zai", "openai-compatible"
  provider_key?: string | null
  display_name?: string | null
  adapter_type?: string | null
  supports_connections?: boolean
  enabled?: boolean
  legacy?: boolean
  connection_count?: number
  model_count?: number
  has_api_key: boolean
  base_url: string | null
  is_openai_compatible: boolean
  created_at: string
  updated_at: string
}

export type ProvidersResponse = {
  contract_version?: string
  providers: ProviderInfo[]
}

export type ProviderUpdate = {
  provider: string
  api_key?: string | null
  base_url?: string | null
}

// ==================== Model Types ====================

export type ModelType = "llm" | "vlm" | "embedding"

export type ModelCapabilityStatus = {
  id: string
  model_id: string
  provider: string
  provider_model_id: string
  checked_at: string
  chat_ok: boolean
  thinking_request_ok: boolean | null
  reasoning_text_ok: boolean | null
  streaming_reasoning_ok: boolean | null
  reasoning_field_path: string | null
  latency_ms: number | null
  error_type: string | null
  last_error: string | null
  raw_summary: Record<string, unknown>
}

export type ProviderConnectionInfo = {
  connection_id: string
  provider_key: string
  name: string
  preset_type: string
  base_url: string | null
  has_api_key: boolean
  enabled: boolean
  model_count: number
  extra_headers_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type ProviderConnectionsResponse = {
  connections: ProviderConnectionInfo[]
}

export type ProviderConnectionCreate = {
  provider_key: string
  name: string
  preset_type: string
  api_key?: string | null
  base_url?: string | null
  enabled?: boolean
  extra_headers_json?: Record<string, unknown> | null
}

export type ProviderConnectionUpdate = {
  name?: string
  preset_type?: string
  api_key?: string | null
  clear_api_key?: boolean
  base_url?: string | null
  enabled?: boolean
  extra_headers_json?: Record<string, unknown> | null
}

export type ModelInfo = {
  id: string  // UUID primary key
  provider: string  // e.g. "dashscope", "zai"
  connection_id?: string | null
  model_uuid?: string | null
  provider_key?: string | null
  connection_name?: string | null
  provider_model_id?: string | null
  display_name?: string | null
  thinking_requested?: boolean | null
  model_type: ModelType
  model_id: string  // e.g. "dashscope/qwen3.5-27b"
  thinking: boolean  // whether supports thinking mode
  is_default: boolean
  is_active: boolean
  created_at: string
  updated_at: string
  capability?: ModelCapabilityStatus | null
}

export type ModelCreate = {
  provider?: string  // legacy fallback provider
  connection_id?: string | null
  model_type: ModelType
  model_id: string  // Model name WITHOUT provider prefix, e.g. "qwen3.5-27b" (NOT "dashscope/qwen3.5-27b")
  thinking?: boolean
  is_default?: boolean
  is_active?: boolean
}

export type ModelUpdate = {
  provider?: string
  connection_id?: string | null
  model_type?: ModelType
  model_id?: string  // Allow updating model_id (will create new record, delete old one)
  thinking?: boolean
  is_default?: boolean
  is_active?: boolean
}

export type ModelsResponse = {
  models: ModelInfo[]
  default_llm: string | null
  default_vlm: string | null
  default_embedding: string | null
}

// Legacy providers response (list of strings)
export type ProviderListResponse = {
  providers: string[]
}

// ==================== Tool Types ====================

export type ToolCallEvent = {
  name: string
  id: string
  args?: Record<string, unknown>
}

export type ToolResultEvent = {
  name: string
  id: string
  output: string
}

export type ToolCallInfo = {
  name: string
  id: string
  args: Record<string, unknown>
  output?: string
  status: "calling" | "completed"
}

/**
 * Tool info stored in message custom_data for history persistence.
 * This is the format returned by the backend history API.
 */
export type StoredToolCallInfo = {
  name: string
  id: string
  args: Record<string, unknown>
  output?: string | null
  order: number  // Call order index
}

export type StreamEvent =
  | {
    type: "request_start"
    request_id: string
  }
  | {
    type: "token"
    content: string
  }
  | {
    type: "llm"
    content: string
    id: string
  }
  | {
    type: "reasoning"
    content: string
  }
  | {
    type: "message"
    content: ChatMessage
  }
  | {
    type: "tool"
    content: {
      name: string
      tool_id: string
      args: Record<string, unknown>
    }
    id: string
  }
  | {
    type: "tool_result"
    content: {
      name: string
      id: string
      output: string
    }
  }
  | {
    type: "usage"
    content: {
      node: string
      usage: {
        input_tokens?: number
        output_tokens?: number
        total_tokens?: number
        [key: string]: unknown
      }
    }
  }
  | {
    type: "error"
    content: string
    error_type?: string
  }

