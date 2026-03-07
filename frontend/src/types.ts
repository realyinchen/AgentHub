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
  created_at: string
  updated_at: string
  is_deleted: boolean
}

export type UserInput = {
  content: string
  agent_id: string
  thread_id?: string | null
}

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

export type StreamEvent =
  | {
      type: "token"
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
