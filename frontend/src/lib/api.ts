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
  ProvidersResponse,
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
 * 获取可用模型列表（前端下拉框使用）
 * 只返回已配置 API Key 的模型
 */
export async function getAvailableModels(): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>("/models/")
}

/**
 * 获取所有模型（配置页面使用）
 */
export async function getAllModels(): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>("/models/all")
}

/**
 * 创建新模型
 */
export async function createModel(data: ModelCreate): Promise<ModelInfo> {
  return requestJson<ModelInfo>("/models/", {
    method: "POST",
    body: JSON.stringify(data),
  })
}

/**
 * 更新模型配置
 */
export async function updateModel(modelId: string, data: ModelUpdate): Promise<ModelInfo> {
  return requestJson<ModelInfo>("/models/update", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId, ...data }),
  })
}

/**
 * 删除模型
 */
export async function deleteModel(modelId: string): Promise<void> {
  await requestJson<void>("/models/delete", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId }),
  })
}

/**
 * 设置默认模型
 */
export async function setDefaultModel(modelId: string): Promise<ModelInfo> {
  return requestJson<ModelInfo>("/models/set-default", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId }),
  })
}

/**
 * 设置默认思考模型
 */
export async function setDefaultThinkingModel(modelId: string): Promise<ModelInfo> {
  return requestJson<ModelInfo>("/models/set-default-thinking", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId }),
  })
}

/**
 * 手动刷新模型缓存
 */
export async function refreshModelsCache(): Promise<{ success: boolean; message: string; models_count: number }> {
  return requestJson<{ success: boolean; message: string; models_count: number }>("/models/refresh", {
    method: "POST",
  })
}

/**
 * 获取可用的模型提供商列表
 */
export async function getProviders(): Promise<ProvidersResponse> {
  return requestJson<ProvidersResponse>("/models/providers")
}
