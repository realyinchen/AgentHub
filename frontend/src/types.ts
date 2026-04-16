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
 * - ai: AI response with content and optional thinking
 * - tool: Tool execution with name, args, and output (merged call + result)
 */
export type MessageStep = {
  step_number: number
  message_type: "ai" | "tool"
  content: string | null
  tool_name: string | null
  tool_args: Record<string, unknown> | null
  tool_output: string | null
  thinking: string | null
}

export type AgentInDB = {
  agent_id: string
  description: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ConversationInDB = {
  thread_id: string
  title: string
  agent_id?: string | null
  created_at: string
  updated_at: string
  is_deleted: boolean
}

export type UserInput = {
  content: string
  agent_id: string
  thread_id?: string | null
  model_name?: string | null
  thinking_mode?: boolean
  custom_data?: Record<string, unknown> | null
}

// ==================== Model Types ====================

export type ModelType = "llm" | "vlm" | "embedding"

export type ModelInfo = {
  provider: string  // e.g. "dashscope", "zai"
  model_type: ModelType
  model_id: string  // e.g. "dashscope/qwen3.5-27b"
  model_name: string  // e.g. "qwen3.5-27b"
  has_api_key: boolean
  thinking: boolean  // whether supports thinking mode
  is_default: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ModelCreate = {
  provider: string
  model_type: ModelType
  model_id: string
  model_name: string
  api_key?: string | null
  thinking?: boolean
  is_default?: boolean
  is_active?: boolean
}

export type ModelUpdate = {
  provider?: string
  model_type?: ModelType
  model_name?: string
  api_key?: string | null
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

export type ProvidersResponse = {
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
    type: "token"
    content: string
  }
  | {
    type: "llm"
    id: string
    step: number
    content: string
  }
  | {
    type: "tool"
    id: string
    step: number
    content: {
      name: string
      tool_id: string
      args?: Record<string, unknown>
      status: "calling"
    }
  }
  | {
    type: "tool_result"
    content: ToolResultEvent
  }
  | {
    type: "message"
    content: ChatMessage
  }
  | {
    type: "error"
    content: string
  }

// ==================== Agent Process Types ====================

/**
 * Single step in agent execution process.
 * Used to track thinking and tool calls during streaming.
 * 
 * Types:
 * - human: User message
 * - thinking: LLM reasoning/thinking content
 * - tool_call: Tool invocation with args and result
 * - ai_response: Final AI response with content and optional thinking
 */
export type AgentProcessStep = {
  id: string
  type: "human" | "thinking" | "tool_call" | "ai_response"
  content: string | ToolCallEvent
  timestamp: number
  status?: "running" | "done"
  // For tool_call steps, store the result when completed
  result?: string
  // For ai_response steps, store thinking content if available
  thinking?: string
}

/**
 * Agent execution session for real-time process display.
 * Active during streaming, cleared after streaming ends.
 */
export type AgentProcessSession = {
  threadId: string
  agentId: string
  steps: AgentProcessStep[]
  isActive: boolean
  startTime: number
  endTime?: number
}

/**
 * View mode for sidebar process panel.
 */
export type ProcessViewMode = "streaming" | "history"

/**
 * Single step in historical process data.
 * Used to preserve the order and type of each step.
 */
export type HistoricalProcessStep = {
  id: string
  type: "human" | "thinking" | "tool_call" | "ai_response"
  content: string  // Thinking content or tool name
  args?: Record<string, unknown>  // Tool arguments (for tool_call type)
  result?: string  // Tool result (for tool_call type)
  thinking?: string  // For ai_response steps
  order: number  // Step order index
}

/**
 * Data to display in sidebar when viewing historical process.
 * Supports both legacy format (single thinking + tool calls) and new format (ordered steps).
 */
export type HistoricalProcessData = {
  thinkingContent: string  // Legacy: combined thinking content
  toolCalls: ToolCallInfo[]  // Legacy: tool calls
  messageId: string
  steps?: HistoricalProcessStep[]  // New: ordered steps with type info
}
