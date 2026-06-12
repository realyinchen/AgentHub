import type {
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

// ── Auth helpers ───────────────────────────────────────────────────────────────

/** Check if current path is login page */
function isLoginPage(): boolean {
  return window.location.pathname === "/login"
}

/** Redirect to login page on 401 */
function handleUnauthorized(): void {
  if (!isLoginPage()) {
    window.location.href = "/login"
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    credentials: "include", // Include HTTP-only cookies
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  })

  if (response.status === 401) {
    handleUnauthorized()
    throw new Error("Unauthorized")
  }

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

// ── Deprecated: kept for backward compatibility ───────────────────────────────
// These functions are no longer used but exported to prevent breaking changes

/** @deprecated User ID is now managed server-side via JWT cookie */
export function setCurrentUserId(_userId: string | null): void {
  // No-op: user ID comes from JWT cookie
}

/** @deprecated User ID is now managed server-side via JWT cookie */
export function getCurrentUserId(): string | null {
  console.warn("getCurrentUserId() is deprecated. Use /auth/status instead.")
  return null
}

// ── Auth API ──────────────────────────────────────────────────────────────────

export interface AuthStatus {
  authenticated: boolean
  user: {
    id: string
    display_name: string
    is_mock_user: boolean
  } | null
}

export async function getAuthStatus(): Promise<AuthStatus> {
  return requestJson<AuthStatus>("/auth/status")
}

export interface MockUser {
  id: string
  display_name: string
  is_mock_user: boolean
}

export async function getMockUsers(): Promise<MockUser[]> {
  return requestJson<MockUser[]>("/auth/mock-users")
}

export async function mockLogin(userId: string): Promise<void> {
  await requestJson<void>("/auth/mock-login", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  })
}

export async function logout(): Promise<void> {
  await requestJson<void>("/auth/logout", {
    method: "POST",
  })
}

// ── Conversations ─────────────────────────────────────────────────────────────

export async function listConversations(
  limit = 10,
  offset = 0,
): Promise<{ conversations: ConversationInDB[]; total: number }> {
  const response = await fetch(
    `${apiBaseUrl}/chat/conversations?limit=${limit}&offset=${offset}`,
    { credentials: "include" },
  )
  if (response.status === 401) {
    handleUnauthorized()
    throw new Error("Unauthorized")
  }
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
  return requestJson<ConversationInDB>("/chat/conversations", {
    method: "POST",
    body: JSON.stringify(input),
  })
}

export async function deleteConversation(threadId: string): Promise<void> {
  const response = await fetch(
    `${apiBaseUrl}/chat/conversations/${encodeURIComponent(threadId)}`,
    {
      method: "DELETE",
      credentials: "include",
    },
  )
  if (response.status === 401) {
    handleUnauthorized()
    throw new Error("Unauthorized")
  }
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
    `/chat/conversations/${encodeURIComponent(threadId)}/info`,
  )
}

// ── Title ─────────────────────────────────────────────────────────────────────

export async function getConversationTitle(
  threadId: string,
): Promise<ConversationInDB | null> {
  return requestJson<ConversationInDB | null>(
    `/chat/conversations/${encodeURIComponent(threadId)}/title`,
  )
}

export async function setConversationTitle(
  threadId: string,
  title: string,
): Promise<ConversationInDB | null> {
  return requestJson<ConversationInDB | null>(
    `/chat/conversations/${encodeURIComponent(threadId)}/title`,
    {
      method: "PATCH",
      body: JSON.stringify({ title }),
    },
  )
}

/**
 * Generate and save conversation title using LLM.
 * The generated title is automatically saved to the database.
 * Returns the updated conversation object.
 */
export async function generateTitle(input: {
  thread_id: string
  user_message: string
  ai_response?: string
}): Promise<ConversationInDB> {
  return requestJson<ConversationInDB>(
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

export async function getHistory(threadId: string): Promise<ChatHistory> {
  return requestJson<ChatHistory>(
    `/chat/history/${encodeURIComponent(threadId)}`,
  )
}

// ── Invoke / Stream ───────────────────────────────────────────────────────────

export async function invoke(
  threadId: string,
  input: UserInput,
): Promise<ChatMessage> {
  const requestId = crypto.randomUUID()
  return requestJson<ChatMessage>(
    `/chat/${encodeURIComponent(threadId)}/invoke`,
    {
      method: "POST",
      body: JSON.stringify(input),
      headers: {
        "X-Request-ID": requestId,
      },
    },
  )
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
  threadId: string,
  input: UserInput,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const requestId = crypto.randomUUID()
  const response = await fetch(
    `${apiBaseUrl}/chat/${encodeURIComponent(threadId)}/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
      body: JSON.stringify(input),
      signal,
      credentials: "include", // Include HTTP-only cookies
    },
  )

  if (response.status === 401) {
    handleUnauthorized()
    throw new Error("Unauthorized")
  }

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
