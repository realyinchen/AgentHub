import type {
  ChatHistory,
  ChatMessage,
  ConversationInDB,
  ModelInfo,
  ModelCapabilityStatus,
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

// ── User scoping helper ───────────────────────────────────────────────────────

let _currentUserId: string | null = null

export function setCurrentUserId(userId: string | null): void {
  _currentUserId = userId
}

export function getCurrentUserId(): string | null {
  return _currentUserId
}

function userIdQuery(): string {
  const id = _currentUserId
  if (!id) throw new Error("No user selected. Please select a user first.")
  return `user_id=${encodeURIComponent(id)}`
}

// ── Conversations ─────────────────────────────────────────────────────────────

export async function listConversations(
  limit = 10,
  offset = 0,
): Promise<{ conversations: ConversationInDB[]; total: number }> {
  const response = await fetch(
    `${apiBaseUrl}/chat/conversations?${userIdQuery()}&limit=${limit}&offset=${offset}`,
  )
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  const conversations = (await response.json()) as ConversationInDB[]
  // Get total from X-Total-Count header if available, otherwise estimate
  const totalHeader = response.headers.get("X-Total-Count")
  const total = totalHeader ? parseInt(totalHeader, 10) : conversations.length
  return { conversations, total }
}

export async function loadMoreConversations(
  offset: number,
  limit = 10,
): Promise<{ conversations: ConversationInDB[]; total: number }> {
  return listConversations(limit, offset)
}

export async function createConversation(input: {
  thread_id: string
  title: string
}): Promise<ConversationInDB> {
  return requestJson<ConversationInDB>(
    `/chat/conversations?${userIdQuery()}`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  )
}

export async function deleteConversation(
  threadId: string,
): Promise<void> {
  await fetch(
    `${apiBaseUrl}/chat/conversations/${encodeURIComponent(threadId)}?${userIdQuery()}`,
    { method: "DELETE" },
  )
}

// ── Conversation info (model fallback) ────────────────────────────────────────

export type ConversationInfoResponse = {
  model_name: string | null
  model_fallback: boolean
}

export async function getConversationInfo(
  threadId: string,
): Promise<ConversationInfoResponse> {
  return requestJson<ConversationInfoResponse>(
    `/chat/conversations/${encodeURIComponent(threadId)}/info?${userIdQuery()}`,
  )
}

// ── Title ─────────────────────────────────────────────────────────────────────

export async function getConversationTitle(
  threadId: string,
): Promise<ConversationInDB | null> {
  return requestJson<ConversationInDB | null>(
    `/chat/conversations/${encodeURIComponent(threadId)}/title?${userIdQuery()}`,
  )
}

export async function setConversationTitle(
  threadId: string,
  title: string,
): Promise<ConversationInDB | null> {
  return requestJson<ConversationInDB | null>(
    `/chat/conversations/${encodeURIComponent(threadId)}/title?${userIdQuery()}`,
    {
      method: "PATCH",
      body: JSON.stringify({ title }),
    },
  )
}

export async function generateTitle(input: {
  thread_id: string
  user_message: string
  ai_response?: string
}): Promise<{ title: string }> {
  return requestJson<{ title: string }>(
    `/chat/conversations/${encodeURIComponent(input.thread_id)}/title/generate`,
    {
      method: "POST",
      body: JSON.stringify({
        user_message: input.user_message,
        ai_response: input.ai_response,
      }),
    },
  )
}

// ── History ───────────────────────────────────────────────────────────────────

export async function getHistory(
  threadId: string,
): Promise<ChatHistory> {
  return requestJson<ChatHistory>(
    `/chat/history/${encodeURIComponent(threadId)}?${userIdQuery()}`,
  )
}

// ── Invoke / Stream ───────────────────────────────────────────────────────────

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

// ── Thinking mode ─────────────────────────────────────────────────────────────

export async function getThinkingModeStatus(): Promise<{ available: boolean }> {
  return requestJson<{ available: boolean }>("/models/thinking-mode")
}

// ── Model API ─────────────────────────────────────────────────────────────────

/**
 * Get available models (for frontend dropdown)
 * Only returns models with API key configured
 */
export async function getAvailableModels(): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>("/models")
}

/**
 * Get all models (for configuration page)
 */
export async function getAllModels(): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>("/models?include_inactive=true")
}

/**
 * Create a new model
 * Note: model_id should be the model name WITHOUT provider prefix.
 * If user provides "provider/model_name", it will be automatically normalized to "model_name".
 */
export async function createModel(data: ModelCreate): Promise<ModelInfo> {
  // Normalize model_id: strip provider prefix if present
  let normalizedModelId = data.model_id
  if (normalizedModelId.startsWith(`${data.provider}/`)) {
    normalizedModelId = normalizedModelId.slice(data.provider.length + 1)
  }

  return requestJson<ModelInfo>("/models", {
    method: "POST",
    body: JSON.stringify({
      ...data,
      model_id: normalizedModelId,
    }),
  })
}

/**
 * Update model configuration
 */
export async function updateModel(id: string, data: ModelUpdate): Promise<ModelInfo> {
  return requestJson<ModelInfo>(`/models/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  })
}

/**
 * Run a real model capability check.
 */
export async function validateModel(
  id: string,
  checkThinking = true,
): Promise<ModelCapabilityStatus> {
  return requestJson<ModelCapabilityStatus>(`/models/${id}/validate`, {
    method: "POST",
    body: JSON.stringify({ check_thinking: checkThinking }),
  })
}

/**
 * Get the latest model capability check.
 */
export async function getModelCapability(
  id: string,
): Promise<ModelCapabilityStatus | null> {
  return requestJson<ModelCapabilityStatus | null>(`/models/${id}/capabilities`)
}

/**
 * Delete a model
 */
export async function deleteModel(id: string): Promise<void> {
  await requestJson<void>(`/models/${id}`, {
    method: "DELETE",
  })
}

/**
 * Set default model
 */
export async function setDefaultModel(id: string): Promise<ModelInfo> {
  return requestJson<ModelInfo>(`/models/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_default: true }),
  })
}

/**
 * Set default thinking model
 * Note: Backend does not have a dedicated endpoint for this.
 * This sets the model as default and assumes the backend handles thinking mode appropriately.
 */
export async function setDefaultThinkingModel(modelId: string): Promise<ModelInfo> {
  // Backend doesn't have a separate thinking-model endpoint
  // We'll set it as default with thinking mode enabled
  return requestJson<ModelInfo>(`/models/${modelId}`, {
    method: "PATCH",
    body: JSON.stringify({ is_default: true, thinking: true }),
  })
}

/**
 * Get all providers with their configuration
 */
export async function getProviders(): Promise<ProvidersResponse> {
  return requestJson<ProvidersResponse>("/models/providers")
}

/**
 * Update provider configuration (API key and/or base URL)
 */
export async function updateProvider(data: ProviderUpdate): Promise<ProviderInfo> {
  return requestJson<ProviderInfo>(`/models/providers/${data.provider}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  })
}
