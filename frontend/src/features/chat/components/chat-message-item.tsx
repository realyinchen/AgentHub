import {
  BrainIcon,
  CheckIcon,
  ChevronDown,
  CopyIcon,
  PencilIcon,
  RefreshCcwIcon,
  WrenchIcon,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Action, Actions } from "@/components/ai/actions"
import { Message, MessageContent } from "@/components/ai/message"
import { cn } from "@/lib/utils"
import type { LocalChatMessage, ToolCallInfo, StoredToolCallInfo } from "@/types"
import { MarkdownContent } from "@/components/ui/markdown-content"
import { useI18n } from "@/i18n"

type ChatMessageItemProps = {
  message: LocalChatMessage
  onRetry?: () => void
  retryDisabled?: boolean
  calledTools?: ToolCallInfo[]
  isAgentThinking?: boolean
  activeToolName?: string | null
  thinkingContent?: string // Accumulated thinking content (streaming)
  isProcessing?: boolean // Processing, no content received yet
  isStreaming?: boolean // Whether the current message is streaming
  onEditMessage?: (newContent: string) => void // Callback when user edits their message
  editDisabled?: boolean // Whether edit is disabled
}

type SourceLink = {
  href: string
  title: string
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
    return []
  }
}

/**
 * Group consecutive tool calls with the same name.
 * Returns an array of grouped tool calls with count.
 */
type GroupedToolCall = {
  name: string
  count: number
  tools: ToolCallInfo[]
}

function groupConsecutiveToolCalls(tools: ToolCallInfo[]): GroupedToolCall[] {
  if (tools.length === 0) {
    return []
  }

  const groups: GroupedToolCall[] = []
  let currentGroup: GroupedToolCall = {
    name: tools[0].name,
    count: 1,
    tools: [tools[0]],
  }

  for (let i = 1; i < tools.length; i++) {
    const tool = tools[i]
    if (tool.name === currentGroup.name) {
      // Same tool as previous - add to current group
      currentGroup.count++
      currentGroup.tools.push(tool)
    } else {
      // Different tool - push current group and start new one
      groups.push(currentGroup)
      currentGroup = {
        name: tool.name,
        count: 1,
        tools: [tool],
      }
    }
  }

  // Don't forget to push the last group
  groups.push(currentGroup)

  return groups
}

export function ChatMessageItem({ 
  message, 
  onRetry, 
  retryDisabled = false, 
  calledTools = [], 
  activeToolName = null,
  thinkingContent = "",
  isProcessing = false,
  isStreaming = false,
  onEditMessage,
  editDisabled = false,
}: ChatMessageItemProps) {
  const messageRef = useRef<HTMLDivElement>(null)
  const { t } = useI18n()
  const isUser = message.type === "human"
  const isAI = message.type === "ai"
  const isTool = message.type === "tool"
  const sources = parseSources(message)
  const [copied, setCopied] = useState(false)
  const [showThinkingProcess, setShowThinkingProcess] = useState(false)
  const [showToolCalls, setShowToolCalls] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [editContent, setEditContent] = useState(message.content)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [isHovered, setIsHovered] = useState(false)
  
  // Parse thinking content from message (for history) or use streaming content
  const historicalThinking = parseThinkingContent(message)
  const displayThinkingContent = thinkingContent || historicalThinking || ""
  const hasThinkingContent = Boolean(displayThinkingContent)
  
  // Merge calledTools from streaming with stored tool_info from history
  // For streaming messages, use calledTools; for history messages, use stored tool_info
  const allTools = calledTools.length > 0 ? calledTools : parseStoredToolInfo(message)
  const hasToolCalls = allTools.length > 0

  // Don't render tool type messages (tool call results)
  if (isTool) {
    return null
  }

  // For AI messages, don't render if there's no content, thinking content, or tool calls
  // This avoids empty bubbles
  // But during streaming, show processing state even without content
  if (isAI && !isStreaming && !message.content.trim() && !hasThinkingContent && !hasToolCalls) {
    return null
  }

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
  const showThinkingButton = hasThinkingContent
  const showToolCallButton = hasToolCalls

  return (
    <article
      id={`message-${message.local_id}`}
      ref={messageRef}
      className={cn("flex w-full items-start gap-3", isUser && "justify-end")}
    >
      <Message
        from={isUser ? "user" : "assistant"}
        className={cn(
          "min-w-0 shrink-0",
          isUser
            ? "w-auto max-w-[72%] items-end"
            : "w-full max-w-[85%]",
        )}
        onMouseEnter={() => isUser && setIsHovered(true)}
        onMouseLeave={() => isUser && setIsHovered(false)}
      >
        <MessageContent
          className={cn(
            "max-w-full overflow-visible rounded-2xl px-4 py-3",
            isUser
              ? "w-fit mr-3 text-white"
              : "w-full bg-muted/60 text-foreground",
          )}
          style={isUser ? { backgroundColor: "#1AAD19" } : undefined}
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

          {/* Processing state - show loading animation before any content arrives */}
          {isAI && isStreaming && isProcessing && !message.content.trim() && !displayThinkingContent && allTools.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="inline-flex gap-1">
                <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
                <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
                <span className="size-1.5 animate-bounce rounded-full bg-current" />
              </span>
              <span>{t("message.processing")}</span>
            </div>
          ) : null}

          {/* Thinking process - only show when there is actual thinking content */}
          {isAI && hasThinkingContent && isStreaming && !message.content.trim() ? (
            <details className="rounded-lg border border-border/60 bg-background/50 p-2 text-xs mb-2" open>
              <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground">
                <BrainIcon className="size-3" />
                {t("message.thinking")}
              </summary>
              <div className="mt-2 whitespace-pre-wrap text-muted-foreground max-h-40 overflow-y-auto">
                {displayThinkingContent}
              </div>
            </details>
          ) : null}

          {/* Tool calls during streaming - show grouped consecutive calls */}
          {isAI && allTools.length > 0 && isStreaming && !message.content.trim() ? (
            <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-xs mb-2">
              <div className="space-y-1.5">
                {groupConsecutiveToolCalls(allTools).map((group, groupIndex) => {
                  // Check if any tool in the group is still calling
                  const hasCallingTool = group.tools.some(t => t.status === "calling")
                  
                  return (
                    <div key={`group-${groupIndex}`} className="flex items-center gap-2">
                      {hasCallingTool ? (
                        <span className="inline-flex gap-1">
                          <span className="size-1 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
                          <span className="size-1 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
                          <span className="size-1 animate-bounce rounded-full bg-current" />
                        </span>
                      ) : (
                        <CheckIcon className="size-3 text-green-500" />
                      )}
                      <span className={hasCallingTool ? "text-muted-foreground" : "text-foreground"}>
                        {group.name}
                        {group.count > 1 ? (
                          <span className="ml-1 text-muted-foreground">×{group.count}</span>
                        ) : null}
                      </span>
                      {hasCallingTool ? (
                        <span className="text-muted-foreground">...</span>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </div>
          ) : activeToolName && isStreaming && !message.content.trim() ? (
            <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-xs mb-2">
              <div className="flex items-center gap-2">
                <span className="inline-flex gap-1">
                  <span className="size-1 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
                  <span className="size-1 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
                  <span className="size-1 animate-bounce rounded-full bg-current" />
                </span>
                <span className="text-muted-foreground">{activeToolName}...</span>
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
                ref={textareaRef}
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className="w-full min-h-[60px] resize-none rounded-lg bg-white/10 p-2 text-sm text-white placeholder-white/60 focus:outline-none focus:ring-2 focus:ring-white/30"
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
                  className="rounded-md px-2 py-1 text-xs text-white/80 hover:bg-white/10"
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (editContent.trim() && editContent.trim() !== message.content.trim() && onEditMessage) {
                      onEditMessage(editContent.trim())
                    }
                    setIsEditing(false)
                  }}
                  disabled={!editContent.trim() || editContent.trim() === message.content.trim() || editDisabled}
                  className="rounded-md bg-white/20 px-2 py-1 text-xs text-white hover:bg-white/30 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {t("message.sendEdit")}
                </button>
              </div>
            </div>
          ) : (
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {message.content}
            </p>
          )}
        </MessageContent>

        {/* User message actions: copy and edit - only show on hover */}
        {isUser && !isEditing && isHovered ? (
          <Actions className="pt-1 justify-end">
            <Action
              onClick={() => {
                void handleCopy()
              }}
              className="cursor-pointer"
              tooltip={copied ? t("common.copied") : t("common.copy")}
              label={copied ? t("message.copiedMessage") : t("message.copyMessage")}
            >
              {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
            </Action>
            <Action
              onClick={() => setIsEditing(true)}
              tooltip={t("common.edit")}
              label={t("message.editMessage")}
              className="cursor-pointer"
              disabled={editDisabled}
            >
              <PencilIcon className="size-4" />
            </Action>
          </Actions>
        ) : null}

        {/* Actions area: copy, retry, thinking process, tool calls */}
        {isAI && !isStreaming ? (
          <div className={cn("flex flex-col", isUser ? "items-end" : "items-start")}>
            <Actions className={cn("pt-1", isUser ? "justify-end" : "justify-start")}>
              <Action
                onClick={() => {
                  void handleCopy()
                }}
                className="cursor-pointer"
                tooltip={copied ? t("common.copied") : t("common.copy")}
                label={copied ? t("message.copiedResponse") : t("message.copyResponse")}
              >
                {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
              </Action>
              <Action
                onClick={onRetry}
                tooltip={t("common.retry")}
                label={t("message.retryResponse")}
                className="cursor-pointer"
                disabled={!onRetry || retryDisabled}
              >
                <RefreshCcwIcon className="size-4" />
              </Action>
              {showThinkingButton ? (
                <Action
                  onClick={() => setShowThinkingProcess(!showThinkingProcess)}
                  tooltip={showThinkingProcess ? t("message.hideThinkingProcess") : t("message.showThinkingProcess")}
                  label={t("message.thinkingProcess")}
                  className="cursor-pointer"
                >
                  <BrainIcon className="size-4" />
                </Action>
              ) : null}
              {showToolCallButton ? (
                <Action
                  onClick={() => setShowToolCalls(!showToolCalls)}
                  tooltip={showToolCalls ? t("message.hideToolCalls") : t("message.showToolCalls")}
                  label={t("message.toolCalls")}
                  className="cursor-pointer"
                >
                  <WrenchIcon className="size-4" />
                </Action>
              ) : null}
            </Actions>
            
            {/* Thinking process detail panel */}
            {showThinkingButton && showThinkingProcess ? (
              <div className="mt-2 w-full rounded-lg border border-border/60 bg-background/50 p-3 text-xs">
                <div className="mb-2 font-medium text-muted-foreground flex items-center gap-2">
                  <BrainIcon className="size-3" />
                  {t("message.thinkingProcess")}
                </div>
                <div className="whitespace-pre-wrap text-muted-foreground max-h-60 overflow-y-auto">
                  {displayThinkingContent}
                </div>
              </div>
            ) : null}
            
            {/* Tool calls detail panel */}
            {showToolCallButton && showToolCalls ? (
              <div className="mt-2 w-full rounded-lg border border-border/60 bg-background/50 p-3 text-xs">
                <div className="mb-2 font-medium text-muted-foreground flex items-center gap-2">
                  <WrenchIcon className="size-3" />
                  {t("message.toolCallsCount", { count: allTools.length })}
                </div>
                <div className="space-y-2">
                  {groupConsecutiveToolCalls(allTools).map((group, groupIndex) => (
                    <details key={`group-${groupIndex}`} className="rounded border border-border/40 bg-background/30">
                      <summary className="flex cursor-pointer list-none items-center gap-2 p-2">
                        <CheckIcon className="size-3 text-green-500" />
                        <div className="font-medium text-foreground">
                          {group.name}
                          {group.count > 1 ? (
                            <span className="ml-1 text-muted-foreground">×{group.count}</span>
                          ) : null}
                        </div>
                      </summary>
                      <div className="border-t border-border/30 p-2 space-y-2">
                        {group.tools.map((tool, toolIndex) => (
                          <div key={`${tool.id}-${toolIndex}`} className="text-muted-foreground">
                            {group.count > 1 ? (
                              <div className="font-medium text-foreground mb-1 text-[11px]">
                                #{toolIndex + 1}
                              </div>
                            ) : null}
                            {Object.keys(tool.args).length > 0 ? (
                              <div className="mb-1">
                                <span className="font-medium">{t("message.toolInput")}:</span>
                                <pre className="mt-0.5 whitespace-pre-wrap break-all text-[11px]">
                                  {JSON.stringify(tool.args, null, 2)}
                                </pre>
                              </div>
                            ) : null}
                            {tool.output ? (
                              <div>
                                <span className="font-medium">{t("message.toolOutput")}:</span>
                                <pre className="mt-0.5 whitespace-pre-wrap break-all text-[11px] max-h-32 overflow-y-auto">
                                  {tool.output}
                                </pre>
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </details>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </Message>
    </article>
  )
}