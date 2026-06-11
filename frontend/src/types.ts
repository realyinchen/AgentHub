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
  thinking_mode?: boolean
  timezone?: string
  custom_data?: Record<string, unknown> | null
}

// ==================== Model Types ====================

// ==================== Provider Types ====================

export type ProviderInfo = {
  provider: string  // e.g. "dashscope", "zai", "openai-compatible"
  has_api_key: boolean
  base_url: string | null
  is_openai_compatible: boolean
  created_at: string
  updated_at: string
}

export type ProvidersResponse = {
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

export type ModelInfo = {
  id: string  // UUID primary key
  provider: string  // e.g. "dashscope", "zai"
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
  provider: string  // e.g. "dashscope", "zai", "openai"
  model_type: ModelType
  model_id: string  // Model name WITHOUT provider prefix, e.g. "qwen3.5-27b" (NOT "dashscope/qwen3.5-27b")
  thinking?: boolean
  is_default?: boolean
  is_active?: boolean
}

export type ModelUpdate = {
  provider?: string
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

