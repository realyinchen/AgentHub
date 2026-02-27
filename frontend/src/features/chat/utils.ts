import type { ChatMessage, ConversationInDB, LocalChatMessage } from "@/types"
import type { Locale } from "@/i18n"

const FALLBACK_DEFAULT_TITLES = ["New conversation", "新会话"]

export function normalizeChatMessage(message: Partial<ChatMessage>): ChatMessage {
  const toolCalls = Array.isArray(message.tool_calls)
    ? message.tool_calls.map((call) => ({
        id: String(call.id ?? crypto.randomUUID()),
        name: String(call.name ?? "tool"),
        args:
          call.args && typeof call.args === "object"
            ? (call.args as Record<string, unknown>)
            : {},
        type: call.type,
      }))
    : []

  return {
    type: (message.type as ChatMessage["type"]) ?? "ai",
    content: typeof message.content === "string" ? message.content : "",
    tool_calls: toolCalls,
    tool_call_id: message.tool_call_id ?? null,
    run_id: message.run_id ?? null,
    response_metadata:
      message.response_metadata && typeof message.response_metadata === "object"
        ? (message.response_metadata as Record<string, unknown>)
        : {},
    custom_data:
      message.custom_data && typeof message.custom_data === "object"
        ? (message.custom_data as Record<string, unknown>)
        : {},
  }
}

export function toLocalMessage(
  message: Partial<ChatMessage>,
  options?: { localId?: string; isStreaming?: boolean },
): LocalChatMessage {
  const normalized = normalizeChatMessage(message)
  return {
    ...normalized,
    local_id: options?.localId ?? crypto.randomUUID(),
    is_streaming: options?.isStreaming,
  }
}

export function sortConversationsByUpdatedAt(
  items: ConversationInDB[],
): ConversationInDB[] {
  return [...items].sort(
    (a, b) =>
      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  )
}

export function sanitizeTitle(rawTitle: string): string {
  return rawTitle.trim().replace(/\s+/g, " ").slice(0, 64)
}

export function isDefaultConversationTitle(rawTitle: string): boolean {
  const title = sanitizeTitle(rawTitle)
  return title.length === 0 || FALLBACK_DEFAULT_TITLES.includes(title)
}

export function getErrorMessage(error: unknown, fallback = "Unexpected error"): string {
  if (error instanceof Error) {
    return error.message
  }
  return fallback
}

export function formatUpdatedAt(isoString: string, locale: Locale): string {
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) {
    return ""
  }

  return date.toLocaleString(locale === "zh" ? "zh-CN" : "en-US", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function readThreadIdFromUrl(): string | null {
  const value = new URLSearchParams(window.location.search).get("thread_id")
  return value && value.trim() ? value : null
}
