import {
  BrainIcon,
  CheckIcon,
  ChevronDown,
  CopyIcon,
  Loader2,
  PencilIcon,
  QuoteIcon,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Message, MessageContent } from "@/components/ai/message"
import { cn } from "@/lib/utils"
import type { LocalChatMessage, ToolCallInfo, StoredToolCallInfo } from "@/types"
import { MarkdownContent } from "@/components/ui/markdown-content"
import { Separator } from "@/components/ui/separator"
import { useI18n } from "@/i18n"

type ChatMessageItemProps = {
  message: LocalChatMessage
  messageIndex: number // Index in messages array for edit functionality
  calledTools?: ToolCallInfo[]
  isAgentThinking?: boolean
  thinkingContent?: string // Accumulated thinking content (streaming)
  isProcessing?: boolean // Processing, no content received yet (kept for backward compatibility, not used)
  isStreaming?: boolean // Whether the current message is streaming
  sessionId?: string | null // session_id for this AI message
  hasSteps?: boolean // Whether this AI message has steps (tool calls or thinking)
  isSelected?: boolean // Whether this message's session is currently selected in sidebar
  onEditMessage?: (newContent: string, messageIndex: number) => void // Callback when user edits their message, with index
  editDisabled?: boolean // Whether edit is disabled
  onQuote?: () => void // Callback when user wants to quote this message
  quoteDisabled?: boolean // Whether quote is disabled
  onJumpToMessage?: (localId: string) => void // Jump to quoted message
  onToggleSidebarProcess?: () => void // Toggle sidebar process panel visibility
  onSelectSession?: (sessionId: string) => void // Select a specific session to view
  onSelectRequestId?: (requestId: string | null) => void // Select request_id for DAG viewing
}

type SourceLink = {
  href: string
  title: string
}

/**
 * Parse quoted content from message.
 * Format: "> quoted content\n\nnew message"
 * Returns { quotedContent, newContent } or null if not a quoted message.
 */
function parseQuotedContent(content: string): { quotedContent: string; newContent: string } | null {
  // Check if message starts with "> "
  if (!content.startsWith("> ")) {
    return null
  }

  // Find the separator "\n\n" after the quoted content
  const separatorIndex = content.indexOf("\n\n")
  if (separatorIndex === -1) {
    return null
  }

  // Extract quoted content (remove "> " prefix)
  const quotedContent = content.slice(2, separatorIndex)
  // Extract new content (after "\n\n")
  const newContent = content.slice(separatorIndex + 2)

  if (!quotedContent.trim() || !newContent.trim()) {
    return null
  }

  return { quotedContent, newContent }
}

function parseSources(message: LocalChatMessage): SourceLink[] {
  const candidates = [
    message.custom_data?.sources,
    message.response_metadata?.sources,
  ]

  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) {
      continue
    }

    const normalized = candidate
      .map((item) => {
        if (!item || typeof item !== "object") {
          return null
        }

        const record = item as Record<string, unknown>
        const href =
          typeof record.href === "string"
            ? record.href
            : typeof record.url === "string"
              ? record.url
              : null

        if (!href) {
          return null
        }

        return {
          href,
          title:
            typeof record.title === "string"
              ? record.title
              : typeof record.name === "string"
                ? record.name
                : href,
        }
      })
      .filter((item): item is SourceLink => Boolean(item))

    if (normalized.length > 0) {
      return normalized
    }
  }

  return []
}

/**
 * Parse thinking content from message.
 * Checks multiple sources for compatibility.
 */
function parseThinkingContent(message: LocalChatMessage): string | null {
  // 1. Check custom_data.thinking (saved from backend)
  const thinkingFromCustomData = message.custom_data?.thinking
  if (typeof thinkingFromCustomData === "string" && thinkingFromCustomData.trim()) {
    return thinkingFromCustomData.trim()
  }

  // 2. Check response_metadata.thinking
  const thinkingFromMetadata = message.response_metadata?.thinking
  if (typeof thinkingFromMetadata === "string" && thinkingFromMetadata.trim()) {
    return thinkingFromMetadata.trim()
  }

  // 3. Check reasoning_content
  const reasoningContent = message.reasoning_content
  if (typeof reasoningContent === "string" && reasoningContent.trim()) {
    return reasoningContent.trim()
  }

  // 4. Check custom_data.reasoning
  const reasoningFromCustomData = message.custom_data?.reasoning
  if (typeof reasoningFromCustomData === "string" && reasoningFromCustomData.trim()) {
    return reasoningFromCustomData.trim()
  }

  return null
}

/**
 * Parse stored tool info from message custom_data.
 * This is used to display tool calls from conversation history.
 */
function parseStoredToolInfo(message: LocalChatMessage): ToolCallInfo[] {
  try {
    const toolInfo = message.custom_data?.tool_info

    if (!Array.isArray(toolInfo) || toolInfo.length === 0) {
      return []
    }

    // Check if all items have order field - if so, sort by order
    // Otherwise, keep original array order (which should be correct from backend)
    const hasOrderField = toolInfo.every(
      (item) => {
        const stored = item as StoredToolCallInfo
        return stored && typeof stored.order === "number"
      }
    )

    const sortedInfo = hasOrderField
      ? [...toolInfo].sort((a, b) => {
        const orderA = (a as StoredToolCallInfo).order as number
        const orderB = (b as StoredToolCallInfo).order as number
        return orderA - orderB
      })
      : toolInfo

    return sortedInfo.map((info, index): ToolCallInfo => {
      const stored = info as StoredToolCallInfo
      return {
        name: (stored?.name as string) || "unknown",
        id: (stored?.id as string) || `tool-${index}-${Date.now()}`,
        args: (stored?.args as Record<string, unknown>) || {},
        output: (stored?.output as string | undefined) || undefined,
        status: "completed" as const,
      }
    })
  } catch {
    // Ignore parsing errors for malformed tool info
    return []
  }
}
export function ChatMessageItem({
  message,
  messageIndex,
  calledTools = [],
  thinkingContent = "",
  isStreaming = false,
  isSelected = false,
  onEditMessage,
  editDisabled = false,
  onQuote,
  quoteDisabled = false,
  onJumpToMessage,
  onSelectRequestId,
}: ChatMessageItemProps) {
  const { t } = useI18n()
  const isUser = message.type === "human"
  const isAI = message.type === "ai"
  const isTool = message.type === "tool"
  const sources = parseSources(message)
  const [copied, setCopied] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  // For quoted messages, edit only the user_content; otherwise edit the full content
  const [editContent, setEditContent] = useState(
    (isUser && message.custom_data?.user_content as string | undefined) || message.content
  )
  const [isActionsHovered, setIsActionsHovered] = useState(false)

  // Parse thinking content from message (for history) or use streaming content
  const historicalThinking = parseThinkingContent(message)
  const displayThinkingContent = thinkingContent || historicalThinking || ""
  const hasThinkingContent = Boolean(displayThinkingContent)

  // Ref for thinking content container - auto-scroll during streaming
  const thinkingContentRef = useRef<HTMLDivElement>(null)

  // Auto-scroll thinking content to bottom when content grows during streaming
  useEffect(() => {
    if (isStreaming && thinkingContent && thinkingContentRef.current) {
      thinkingContentRef.current.scrollTop = thinkingContentRef.current.scrollHeight
    }
  }, [isStreaming, thinkingContent])

  // Merge calledTools from streaming with stored tool_info from history
  // For streaming messages, use calledTools; for history messages, use stored tool_info
  const allTools = calledTools.length > 0 ? calledTools : parseStoredToolInfo(message)
  const hasToolCalls = allTools.length > 0


  useEffect(() => {
    if (!copied) {
      return
    }

    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  const handleCopy = async () => {
    if (!message.content.trim()) {
      return
    }

    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
    } catch {
      // Ignore clipboard failures in unsupported environments.
    }
  }

  // Determine what to show in the action bar
  // Show brain icon if this AI message has request_id (for DAG viewing)
  const hasRequestId = Boolean(message.request_id)
  const showBrainIcon = hasRequestId

  // Get quoted message ID and user content from custom_data
  const quotedMessageId = message.custom_data?.quoted_message_id as string | undefined
  const userContent = message.custom_data?.user_content as string | undefined

  // Check if this is a quoted message (has quoted_message_id and user_content)
  const isQuotedMessage = isUser && quotedMessageId && userContent

  // Parse quoted content from message content for display
  // Format: "> quoted content\n\nuser message"
  const quotedParts = isQuotedMessage ? parseQuotedContent(message.content) : null

  // Truncate quoted content to 100 chars with underscore
  const getTruncatedQuote = (content: string) => {
    if (content.length > 100) {
      return `${content.slice(0, 100)}_`
    }
    return content
  }

  // Don't render tool type messages (tool call results)
  if (isTool) {
    return null
  }

  // For AI messages, don't render if there's no content, thinking content, or tool calls
  // This avoids empty bubbles
  // But during streaming with processing state, show the loader even without content
  if (isAI && !isStreaming && !message.content.trim() && !hasThinkingContent && !hasToolCalls) {
    return null
  }

  // During streaming, if there's no content, thinking, or tools, return null
  // The center loader (in chat-main-panel.tsx) will show instead
  if (isAI && isStreaming && !message.content.trim() && !hasThinkingContent && !hasToolCalls) {
    return null
  }

  return (
    <article
      id={`message-${message.local_id}`}
      className={cn("flex w-full items-start gap-3", isUser && "justify-end")}
    >
      <Message
        from={isUser ? "user" : "assistant"}
        className={cn(
          "min-w-0 shrink-0 transition-all duration-300",
          isUser
            ? "w-auto max-w-[72%] items-end"
            : "w-full max-w-[85%]",
          isAI && isSelected && "scale-[1.01]"
        )}
      >
        <MessageContent
          className={cn(
            "max-w-full overflow-visible rounded-3xl px-5 py-3.5 text-[15px] leading-relaxed transition-all duration-300",
            isUser
              ? "w-fit mr-3 bg-user-bubble text-user-bubble-foreground"
              : "w-full bg-ai-bubble text-foreground border border-border/50",
            // Add selected highlight for AI messages
            isAI && isSelected && [
              "border-primary/40 shadow-[0_0_0_1px_rgba(var(--primary),0.2),0_0_20px_rgba(var(--primary),0.15)]",
              "dark:shadow-[0_0_0_1px_rgba(var(--primary),0.3),0_0_30px_rgba(var(--primary),0.2)]"
            ],
          )}
        >
          {/* Sources */}
          {sources.length > 0 ? (
            <details className="rounded-lg border border-border/80 bg-background/70 p-2 text-xs mb-2">
              <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground">
                <ChevronDown className="size-3" />
                {t("message.sources", { count: sources.length })}
              </summary>
              <div className="mt-2 space-y-1">
                {sources.map((source) => (
                  <a
                    key={source.href}
                    href={source.href}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate text-primary hover:underline"
                  >
                    {source.title}
                  </a>
                ))}
              </div>
            </details>
          ) : null}


          {/* Thinking content display - show during streaming when there's thinking content */}
          {/* Note: DashScope may send reasoning events after text tokens, so we show thinking
              content whenever it's available during streaming, regardless of text content */}
          {isAI && isStreaming && thinkingContent ? (
            <div className="rounded-lg border border-border/60 bg-muted/30 p-3 text-xs mb-2">
              <div className="flex items-center gap-2 mb-2">
                <BrainIcon className="size-3.5 text-primary animate-pulse" />
                <span className="font-medium text-muted-foreground">
                  {t("message.thinking") || "Thinking..."}
                </span>
              </div>
              <div ref={thinkingContentRef} className="whitespace-pre-wrap break-words text-muted-foreground max-h-48 overflow-y-auto">
                {thinkingContent}
              </div>
            </div>
          ) : null}

          {/* Tool calls display - ChatGPT style scrolling list */}
          {isAI && allTools.length > 0 && (isStreaming || !message.content.trim()) ? (
            <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-xs mb-2 max-h-32 overflow-y-auto">
              <div className="space-y-1.5">
                {allTools.map((tool, toolIndex) => {
                  const isCalling = tool.status === "calling"
                  const isCompleted = tool.status === "completed"
                  return (
                    <div
                      key={tool.id || `tool-${toolIndex}`}
                      className={cn(
                        "flex items-center gap-2 animate-in slide-in-from-left-2 duration-200",
                        toolIndex === allTools.length - 1 && isCalling && "bg-primary/5 -mx-1 px-1 rounded"
                      )}
                    >
                      {isCalling ? (
                        <Loader2 className="size-3 animate-spin text-primary" />
                      ) : isCompleted ? (
                        <CheckIcon className="size-3 text-green-500" />
                      ) : null}
                      <span className={cn(
                        "font-medium",
                        isCalling ? "text-foreground" : "text-muted-foreground"
                      )}>
                        {tool.name}
                      </span>
                      {isCalling && (
                        <span className="text-muted-foreground text-[10px] animate-pulse">
                          {t("message.toolRunning")}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}

          {/* Main message content */}
          {isAI ? (
            message.content ? (
              <MarkdownContent content={message.content} isStreaming={isStreaming} />
            ) : null
          ) : isEditing ? (
            <div className="space-y-2">
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className="w-full min-h-[60px] resize-none rounded-lg bg-background p-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder={t("message.editPlaceholder")}
                rows={3}
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setIsEditing(false)
                    setEditContent(message.content)
                  }}
                  className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-background/80"
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (editContent.trim() && onEditMessage) {
                      // For quoted messages, reconstruct the full content with quote
                      if (isQuotedMessage && quotedParts) {
                        const newFullContent = `> ${quotedParts.quotedContent}\n\n${editContent.trim()}`
                        // Only send if content actually changed
                        if (newFullContent !== message.content.trim()) {
                          onEditMessage(newFullContent, messageIndex)
                        }
                      } else {
                        // Regular message - check if content changed
                        if (editContent.trim() !== message.content.trim()) {
                          onEditMessage(editContent.trim(), messageIndex)
                        }
                      }
                    }
                    setIsEditing(false)
                  }}
                  disabled={!editContent.trim() || editDisabled}
                  className="rounded-md bg-primary/20 px-2 py-1 text-xs text-primary hover:bg-primary/30 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {t("message.sendEdit")}
                </button>
              </div>
            </div>
          ) : isQuotedMessage ? (
            // Render quoted message with separator - use user_content for display
            <div className="space-y-2">
              {/* Quoted content - clickable to jump to original, truncated to 100 chars */}
              <button
                type="button"
                onClick={() => {
                  if (quotedMessageId && onJumpToMessage) {
                    onJumpToMessage(quotedMessageId)
                  }
                }}
                disabled={!quotedMessageId || !onJumpToMessage}
                className={cn(
                  "text-sm text-user-bubble-foreground/70 whitespace-pre-wrap break-words text-left w-full",
                  quotedMessageId && onJumpToMessage && "cursor-pointer hover:text-user-bubble-foreground/90 underline underline-offset-2"
                )}
                title={quotedMessageId && onJumpToMessage ? t("message.jumpToOriginal") : undefined}
              >
                {quotedParts ? getTruncatedQuote(quotedParts.quotedContent) : "引用消息"}
              </button>
              {/* Separator line */}
              <Separator className="bg-user-bubble-foreground/30" />
              {/* User content - use user_content from custom_data */}
              <p className="whitespace-pre-wrap break-words text-sm leading-6">
                {userContent}
              </p>
            </div>
          ) : (
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {message.content}
            </p>
          )}
        </MessageContent>

        {/* User message actions: copy, edit, quote - always rendered, controlled by opacity */}
        {isUser && !isEditing && (
          <div
            className={cn(
              "pt-1 justify-end transition-opacity duration-200 flex items-center gap-1",
              isActionsHovered ? "opacity-100" : "opacity-0"
            )}
            onMouseEnter={() => setIsActionsHovered(true)}
            onMouseLeave={() => setIsActionsHovered(false)}
          >
            <button
              onClick={() => void handleCopy()}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
              title={copied ? t("common.copied") : t("common.copy")}
            >
              {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
            </button>
            <button
              onClick={() => setIsEditing(true)}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
              title={t("common.edit")}
              disabled={editDisabled}
            >
              <PencilIcon className="size-4" />
            </button>
            {onQuote ? (
              <button
                onClick={onQuote}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
                title={t("message.quote")}
                disabled={quoteDisabled}
              >
                <QuoteIcon className="size-4" />
              </button>
            ) : null}
          </div>
        )}

        {/* Actions area: copy, thinking process, tool calls */}
        {isAI && !isStreaming ? (
          <div className={cn("flex flex-col", isUser ? "items-end" : "items-start")}>
            <div className={cn("pt-1 flex items-center gap-1", isUser ? "justify-end" : "justify-start")}>
              <button
                onClick={() => void handleCopy()}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
                title={copied ? t("common.copied") : t("common.copy")}
              >
                {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
              </button>
              {onQuote ? (
                <button
                  onClick={onQuote}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
                  title={t("message.quote")}
                  disabled={quoteDisabled}
                >
                  <QuoteIcon className="size-4" />
                </button>
              ) : null}

              {/* DAG icon - click to show this request's execution DAG */}
              {showBrainIcon && message.request_id ? (
                <button
                  type="button"
                  onClick={() => {
                    // Select this request_id to show its DAG
                    if (onSelectRequestId) {
                      onSelectRequestId(message.request_id || null)
                    }
                  }}
                  className={cn(
                    "p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer",
                    isSelected && "text-primary hover:text-primary"
                  )}
                  title={t("process.showProcess")}
                >
                  <BrainIcon className="size-4" />
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
      </Message>
    </article>
  )
}
