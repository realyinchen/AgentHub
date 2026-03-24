import type {
  AgentInDB,
  ChatHistory,
  ChatMessage,
  ConversationInDB,
  StreamEvent,
  UserInput,
} from "@/types"
import type {
  MessageNode,
  MessageTree,
  MessageNodeCreate,
  MessageNodeUpdate,
  // CurrentLeafUpdate, // Used in types but not directly in this file
} from "@/types/message-tree"

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

// ============ Message Node Tree API ============

/**
 * Get the complete message tree for a conversation.
 * @param threadId Thread ID
 * @param leafId Optional leaf ID for share links (locks the view to a specific branch)
 */
export async function getMessageTree(
  threadId: string,
  leafId?: string,
): Promise<MessageTree> {
  const params = leafId ? `?leaf_id=${leafId}` : ""
  return requestJson<MessageTree>(`/chat/tree/${threadId}${params}`)
}

/**
 * Create a new message node.
 */
export async function createMessageNode(
  node: MessageNodeCreate,
): Promise<MessageNode> {
  return requestJson<MessageNode>("/chat/nodes", {
    method: "POST",
    body: JSON.stringify(node),
  })
}

/**
 * Get a message node by ID.
 */
export async function getMessageNode(nodeId: string): Promise<MessageNode> {
  return requestJson<MessageNode>(`/chat/nodes/${nodeId}`)
}

/**
 * Update a message node.
 */
export async function updateMessageNode(
  nodeId: string,
  update: MessageNodeUpdate,
): Promise<MessageNode> {
  return requestJson<MessageNode>(`/chat/nodes/${nodeId}`, {
    method: "PATCH",
    body: JSON.stringify(update),
  })
}

/**
 * Update the current_leaf_id for a conversation.
 */
export async function updateCurrentLeaf(
  threadId: string,
  leafId: string,
): Promise<{ success: boolean }> {
  return requestJson<{ success: boolean }>(
    `/chat/conversations/${threadId}/current-leaf`,
    {
      method: "PATCH",
      body: JSON.stringify({ current_leaf_id: leafId }),
    },
  )
}

/**
 * Get the path from root to a specific node.
 */
export async function getNodePath(nodeId: string): Promise<MessageNode[]> {
  return requestJson<MessageNode[]>(`/chat/nodes/${nodeId}/path`)
}

/**
 * Get the next branch_index for a new sibling node.
 */
export async function getNextBranchIndex(
  parentId: string | null,
): Promise<{ next_branch_index: number }> {
  const path = parentId ? `/chat/nodes/${parentId}/next-branch-index` : "/chat/nodes/null/next-branch-index"
  return requestJson<{ next_branch_index: number }>(path)
}
