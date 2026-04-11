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
  user_tokens: number
  ai_tokens: number
  reasoning_tokens: number
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
    type: "thinking"
    content: string
  }
  | {
    type: "message"
    content: ChatMessage
  }
  | {
    type: "error"
    content: string
  }
  | {
    type: "tool_call"
    content: ToolCallEvent
  }
  | {
    type: "tool_result"
    content: ToolResultEvent
  }