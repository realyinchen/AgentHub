import type {
  AgentInDB,
  ChatHistory,
  ChatMessage,
  ConversationInDB,
  ModelInfo,
  ModelsResponse,
  ModelCreate,
  ModelUpdate,
  StreamEvent,
  UserInput,
  ProviderInfo,
  ProvidersResponse,
  ProviderUpdate,
} from "@/types"

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || "/api/v1"
const apiBaseUrl = rawBaseUrl.replace(/\/$/, "")

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    let details = ""
    try {
      const payload = (await response.json()) as { detail?: string }
      details = payload.detail ? `: ${payload.detail}` : ""
    } catch {
      details = ""
    }
    throw new Error(`HTTP ${response.status}${details}`)
  }

  return (await response.json()) as T
}

export async function listAgents(): Promise<AgentInDB[]> {
  return requestJson<AgentInDB[]>("/agents/?active_only=true&limit=100&offset=0")
}

export async function listConversations(limit = 100): Promise<ConversationInDB[]> {
  return requestJson<ConversationInDB[]>(
    `/chat/conversations?limit=${limit}&offset=0`,
  )
}

export async function createConversation(input: {
  thread_id: string
  title: string
  agent_id?: string
}): Promise<ConversationInDB> {
  return requestJson<ConversationInDB>("/chat/conversations", {
    method: "POST",
    body: JSON.stringify(input),
  })
}

export async function getConversationTitle(
  threadId: string,
): Promise<ConversationInDB | null> {
  return requestJson<ConversationInDB | null>(`/chat/title/${threadId}`)
}

export async function setConversationTitle(input: {
  thread_id: string
  title: string
  is_deleted?: boolean
}): Promise<ConversationInDB | null> {
  return requestJson<ConversationInDB | null>("/chat/title", {
    method: "POST",
    body: JSON.stringify(input),
  })
}

/**
 * Generate a conversation title using the default LLM.
 * This is a lightweight endpoint that doesn't go through the agent flow.
 */
export async function generateTitle(input: {
  user_message: string
  ai_response?: string
}): Promise<{ title: string }> {
  return requestJson<{ title: string }>("/chat/title/generate", {
    method: "POST",
    body: JSON.stringify(input),
  })
}

export async function getHistory(
  agentId: string,
  threadId: string,
): Promise<ChatHistory> {
  return requestJson<ChatHistory>(`/chat/history/${agentId}/${threadId}`)
}

export async function invoke(input: UserInput): Promise<ChatMessage> {
  return requestJson<ChatMessage>("/chat/invoke", {
    method: "POST",
    body: JSON.stringify(input),
  })
}

function parseStreamChunk(
  chunk: string,
  onEvent: (event: StreamEvent) => void,
): boolean {
  const lines = chunk.split("\n")
  for (const line of lines) {
    if (!line.startsWith("data: ")) {
      continue
    }

    const raw = line.slice(6).trim()
    if (!raw) {
      continue
    }

    if (raw === "[DONE]") {
      return true
    }

    const parsed = JSON.parse(raw) as StreamEvent
    onEvent(parsed)
  }
  return false
}

export async function streamChat(
  input: UserInput,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
    signal,
  })

  if (!response.ok) {
    let details = ""
    try {
      const payload = (await response.json()) as { detail?: string }
      details = payload.detail ? `: ${payload.detail}` : ""
    } catch {
      details = ""
    }
    throw new Error(`HTTP ${response.status}${details}`)
  }

  if (!response.body) {
    throw new Error("Stream response body is empty")
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()

  let buffer = ""
  while (true) {
    const { value, done } = await reader.read()
    if (done) {
      if (buffer.trim()) {
        parseStreamChunk(buffer, onEvent)
      }
      break
    }

    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n")

    let separatorIndex = buffer.indexOf("\n\n")
    while (separatorIndex >= 0) {
      const chunk = buffer.slice(0, separatorIndex)
      buffer = buffer.slice(separatorIndex + 2)
      const isDone = parseStreamChunk(chunk, onEvent)
      if (isDone) {
        return
      }
      separatorIndex = buffer.indexOf("\n\n")
    }
  }
}

export async function getThinkingModeStatus(): Promise<{ available: boolean }> {
  return requestJson<{ available: boolean }>("/chat/thinking-mode")
}

// ==================== Model API ====================

/**
 * Get available models (for frontend dropdown)
 * Only returns models with API key configured
 */
export async function getAvailableModels(): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>("/models/")
}

/**
 * Get all models (for configuration page)
 */
export async function getAllModels(): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>("/models/all")
}

/**
 * Create a new model
 */
export async function createModel(data: ModelCreate): Promise<ModelInfo> {
  return requestJson<ModelInfo>("/models/", {
    method: "POST",
    body: JSON.stringify(data),
  })
}

/**
 * Update model configuration
 */
export async function updateModel(id: string, data: ModelUpdate): Promise<ModelInfo> {
  return requestJson<ModelInfo>("/models/update", {
    method: "POST",
    body: JSON.stringify({ id, ...data }),
  })
}

/**
 * Delete a model
 */
export async function deleteModel(id: string): Promise<void> {
  await requestJson<void>("/models/delete", {
    method: "POST",
    body: JSON.stringify({ id }),
  })
}

/**
 * Set default model
 */
export async function setDefaultModel(id: string): Promise<ModelInfo> {
  return requestJson<ModelInfo>("/models/set-default", {
    method: "POST",
    body: JSON.stringify({ id }),
  })
}

/**
 * Set default thinking model
 */
export async function setDefaultThinkingModel(modelId: string): Promise<ModelInfo> {
  return requestJson<ModelInfo>("/models/set-default-thinking", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId }),
  })
}

/**
 * Manually refresh model cache
 */
export async function refreshModelsCache(): Promise<{ success: boolean; message: string; models_count: number }> {
  return requestJson<{ success: boolean; message: string; models_count: number }>("/models/refresh", {
    method: "POST",
  })
}

/**
 * Get all providers with their configuration
 */
export async function getProviders(): Promise<ProvidersResponse> {
  return requestJson<ProvidersResponse>("/providers/")
}

/**
 * Update provider configuration (API key and/or base URL)
 */
export async function updateProvider(data: ProviderUpdate): Promise<ProviderInfo> {
  return requestJson<ProviderInfo>("/providers/update", {
    method: "POST",
    body: JSON.stringify(data),
  })
}
